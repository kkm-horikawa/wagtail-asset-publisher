"""Extract inline <style> and <script> tags from HTML content."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from typing import NamedTuple


class ExtractedAsset(NamedTuple):
    """An extracted inline asset."""

    content: str
    content_hash: str
    loading: str = ""  # "", "defer", "async", "module", "module-async"


class AssetExtractor(HTMLParser):
    """HTML parser that extracts inline <style> and <script> tags.

    Respects the ``data-no-extract`` attribute: tags with this attribute
    are left inline and not extracted.
    """

    # Non-JS script types that should never be extracted.
    _NON_JS_TYPES = frozenset({"importmap", "speculationrules"})

    def __init__(self) -> None:
        super().__init__()
        self._styles: list[ExtractedAsset] = []
        self._scripts: list[ExtractedAsset] = []
        self._current_tag: str | None = None
        self._current_content: list[str] = []
        self._skip_current: bool = False
        self._is_external_script: bool = False
        self._current_loading: str = ""

    @property
    def styles(self) -> list[ExtractedAsset]:
        return list(self._styles)

    @property
    def scripts(self) -> list[ExtractedAsset]:
        return list(self._scripts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
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

        if tag == "script":
            self._current_loading = self._resolve_loading_strategy(attr_dict)

    def handle_data(self, data: str) -> None:
        if (
            self._current_tag
            and not self._skip_current
            and not self._is_external_script
        ):
            self._current_content.append(data)

    def handle_endtag(self, tag: str) -> None:
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
                    )
                    self._scripts.append(asset)

        self._current_tag = None
        self._current_content = []
        self._skip_current = False
        self._is_external_script = False
        self._current_loading = ""

    def _resolve_loading_strategy(self, attr_dict: dict[str, str | None]) -> str:
        """Determine the loading strategy from <script> tag attributes.

        Returns one of: "", "defer", "async", "module", "module-async".
        Sets ``_skip_current = True`` for non-JS types (importmap, etc.)
        so the tag is left inline.
        """
        type_attr = (attr_dict.get("type") or "").strip().lower()

        if type_attr and type_attr not in ("text/javascript", "module"):
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
    """Extract assets from a Wagtail page's StreamField content.

    Iterates over all StreamField fields on the page, renders each block,
    and extracts inline <style> and <script> tags.
    """
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


def get_page_html_for_tailwind(page: object) -> str:
    """Render full page HTML for Tailwind CSS class scanning.

    Creates a fake request and renders the page template to get
    the complete HTML output for Tailwind CLI to scan.
    """
    from django.contrib.auth.models import AnonymousUser
    from django.template.loader import render_to_string
    from django.test import RequestFactory
    from wagtail.models import Page

    if not isinstance(page, Page):
        return ""

    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    template = page.get_template(request)
    context = page.get_context(request)
    return render_to_string(template, context, request=request)
