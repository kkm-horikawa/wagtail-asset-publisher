"""Middleware for stripping inline assets and injecting static file references."""

from __future__ import annotations

import logging
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "wap:"
CACHE_TIMEOUT = 300  # 5 minutes


class AssetPublisherMiddleware:
    """Strip extracted inline <style>/<script> and inject static file refs.

    Only activates for Wagtail page responses that have published assets.
    Non-page responses and pages without assets pass through untouched.

    In preview mode, injects Tailwind CDN script instead of published assets
    so editors can see Tailwind utility classes rendered in real time.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return response

        if _is_preview_request(request):
            return _handle_preview(response)

        page = _get_page(request)
        if page is None:
            return response

        assets = _get_published_assets(page.pk)
        if not assets:
            return response

        charset = response.charset or "utf-8"
        content = response.content.decode(charset)
        content = _process_html(content, assets)
        response.content = content.encode(charset)
        response["Content-Length"] = len(response.content)

        return response


def _is_preview_request(request: HttpRequest) -> bool:
    """Check if this is a Wagtail page preview request.

    Wagtail sets ``is_preview`` on the request during preview rendering.
    As a fallback, we check for known preview URL patterns.
    """
    if getattr(request, "is_preview", False):
        return True
    path = request.path
    return "/edit/preview/" in path or path.endswith("/preview/")


def _handle_preview(response: HttpResponse) -> HttpResponse:
    """Inject Tailwind CDN script into preview responses.

    Only injects when the CSS builder is Tailwind-based; otherwise
    returns the response unmodified.
    """
    from .preview import get_tailwind_cdn_script, is_tailwind_builder

    if not is_tailwind_builder():
        return response

    charset = response.charset or "utf-8"
    content = response.content.decode(charset)

    if "</head>" not in content:
        return response

    cdn_script = get_tailwind_cdn_script()
    content = content.replace("</head>", f"{cdn_script}\n</head>", 1)
    response.content = content.encode(charset)
    response["Content-Length"] = len(response.content)

    return response


def _get_page(request: HttpRequest) -> Any:
    """Extract the Wagtail page from the request."""
    # Wagtail sets this attribute during page serving
    page = getattr(request, "wagtailpage", None)
    if page is not None:
        return page
    return getattr(request, "_wagtail_page", None)


def _get_published_assets(page_id: int) -> dict[str, Any]:
    """Look up published assets for a page, with caching."""
    cache_key = f"{CACHE_KEY_PREFIX}{page_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    from .models import PublishedAsset

    assets: dict[str, Any] = {}
    for asset in PublishedAsset.objects.filter(page_id=page_id):
        assets[asset.asset_type] = {
            "url": asset.url,
            "content_hashes": set(asset.content_hashes),
        }

    cache.set(cache_key, assets, CACHE_TIMEOUT)
    return assets


def _process_html(html: str, assets: dict[str, Any]) -> str:
    """Strip matched inline tags and inject static file references."""
    css_hashes: set[str] = set()
    js_hashes: set[str] = set()
    if "css" in assets:
        css_hashes = assets["css"]["content_hashes"]
    if "js" in assets:
        js_hashes = assets["js"]["content_hashes"]

    if css_hashes or js_hashes:
        html = _strip_matching_tags(html, css_hashes, js_hashes)

    if "css" in assets:
        css_url = assets["css"]["url"]
        css_tag = f'<link rel="stylesheet" href="{_escape_attr(css_url)}">'
        html = html.replace("</head>", f"{css_tag}\n</head>", 1)

    if "js" in assets:
        js_url = assets["js"]["url"]
        js_tag = f'<script src="{_escape_attr(js_url)}"></script>'
        html = html.replace("</body>", f"{js_tag}\n</body>", 1)

    return html


def _escape_attr(value: str) -> str:
    """Escape a string for safe use in an HTML attribute."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _compute_hash(content: str) -> str:
    """Compute content hash for matching (delegates to extractors)."""
    from .extractors import compute_content_hash

    return compute_content_hash(content)


class _TagStripper(HTMLParser):
    """HTML parser that strips <style>/<script> tags matching given content hashes.

    Rebuilds the HTML string, omitting matched tags entirely.
    """

    def __init__(
        self,
        css_hashes: set[str],
        js_hashes: set[str],
    ) -> None:
        super().__init__(convert_charrefs=False)
        self._css_hashes = css_hashes
        self._js_hashes = js_hashes
        self._output: list[str] = []
        self._stripping: bool = False
        self._strip_tag: str | None = None
        self._strip_content: list[str] = []
        self._strip_start_text: str = ""

    def get_output(self) -> str:
        return "".join(self._output)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script") and not self._stripping:
            attr_dict = dict(attrs)
            if "data-no-extract" in attr_dict:
                self._output.append(self.get_starttag_text() or "")
                return
            # External scripts are never stripped
            if tag == "script" and "src" in attr_dict:
                self._output.append(self.get_starttag_text() or "")
                return
            self._stripping = True
            self._strip_tag = tag
            self._strip_content = []
            self._strip_start_text = self.get_starttag_text() or f"<{tag}>"
            return
        if not self._stripping:
            self._output.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if self._stripping and tag == self._strip_tag:
            content = "".join(self._strip_content).strip()
            content_hash = _compute_hash(content)

            hashes = self._css_hashes if tag == "style" else self._js_hashes
            if content_hash not in hashes:
                # Hash doesn't match -- keep the tag with original attributes
                self._output.append(self._strip_start_text)
                self._output.append("".join(self._strip_content))
                self._output.append(f"</{tag}>")

            self._stripping = False
            self._strip_tag = None
            self._strip_content = []
            self._strip_start_text = ""
        elif not self._stripping:
            self._output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._stripping:
            self._strip_content.append(data)
        else:
            self._output.append(data)

    def handle_entityref(self, name: str) -> None:
        text = f"&{name};"
        if self._stripping:
            self._strip_content.append(text)
        else:
            self._output.append(text)

    def handle_charref(self, name: str) -> None:
        text = f"&#{name};"
        if self._stripping:
            self._strip_content.append(text)
        else:
            self._output.append(text)

    def handle_comment(self, data: str) -> None:
        if not self._stripping:
            self._output.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._output.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._output.append(f"<?{data}>")

    def unknown_decl(self, data: str) -> None:
        self._output.append(f"<![{data}]>")


def _strip_matching_tags(
    html: str,
    css_hashes: set[str],
    js_hashes: set[str],
) -> str:
    """Strip <style>/<script> tags whose content hash matches."""
    stripper = _TagStripper(css_hashes, js_hashes)
    stripper.feed(html)
    return stripper.get_output()


def invalidate_cache(page_id: int) -> None:
    """Invalidate the middleware cache for a page.

    Called after publishing new assets to ensure the next request
    picks up the new URLs.
    """
    cache_key = f"{CACHE_KEY_PREFIX}{page_id}"
    cache.delete(cache_key)
