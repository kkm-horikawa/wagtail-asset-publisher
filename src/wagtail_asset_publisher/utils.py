"""Build orchestration for wagtail-asset-publisher.

Pipeline: Extract -> Build -> Publish -> Record
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .conf import get_setting
from .extractors import (
    compute_content_hash,
    extract_assets_from_page,
    get_page_html_for_tailwind,
)
from .middleware import invalidate_cache

logger = logging.getLogger(__name__)


def build_page_assets(page: Any) -> None:
    """Main entry point: extract, build, publish, and record assets for a page."""
    storage = get_storage()
    _process_css(page, storage)
    _process_js(page, storage)


def _process_css(page: Any, storage: Any) -> None:
    """Process CSS assets for a page."""
    from .models import PublishedAsset

    builder = get_builder(get_setting("CSS_BUILDER"))

    styles, _ = extract_assets_from_page(page)
    extracted_css = [s.content for s in styles]
    content_hashes = [s.content_hash for s in styles]

    if builder.requires_html_content:
        html_content = get_page_html_for_tailwind(page)
        built_css = builder.build(html_content, extracted_css, "css")
    else:
        built_css = builder.build(None, extracted_css, "css")

    if not built_css:
        _clear_asset(page, "css", storage)
        invalidate_cache(page.pk)
        return

    if get_setting("MINIFY_CSS"):
        built_css = _minify_css(built_css)

    css_hash = compute_content_hash(built_css, get_setting("HASH_LENGTH"))
    prefix = get_setting("CSS_PREFIX")
    filename = f"{prefix}{page.pk}-{css_hash}.css"

    _clear_asset(page, "css", storage)

    url = storage.save(filename, built_css)

    PublishedAsset.objects.update_or_create(
        page=page,
        asset_type="css",
        defaults={"url": url, "content_hashes": content_hashes},
    )
    logger.info("Published CSS for page %d: %s", page.pk, url)
    invalidate_cache(page.pk)


def _process_js(page: Any, storage: Any) -> None:
    """Process JS assets for a page, grouped by loading strategy."""
    from .models import PublishedAsset

    builder = get_builder(get_setting("JS_BUILDER"))
    _, scripts = extract_assets_from_page(page)

    groups: dict[str, list[Any]] = {}
    for script in scripts:
        groups.setdefault(script.loading, []).append(script)

    _clear_js_assets(page, storage)

    if not groups:
        invalidate_cache(page.pk)
        return

    for loading, group_scripts in groups.items():
        extracted_js = [s.content for s in group_scripts]
        content_hashes = [s.content_hash for s in group_scripts]

        built_js = builder.build(None, extracted_js, "js")
        if not built_js:
            continue

        if get_setting("OBFUSCATE_JS"):
            built_js = _optimize_js(built_js)

        js_hash = compute_content_hash(built_js, get_setting("HASH_LENGTH"))
        prefix = get_setting("JS_PREFIX")
        loading_suffix = f"-{loading}" if loading else ""
        filename = f"{prefix}{page.pk}-{js_hash}{loading_suffix}.js"

        url = storage.save(filename, built_js)

        PublishedAsset.objects.update_or_create(
            page=page,
            asset_type="js",
            loading=loading,
            defaults={"url": url, "content_hashes": content_hashes},
        )
        logger.info(
            "Published JS (%s) for page %d: %s",
            loading or "blocking",
            page.pk,
            url,
        )

    invalidate_cache(page.pk)


def _optimize_js(content: str) -> str:
    """Optimize JS content using terser (preferred) or rjsmin (fallback).

    Falls back gracefully if neither tool is available.
    """
    terser_path = _find_terser()
    if terser_path is not None:
        try:
            result = subprocess.run(  # noqa: S603
                [terser_path, *get_setting("TERSER_OPTIONS")],
                input=content,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            return result.stdout
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            OSError,
        ) as e:
            logger.warning("terser failed: %s. Falling back to rjsmin.", e)

    try:
        import rjsmin  # type: ignore[import-not-found, import-untyped]

        return rjsmin.jsmin(content)  # type: ignore[no-any-return]
    except ImportError:
        logger.warning(
            "Neither terser nor rjsmin is available. JS optimization skipped."
        )
        return content


def _minify_css(content: str) -> str:
    """Minify CSS content using rcssmin.

    Falls back gracefully if rcssmin is not installed.
    """
    try:
        import rcssmin  # type: ignore[import-not-found, import-untyped]

        return rcssmin.cssmin(content)  # type: ignore[no-any-return]
    except ImportError:
        logger.warning("rcssmin is not installed. CSS minification skipped.")
        return content


def _find_terser() -> str | None:
    """Find the terser CLI binary.

    Search order: TERSER_PATH setting -> node_modules/.bin/terser -> PATH.
    """
    explicit: str | None = get_setting("TERSER_PATH")
    if explicit:
        return explicit
    from django.conf import settings as django_settings

    base_dir = getattr(django_settings, "BASE_DIR", None)
    if base_dir is not None:
        local = Path(base_dir) / "node_modules" / ".bin" / "terser"
        if local.exists():
            return str(local)
    return shutil.which("terser")


def _clear_asset(page: Any, asset_type: str, storage: Any) -> None:
    """Remove a single published asset (CSS) from storage and DB."""
    from .models import PublishedAsset

    try:
        asset = PublishedAsset.objects.get(page=page, asset_type=asset_type)
        path = _extract_path_from_url(asset.url)
        if path and storage.exists(path):
            storage.delete(path)
        asset.delete()
    except PublishedAsset.DoesNotExist:
        pass


def _clear_js_assets(page: Any, storage: Any) -> None:
    """Remove ALL JS published assets for a page from storage and DB."""
    from .models import PublishedAsset

    for asset in PublishedAsset.objects.filter(page=page, asset_type="js"):
        path = _extract_path_from_url(asset.url)
        if path and storage.exists(path):
            storage.delete(path)
        asset.delete()


def _extract_path_from_url(url: str) -> str:
    """Extract the storage path from a URL."""
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    for prefix_key in ("CSS_PREFIX", "JS_PREFIX"):
        prefix = get_setting(prefix_key)
        if path.startswith(prefix):
            return path
    # For full URLs, try matching the prefix in the full path
    for prefix_key in ("CSS_PREFIX", "JS_PREFIX"):
        prefix = get_setting(prefix_key)
        idx = path.find(prefix)
        if idx >= 0:
            return path[idx:]
    return ""


def get_builder(builder_path: str) -> Any:
    """Import and instantiate a builder class."""
    cls = import_class(builder_path)
    return cls()


def get_storage() -> Any:
    """Import and instantiate the configured storage backend."""
    storage_path = get_setting("STORAGE_BACKEND")
    cls = import_class(storage_path)
    return cls()


def import_class(dotted_path: str) -> type:
    """Import a class from a dotted path string."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, class_name)  # type: ignore[no-any-return]
