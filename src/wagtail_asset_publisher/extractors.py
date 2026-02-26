"""Extract inline <style> and <script> tags from HTML content."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from html.parser import HTMLParser
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Cache for rendered page HTML, keyed by page pk.
# Used by render_page_html_cached() context manager to avoid
# rendering the same page multiple times within a single pipeline run.
_rendered_html_cache: ContextVar[dict[int, str]] = ContextVar("_rendered_html_cache")


class ExtractedAsset(NamedTuple):
    """An extracted inline asset."""

    content: str
    content_hash: str
    loading: str = ""  # "", "defer", "async", "module", "module-async"
    position: str = "body"  # "head" or "body"


_JS_MIME_TYPES = frozenset(
    {
        "text/javascript",
        "application/javascript",
    }
)


class AssetExtractor(HTMLParser):
    """HTML parser that extracts inline <style> and <script> tags.

    Respects the ``data-no-extract`` attribute: tags with this attribute
    are left inline and not extracted.
    """

    def __init__(self) -> None:
        super().__init__()
        self._styles: list[ExtractedAsset] = []
        self._scripts: list[ExtractedAsset] = []
        self._current_tag: str | None = None
        self._current_content: list[str] = []
        self._skip_current: bool = False
        self._is_external_script: bool = False
        self._current_loading: str = ""
        self._in_head: bool = False
        self._current_position: str = "body"

    @property
    def styles(self) -> list[ExtractedAsset]:
        return list(self._styles)

    @property
    def scripts(self) -> list[ExtractedAsset]:
        return list(self._scripts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self._in_head = True
            return
        if tag == "body":
            self._in_head = False
            return

        if tag not in ("style", "script"):
            return

        attr_dict = dict(attrs)
        self._current_tag = tag
        self._current_content = []

        if "data-no-extract" in attr_dict:
            self._skip_current = True
            return

        if tag == "script" and "src" in attr_dict:
            self._is_external_script = True
            return

        self._skip_current = False
        self._is_external_script = False
        self._current_loading = ""
        self._current_position = "body"

        if tag == "script":
            self._current_loading = self._resolve_loading_strategy(attr_dict)

            # Head scripts: skip by default, opt-in with data-extract
            if self._in_head:
                if "data-extract" not in attr_dict:
                    self._skip_current = True
                    return
                self._current_position = "head"
            elif "data-head" in attr_dict:
                self._current_position = "head"

    def handle_data(self, data: str) -> None:
        if (
            self._current_tag
            and not self._skip_current
            and not self._is_external_script
        ):
            self._current_content.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
            return

        if tag != self._current_tag:
            return

        if not self._skip_current and not self._is_external_script:
            content = "".join(self._current_content).strip()
            if content:
                if tag == "style":
                    asset = ExtractedAsset(
                        content=content,
                        content_hash=compute_content_hash(content),
                    )
                    self._styles.append(asset)
                elif tag == "script":
                    asset = ExtractedAsset(
                        content=content,
                        content_hash=compute_content_hash(content),
                        loading=self._current_loading,
                        position=self._current_position,
                    )
                    self._scripts.append(asset)

        self._current_tag = None
        self._current_content = []
        self._skip_current = False
        self._is_external_script = False
        self._current_loading = ""
        self._current_position = "body"

    def _resolve_loading_strategy(self, attr_dict: dict[str, str | None]) -> str:
        """Determine the loading strategy from <script> tag attributes.

        Returns one of: "", "defer", "async", "module", "module-async".
        Sets ``_skip_current = True`` for non-JS types (importmap, etc.)
        so the tag is left inline.
        """
        type_attr = (attr_dict.get("type") or "").strip().lower()

        if not type_attr:
            pass  # missing/empty type → normal JS
        elif type_attr == "module":
            pass  # handled below
        elif type_attr in _JS_MIME_TYPES:
            pass  # explicit MIME type → still normal JS
        else:
            # Non-JS type (importmap, speculationrules, etc.) -- skip extraction
            self._skip_current = True
            return ""

        has_async = "async" in attr_dict
        has_defer = "defer" in attr_dict

        if type_attr == "module":
            return "module-async" if has_async else "module"

        # Per HTML spec, async takes precedence when both are present
        if has_async:
            return "async"
        if has_defer:
            return "defer"
        return ""


def compute_content_hash(content: str, length: int = 8) -> str:
    """Compute a short SHA-256 hash of content for matching and filenames."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]


def extract_assets(html: str) -> tuple[list[ExtractedAsset], list[ExtractedAsset]]:
    """Extract inline <style> and <script> tags from HTML.

    Args:
        html: HTML string to parse.

    Returns:
        Tuple of (styles, scripts) where each is a list of ExtractedAsset.
    """
    extractor = AssetExtractor()
    extractor.feed(html)
    return extractor.styles, extractor.scripts


def extract_assets_from_page(
    page: object,
) -> tuple[list[ExtractedAsset], list[ExtractedAsset]]:
    """Extract inline <style> and <script> assets from a Wagtail page.

    When ``EXTRACT_FROM_TEMPLATES`` is ``True`` (the default), the page is
    rendered via :func:`render_page_html` and assets are extracted from the
    full HTML output (which already includes StreamField content).
    If rendering fails, falls back to StreamField-only extraction.

    When the setting is ``False``, only StreamField blocks are scanned.
    """
    from .conf import get_setting

    if get_setting("EXTRACT_FROM_TEMPLATES"):
        html = render_page_html(page)
        if html:
            return extract_assets(html)
        # Rendering failed -- fall back to StreamField-only extraction

    return _extract_assets_from_streamfields(page)


def _extract_assets_from_streamfields(
    page: object,
) -> tuple[list[ExtractedAsset], list[ExtractedAsset]]:
    """Extract assets by scanning only StreamField blocks on the page."""
    from wagtail.fields import StreamField

    all_styles: list[ExtractedAsset] = []
    all_scripts: list[ExtractedAsset] = []

    for field in page._meta.get_fields():  # type: ignore[attr-defined]
        if not isinstance(field, StreamField):
            continue
        stream_value = getattr(page, field.name, None)
        if not stream_value:
            continue
        html = str(stream_value)
        styles, scripts = extract_assets(html)
        all_styles.extend(styles)
        all_scripts.extend(scripts)

    return all_styles, all_scripts


@contextmanager
def cached_render(page: object) -> Iterator[None]:
    """Context manager that caches ``render_page_html`` results.

    Within this context, repeated calls to ``render_page_html`` for the
    same page return the cached result instead of re-rendering.  This
    eliminates the double render that would otherwise happen when
    ``EXTRACT_FROM_TEMPLATES=True`` and the CSS builder also needs the
    rendered HTML (e.g. TailwindCSSBuilder).
    """
    pk = getattr(page, "pk", None)
    if pk is None:
        yield
        return

    cache = _rendered_html_cache.get({})
    token = _rendered_html_cache.set(cache)
    try:
        yield
    finally:
        cache.pop(pk, None)
        _rendered_html_cache.reset(token)


def render_page_html(page: object) -> str:
    """Render full page HTML via RequestFactory.

    Creates a fake request and renders the page template to get
    the complete HTML output.  Used for asset extraction and
    Tailwind CSS class scanning.

    When called inside a :func:`cached_render` context, repeated
    calls for the same page return the cached result.
    """
    pk = getattr(page, "pk", None)
    cache = _rendered_html_cache.get(None)
    if cache is not None and pk is not None and pk in cache:
        return cache[pk]

    html = _render_page_html_uncached(page)

    if cache is not None and pk is not None:
        cache[pk] = html

    return html


def _render_page_html_uncached(page: object) -> str:
    """Perform the actual page rendering (no caching)."""
    from django.contrib.auth.models import AnonymousUser
    from django.template.loader import render_to_string
    from django.test import RequestFactory
    from wagtail.models import Page

    if not isinstance(page, Page):
        return ""

    try:
        request = RequestFactory().get("/")
        request.user = AnonymousUser()

        # Set hostname from page's site to avoid DisallowedHost when
        # templates call request.build_absolute_uri() or request.get_host()
        hostname = _get_page_hostname(page)
        request.META["HTTP_HOST"] = hostname
        request.META["SERVER_NAME"] = hostname

        template = page.get_template(request)
        context = page.get_context(request)
        return render_to_string(template, context, request=request)
    except Exception:
        logger.warning(
            "Failed to render page %s (pk=%s) for asset extraction",
            type(page).__name__,
            getattr(page, "pk", "?"),
            exc_info=True,
        )
        return ""


_DEFAULT_HOSTNAME = "localhost"


def _get_page_hostname(page: object) -> str:
    """Resolve the hostname for a page's site.

    Returns a fallback when the site cannot be determined.
    """
    try:
        site = page.get_site()  # type: ignore[attr-defined]
        if site is not None:
            return str(site.hostname)
    except Exception:
        pass
    return _DEFAULT_HOSTNAME


# Backward-compatible alias
get_page_html_for_tailwind = render_page_html
