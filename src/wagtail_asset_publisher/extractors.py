"""Extract inline <style> and <script> tags from HTML content."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from typing import NamedTuple


class ExtractedAsset(NamedTuple):
    """An extracted inline asset."""

    content: str
    content_hash: str


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
                asset = ExtractedAsset(
                    content=content,
                    content_hash=compute_content_hash(content),
                )
                if tag == "style":
                    self._styles.append(asset)
                elif tag == "script":
                    self._scripts.append(asset)

        self._current_tag = None
        self._current_content = []
        self._skip_current = False
        self._is_external_script = False


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
