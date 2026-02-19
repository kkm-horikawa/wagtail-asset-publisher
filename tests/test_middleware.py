"""Tests for wagtail_asset_publisher.middleware module.

Covers AssetPublisherMiddleware, helper functions (_is_preview_request,
_get_page, _get_published_assets, _process_html, _strip_matching_tags,
_escape_attr, _minify_html), invalidate_cache, and script loading
attribute injection.
"""

import logging
import sys
from unittest import mock

import pytest

from wagtail_asset_publisher.extractors import compute_content_hash
from wagtail_asset_publisher.middleware import (
    _JS_LOADING_ATTRS,
    _JS_LOADING_ORDER,
    CACHE_KEY_PREFIX,
    CACHE_TIMEOUT,
    AssetPublisherMiddleware,
    _escape_attr,
    _get_page,
    _get_published_assets,
    _is_preview_request,
    _minify_html,
    _process_html,
    _strip_matching_tags,
    invalidate_cache,
)


class TestIsPreviewRequest:
    """Tests for _is_preview_request helper."""

    def test_is_preview_true_via_attribute(self):
        """Request with is_preview=True is detected as preview.

        Purpose: Verify that the Wagtail-set is_preview attribute is respected.
        Category: Normal case
        Target: _is_preview_request(request)
        Technique: Equivalence partitioning
        Test data: Mock request with is_preview=True
        """
        request = mock.Mock()
        request.is_preview = True
        request.path = "/some/page/"

        result = _is_preview_request(request)

        assert result is True

    def test_is_preview_true_via_edit_preview_path(self):
        """Request with '/edit/preview/' in path is detected as preview.

        Purpose: Verify fallback URL pattern detection for preview mode.
        Category: Normal case
        Target: _is_preview_request(request)
        Technique: Equivalence partitioning
        Test data: Path containing /edit/preview/
        """
        request = mock.Mock(spec=[])
        request.path = "/admin/pages/42/edit/preview/"

        result = _is_preview_request(request)

        assert result is True

    def test_is_preview_true_via_preview_suffix(self):
        """Request ending with '/preview/' is detected as preview.

        Purpose: Verify fallback for preview URL suffix.
        Category: Normal case
        Target: _is_preview_request(request)
        Technique: Equivalence partitioning
        Test data: Path ending with /preview/
        """
        request = mock.Mock(spec=[])
        request.path = "/some/page/preview/"

        result = _is_preview_request(request)

        assert result is True

    def test_is_preview_false_for_normal_request(self):
        """Normal request without preview indicators returns False.

        Purpose: Verify that non-preview requests are correctly identified.
        Category: Normal case
        Target: _is_preview_request(request)
        Technique: Equivalence partitioning
        Test data: Standard page path without preview markers
        """
        request = mock.Mock(spec=[])
        request.path = "/blog/my-post/"

        result = _is_preview_request(request)

        assert result is False

    def test_is_preview_false_attribute_is_false(self):
        """Request with is_preview=False and non-preview path returns False.

        Purpose: Verify that explicitly False is_preview is handled correctly.
        Category: Edge case
        Target: _is_preview_request(request)
        Technique: Boundary value analysis
        Test data: is_preview=False with normal path
        """
        request = mock.Mock()
        request.is_preview = False
        request.path = "/blog/my-post/"

        result = _is_preview_request(request)

        assert result is False


class TestGetPage:
    """Tests for _get_page helper."""

    def test_returns_wagtailpage_attribute(self):
        """Returns page from request.wagtailpage attribute.

        Purpose: Verify page detection via the before_serve_page hook.
        Category: Normal case
        Target: _get_page(request)
        Technique: Equivalence partitioning
        Test data: Request with wagtailpage attribute set
        """
        page = mock.Mock()
        request = mock.Mock()
        request.wagtailpage = page

        result = _get_page(request)

        assert result is page

    def test_returns_none_when_no_page(self):
        """Returns None when no page attributes are set.

        Purpose: Verify that non-page requests return None.
        Category: Edge case
        Target: _get_page(request)
        Technique: Boundary value analysis
        Test data: Request without page attributes
        """
        request = mock.Mock(spec=[])

        result = _get_page(request)

        assert result is None


class TestGetPublishedAssets:
    """Tests for _get_published_assets with mocked DB and cache."""

    @mock.patch("wagtail_asset_publisher.middleware.cache")
    def test_returns_cached_assets(self, mock_cache):
        """Returns cached assets without DB query when cache hit.

        Purpose: Verify that the cache is checked first and DB is not queried
            when a cache entry exists.
        Category: Normal case
        Target: _get_published_assets(page_id)
        Technique: Equivalence partitioning (cache hit)
        Test data: Pre-populated cache entry
        """
        cached_data = {
            "css": {"url": "https://cdn/a.css", "content_hashes": {"hash1"}},
        }
        mock_cache.get.return_value = cached_data

        result = _get_published_assets(42)

        assert result == cached_data
        mock_cache.get.assert_called_once_with(f"{CACHE_KEY_PREFIX}42")

    @mock.patch("wagtail_asset_publisher.middleware.cache")
    @mock.patch("wagtail_asset_publisher.models.PublishedAsset")
    def test_queries_db_on_cache_miss_css(self, MockPublishedAsset, mock_cache):
        """Queries DB and populates cache on cache miss (CSS).

        Purpose: Verify that a cache miss triggers a DB lookup and the
            result is cached for subsequent requests.
        Category: Normal case
        Target: _get_published_assets(page_id)
        Technique: Equivalence partitioning (cache miss)
        Test data: Empty cache, one CSS asset in DB
        """
        mock_cache.get.return_value = None

        mock_asset = mock.Mock()
        mock_asset.asset_type = "css"
        mock_asset.url = "https://cdn/b.css"
        mock_asset.content_hashes = ["hash1", "hash2"]
        MockPublishedAsset.objects.filter.return_value = [mock_asset]

        result = _get_published_assets(42)

        assert "css" in result
        assert result["css"]["url"] == "https://cdn/b.css"
        assert result["css"]["content_hashes"] == {"hash1", "hash2"}
        mock_cache.set.assert_called_once_with(
            f"{CACHE_KEY_PREFIX}42", result, CACHE_TIMEOUT
        )

    @mock.patch("wagtail_asset_publisher.middleware.cache")
    @mock.patch("wagtail_asset_publisher.models.PublishedAsset")
    def test_queries_db_on_cache_miss_js(self, MockPublishedAsset, mock_cache):
        """Queries DB and populates cache on cache miss (JS as list).

        Purpose: Verify that JS assets are returned as a list of per-loading
            entries when fetched from the DB on cache miss.
        Category: Normal case
        Target: _get_published_assets(page_id)
        Technique: Equivalence partitioning (cache miss, JS structure)
        Test data: Empty cache, one JS asset in DB
        """
        mock_cache.get.return_value = None

        mock_asset = mock.Mock()
        mock_asset.asset_type = "js"
        mock_asset.url = "https://cdn/b.js"
        mock_asset.content_hashes = ["jshash1"]
        mock_asset.loading = "defer"
        MockPublishedAsset.objects.filter.return_value = [mock_asset]

        result = _get_published_assets(42)

        assert "js" in result
        assert isinstance(result["js"], list)
        assert len(result["js"]) == 1
        assert result["js"][0]["url"] == "https://cdn/b.js"
        assert result["js"][0]["loading"] == "defer"

    @mock.patch("wagtail_asset_publisher.middleware.cache")
    @mock.patch("wagtail_asset_publisher.models.PublishedAsset")
    def test_queries_db_on_cache_miss_multiple_js_loading(
        self, MockPublishedAsset, mock_cache
    ):
        """Multiple JS assets with different loading strategies are returned as a list.

        Purpose: Verify that _get_published_assets returns JS assets with
            different loading strategies as a properly structured list,
            one entry per loading group.
        Category: Normal case
        Target: _get_published_assets(page_id)
        Technique: Equivalence partitioning (multiple loading strategies in JS structure)
        Test data: Three JS assets: blocking, defer, module
        """
        mock_cache.get.return_value = None

        asset_blocking = mock.Mock()
        asset_blocking.asset_type = "js"
        asset_blocking.url = "https://cdn/blocking.js"
        asset_blocking.content_hashes = ["hash1"]
        asset_blocking.loading = ""

        asset_defer = mock.Mock()
        asset_defer.asset_type = "js"
        asset_defer.url = "https://cdn/defer.js"
        asset_defer.content_hashes = ["hash2"]
        asset_defer.loading = "defer"

        asset_module = mock.Mock()
        asset_module.asset_type = "js"
        asset_module.url = "https://cdn/module.js"
        asset_module.content_hashes = ["hash3"]
        asset_module.loading = "module"

        MockPublishedAsset.objects.filter.return_value = [
            asset_blocking,
            asset_defer,
            asset_module,
        ]

        result = _get_published_assets(42)

        assert "js" in result
        assert isinstance(result["js"], list)
        assert len(result["js"]) == 3

        loadings = {entry["loading"] for entry in result["js"]}
        assert loadings == {"", "defer", "module"}

    @mock.patch("wagtail_asset_publisher.middleware.cache")
    @mock.patch("wagtail_asset_publisher.models.PublishedAsset")
    def test_returns_empty_dict_when_no_assets(self, MockPublishedAsset, mock_cache):
        """Returns empty dict when page has no published assets.

        Purpose: Verify graceful handling when a page has never been published.
        Category: Edge case
        Target: _get_published_assets(page_id)
        Technique: Boundary value analysis (no assets)
        Test data: Empty DB query result
        """
        mock_cache.get.return_value = None
        MockPublishedAsset.objects.filter.return_value = []

        result = _get_published_assets(42)

        assert result == {}


class TestProcessHtml:
    """Tests for _process_html: stripping and injection logic."""

    def test_css_link_injected_before_head_close(self):
        """CSS <link> tag is injected before </head>.

        Purpose: Verify that when CSS assets exist, a stylesheet link
            is injected into the HTML head section.
        Category: Normal case
        Target: _process_html(html, assets)
        Technique: Equivalence partitioning
        Test data: Full HTML with </head> and CSS asset
        """
        html = "<html><head><title>Test</title></head><body><p>Hi</p></body></html>"
        assets = {
            "css": {
                "url": "https://cdn/page.css",
                "content_hashes": set(),
            },
        }

        result = _process_html(html, assets)

        assert '<link rel="stylesheet" href="https://cdn/page.css">' in result
        assert result.index('<link rel="stylesheet"') < result.index("</head>")

    def test_js_script_injected_before_body_close(self):
        """JS <script> tag is injected before </body>.

        Purpose: Verify that when JS assets exist, a script tag is injected
            before the closing body tag.
        Category: Normal case
        Target: _process_html(html, assets)
        Technique: Equivalence partitioning
        Test data: Full HTML with </body> and JS asset (list format)
        """
        html = "<html><head></head><body><p>Hi</p></body></html>"
        assets = {
            "js": [
                {
                    "url": "https://cdn/page.js",
                    "content_hashes": set(),
                    "loading": "",
                },
            ],
        }

        result = _process_html(html, assets)

        assert '<script src="https://cdn/page.js"></script>' in result
        assert result.index("<script src=") < result.index("</body>")

    def test_both_css_and_js_injected(self):
        """Both CSS and JS are injected when both asset types exist.

        Purpose: Verify that the middleware handles combined CSS+JS assets.
        Category: Normal case
        Target: _process_html(html, assets)
        Technique: Equivalence partitioning
        Test data: HTML with both </head> and </body>, both asset types
        """
        html = "<html><head></head><body></body></html>"
        assets = {
            "css": {"url": "https://cdn/p.css", "content_hashes": set()},
            "js": [
                {
                    "url": "https://cdn/p.js",
                    "content_hashes": set(),
                    "loading": "",
                },
            ],
        }

        result = _process_html(html, assets)

        assert '<link rel="stylesheet" href="https://cdn/p.css">' in result
        assert '<script src="https://cdn/p.js"></script>' in result


class TestProcessHtmlJsLoadingAttrs:
    """Tests for JS script tag injection with loading attributes.

    ## Decision Table: DT-JS-INJECTION

    | ID  | loading        | Expected attrs           |
    |-----|----------------|--------------------------|
    | DT1 | ""             | (none)                   |
    | DT2 | "defer"        | defer                    |
    | DT3 | "async"        | async                    |
    | DT4 | "module"       | type="module"            |
    | DT5 | "module-async" | type="module" async      |
    """

    @pytest.mark.parametrize(
        "loading,expected_tag",
        [
            pytest.param(
                "",
                '<script src="https://cdn/p.js"></script>',
                id="DT1-blocking-no-attrs",
            ),
            pytest.param(
                "defer",
                '<script src="https://cdn/p.js" defer></script>',
                id="DT2-defer-attr",
            ),
            pytest.param(
                "async",
                '<script src="https://cdn/p.js" async></script>',
                id="DT3-async-attr",
            ),
            pytest.param(
                "module",
                '<script src="https://cdn/p.js" type="module"></script>',
                id="DT4-module-type",
            ),
            pytest.param(
                "module-async",
                '<script src="https://cdn/p.js" type="module" async></script>',
                id="DT5-module-async-type-and-attr",
            ),
        ],
    )
    def test_js_script_injected_with_loading_attrs(self, loading, expected_tag):
        """Script tag is injected with correct HTML attributes for each loading value (DT-JS-INJECTION).

        Purpose: Verify that _process_html injects script tags with the correct
            HTML attributes (defer, async, type="module") based on the JS asset's
            loading value.
        Category: Normal case
        Target: _process_html(html, assets)
        Technique: Decision table
        Test data: All patterns from DT-JS-INJECTION
        """
        html = "<html><head></head><body></body></html>"
        assets = {
            "js": [
                {
                    "url": "https://cdn/p.js",
                    "content_hashes": set(),
                    "loading": loading,
                },
            ],
        }

        result = _process_html(html, assets)

        assert expected_tag in result

    def test_multiple_loading_strategies_injection_order(self):
        """Script tags with multiple loading strategies are injected in the correct order.

        Purpose: Verify that script tags are injected in the defined order:
            blocking -> defer -> module -> async -> module-async,
            ensuring predictable script execution ordering.
        Category: Normal case
        Target: _process_html(html, assets)
        Technique: State transition (injection order verification)
        Test data: Five JS assets with different loading strategies
        """
        html = "<html><head></head><body></body></html>"
        assets = {
            "js": [
                {
                    "url": "https://cdn/module-async.js",
                    "content_hashes": set(),
                    "loading": "module-async",
                },
                {
                    "url": "https://cdn/async.js",
                    "content_hashes": set(),
                    "loading": "async",
                },
                {
                    "url": "https://cdn/blocking.js",
                    "content_hashes": set(),
                    "loading": "",
                },
                {
                    "url": "https://cdn/defer.js",
                    "content_hashes": set(),
                    "loading": "defer",
                },
                {
                    "url": "https://cdn/module.js",
                    "content_hashes": set(),
                    "loading": "module",
                },
            ],
        }

        result = _process_html(html, assets)

        blocking_pos = result.index("blocking.js")
        defer_pos = result.index("defer.js")
        module_pos = result.index("module.js")
        async_pos = result.index("async.js")
        module_async_pos = result.index("module-async.js")

        assert blocking_pos < defer_pos
        assert defer_pos < module_pos
        assert module_pos < async_pos
        assert async_pos < module_async_pos

    def test_single_blocking_js_no_extra_attrs(self):
        """Blocking (loading="") script tag has no defer/async/type attributes.

        Purpose: Verify that a JS asset with loading="" is injected without
            any extra attributes.
        Category: Normal case
        Target: _process_html(html, assets)
        Technique: Equivalence partitioning (blocking class verification)
        Test data: JS asset with loading=""
        """
        html = "<html><head></head><body></body></html>"
        assets = {
            "js": [
                {
                    "url": "https://cdn/blocking.js",
                    "content_hashes": set(),
                    "loading": "",
                },
            ],
        }

        result = _process_html(html, assets)

        assert '<script src="https://cdn/blocking.js"></script>' in result
        assert "defer" not in result
        assert "async" not in result
        assert "module" not in result

    def test_js_loading_attrs_mapping_completeness(self):
        """_JS_LOADING_ATTRS has a mapping for every entry in _JS_LOADING_ORDER.

        Purpose: Verify that _JS_LOADING_ATTRS provides a mapping for all
            loading values defined in _JS_LOADING_ORDER.
        Category: Normal case
        Target: _JS_LOADING_ATTRS, _JS_LOADING_ORDER
        Technique: Equivalence partitioning (mapping completeness)
        Test data: All entries in _JS_LOADING_ORDER
        """
        for loading in _JS_LOADING_ORDER:
            assert loading in _JS_LOADING_ATTRS


class TestStripMatchingTags:
    """Tests for _strip_matching_tags: selective removal of inline tags."""

    def test_matching_style_stripped(self):
        """Inline <style> with matching content hash is removed.

        Purpose: Verify that inline styles whose content hash matches a
            published asset are stripped from the HTML.
        Category: Normal case
        Target: _strip_matching_tags(html, css_hashes, js_hashes)
        Technique: Equivalence partitioning
        Test data: HTML with one <style> whose hash matches
        """
        css_content = "body { color: red; }"
        css_hash = compute_content_hash(css_content)
        html = f"<div><style>{css_content}</style><p>Hello</p></div>"

        result = _strip_matching_tags(html, {css_hash}, set())

        assert "<style>" not in result
        assert "body { color: red; }" not in result
        assert "<p>Hello</p>" in result

    def test_non_matching_style_kept(self):
        """Inline <style> with non-matching hash is kept in HTML.

        Purpose: Verify that styles added after publishing (with different
            content hash) are preserved in the output.
        Category: Normal case
        Target: _strip_matching_tags(html, css_hashes, js_hashes)
        Technique: Equivalence partitioning (non-matching hash)
        Test data: HTML with <style> whose hash does NOT match
        """
        html = "<div><style>body { color: blue; }</style></div>"

        result = _strip_matching_tags(html, {"nonexistent_hash"}, set())

        assert "<style>" in result
        assert "body { color: blue; }" in result

    def test_matching_script_stripped(self):
        """Inline <script> with matching content hash is removed.

        Purpose: Verify that inline scripts whose content hash matches
            a published asset are stripped.
        Category: Normal case
        Target: _strip_matching_tags(html, css_hashes, js_hashes)
        Technique: Equivalence partitioning
        Test data: HTML with one <script> whose hash matches
        """
        js_content = 'console.log("hello");'
        js_hash = compute_content_hash(js_content)
        html = f"<div><script>{js_content}</script></div>"

        result = _strip_matching_tags(html, set(), {js_hash})

        assert "<script>" not in result
        assert js_content not in result

    def test_data_no_extract_style_not_stripped(self):
        """<style data-no-extract> is never stripped regardless of hash.

        Purpose: Verify that styles marked with data-no-extract are always
            preserved, even if their hash coincidentally matches.
        Category: Normal case (preservation rule)
        Target: _strip_matching_tags(html, css_hashes, js_hashes)
        Technique: Equivalence partitioning (data-no-extract)
        Test data: HTML with data-no-extract style
        """
        content = ".critical { display: block; }"
        content_hash = compute_content_hash(content)
        html = f"<style data-no-extract>{content}</style>"

        result = _strip_matching_tags(html, {content_hash}, set())

        assert "data-no-extract" in result
        assert content in result

    def test_external_script_not_stripped(self):
        """<script src="..."> (external) is never stripped.

        Purpose: Verify that external scripts with src attribute are
            preserved in the output.
        Category: Normal case (preservation rule)
        Target: _strip_matching_tags(html, css_hashes, js_hashes)
        Technique: Equivalence partitioning (external script)
        Test data: HTML with external script tag
        """
        html = '<script src="https://example.com/lib.js"></script>'

        result = _strip_matching_tags(html, set(), {"any_hash"})

        assert 'src="https://example.com/lib.js"' in result

    def test_empty_hashes_strips_nothing(self):
        """Empty hash sets result in no stripping.

        Purpose: Verify that when no hashes are provided, all tags are kept.
        Category: Edge case
        Target: _strip_matching_tags(html, css_hashes, js_hashes)
        Technique: Boundary value analysis (empty sets)
        Test data: HTML with style and script, empty hash sets
        """
        html = "<style>a {}</style><script>b();</script>"

        result = _strip_matching_tags(html, set(), set())

        assert "<style>" in result
        assert "<script>" in result


class TestEscapeAttr:
    """Tests for _escape_attr HTML attribute escaping."""

    def test_escapes_ampersand(self):
        """Ampersand is escaped to &amp;.

        Purpose: Verify proper HTML entity escaping for URLs with query params.
        Category: Normal case
        Target: _escape_attr(value)
        Technique: Equivalence partitioning
        Test data: String containing &
        """
        assert _escape_attr("a&b") == "a&amp;b"

    def test_escapes_quotes(self):
        """Double quotes are escaped to &quot;.

        Purpose: Verify safe attribute value generation.
        Category: Normal case
        Target: _escape_attr(value)
        Technique: Equivalence partitioning
        Test data: String containing "
        """
        assert _escape_attr('a"b') == "a&quot;b"

    def test_escapes_angle_brackets(self):
        """Angle brackets are escaped to &lt; and &gt;.

        Purpose: Verify XSS prevention in attribute values.
        Category: Normal case
        Target: _escape_attr(value)
        Technique: Equivalence partitioning
        Test data: String containing < and >
        """
        assert _escape_attr("<script>") == "&lt;script&gt;"

    def test_no_escaping_needed(self):
        """String without special chars passes through unchanged.

        Purpose: Verify that safe strings are not modified.
        Category: Normal case
        Target: _escape_attr(value)
        Technique: Equivalence partitioning
        Test data: Simple URL without special characters
        """
        url = "https://cdn.example.com/page.css"

        assert _escape_attr(url) == url


class TestMiddlewareCallPassThrough:
    """Tests for AssetPublisherMiddleware.__call__ pass-through conditions."""

    def test_non_html_response_passes_through(self):
        """JSON response is returned untouched.

        Purpose: Verify that non-HTML responses bypass all middleware logic.
        Category: Normal case
        Target: AssetPublisherMiddleware.__call__(request)
        Technique: Equivalence partitioning (non-HTML content type)
        Test data: Response with Content-Type: application/json
        """
        request = mock.Mock(spec=[])
        request.path = "/api/data/"

        response = mock.Mock()
        response.get.return_value = "application/json"

        get_response = mock.Mock(return_value=response)
        middleware = AssetPublisherMiddleware(get_response)

        result = middleware(request)

        assert result is response

    @mock.patch("wagtail_asset_publisher.middleware._get_published_assets")
    @mock.patch("wagtail_asset_publisher.middleware._get_page")
    @mock.patch("wagtail_asset_publisher.middleware._is_preview_request")
    def test_no_wagtail_page_passes_through(
        self, mock_is_preview, mock_get_page, mock_get_assets
    ):
        """Non-page HTML request passes through without modification.

        Purpose: Verify that HTML responses for non-Wagtail-page requests
            (e.g., Django admin) are not modified.
        Category: Normal case
        Target: AssetPublisherMiddleware.__call__(request)
        Technique: Equivalence partitioning (no page on request)
        Test data: Request without wagtailpage attribute
        """
        request = mock.Mock()
        response = mock.Mock()
        response.get.return_value = "text/html; charset=utf-8"
        response.streaming = False
        mock_is_preview.return_value = False
        mock_get_page.return_value = None

        get_response = mock.Mock(return_value=response)
        middleware = AssetPublisherMiddleware(get_response)

        result = middleware(request)

        assert result is response
        mock_get_assets.assert_not_called()

    @mock.patch("wagtail_asset_publisher.middleware._get_published_assets")
    @mock.patch("wagtail_asset_publisher.middleware._get_page")
    @mock.patch("wagtail_asset_publisher.middleware._is_preview_request")
    def test_no_published_assets_passes_through(
        self, mock_is_preview, mock_get_page, mock_get_assets
    ):
        """Page without published assets passes through unchanged.

        Purpose: Verify that pages that have never been through the asset
            pipeline are not modified.
        Category: Normal case
        Target: AssetPublisherMiddleware.__call__(request)
        Technique: Equivalence partitioning (empty assets)
        Test data: Page with no published assets
        """
        request = mock.Mock()
        page = mock.Mock()
        page.pk = 42

        response = mock.Mock()
        response.get.return_value = "text/html; charset=utf-8"
        response.streaming = False

        mock_is_preview.return_value = False
        mock_get_page.return_value = page
        mock_get_assets.return_value = {}

        get_response = mock.Mock(return_value=response)
        middleware = AssetPublisherMiddleware(get_response)

        result = middleware(request)

        assert result is response

    @mock.patch("wagtail_asset_publisher.middleware._process_html")
    @mock.patch("wagtail_asset_publisher.middleware._get_published_assets")
    @mock.patch("wagtail_asset_publisher.middleware._get_page")
    @mock.patch("wagtail_asset_publisher.middleware._is_preview_request")
    def test_content_length_updated(
        self, mock_is_preview, mock_get_page, mock_get_assets, mock_process_html
    ):
        """Content-Length header is updated after HTML modification.

        Purpose: Verify that the Content-Length header reflects the modified
            content size after stripping and injection.
        Category: Normal case
        Target: AssetPublisherMiddleware.__call__(request)
        Technique: Equivalence partitioning
        Test data: Response that gets modified by _process_html
        """
        request = mock.Mock()
        page = mock.Mock()
        page.pk = 42

        original_html = "<html><head></head><body></body></html>"
        modified_html = '<html><head><link rel="stylesheet" href="x.css">\n</head><body></body></html>'

        response = mock.MagicMock()
        response.get.return_value = "text/html; charset=utf-8"
        response.charset = "utf-8"
        response.streaming = False
        response.content = original_html.encode("utf-8")

        mock_is_preview.return_value = False
        mock_get_page.return_value = page
        mock_get_assets.return_value = {
            "css": {"url": "x.css", "content_hashes": set()}
        }
        mock_process_html.return_value = modified_html

        get_response = mock.Mock(return_value=response)
        middleware = AssetPublisherMiddleware(get_response)

        middleware(request)

        response.__setitem__.assert_any_call(
            "Content-Length", len(modified_html.encode("utf-8"))
        )


class TestMiddlewarePreview:
    """Tests for preview mode handling in the middleware."""

    @mock.patch("wagtail_asset_publisher.middleware._handle_preview")
    @mock.patch("wagtail_asset_publisher.middleware._is_preview_request")
    def test_preview_request_delegates_to_handle_preview(
        self, mock_is_preview, mock_handle_preview
    ):
        """Preview requests are delegated to _handle_preview.

        Purpose: Verify that preview requests bypass the normal asset stripping
            pipeline and go through the preview handler.
        Category: Normal case
        Target: AssetPublisherMiddleware.__call__(request)
        Technique: Equivalence partitioning (preview request)
        Test data: Request identified as preview
        """
        request = mock.Mock()
        response = mock.Mock()
        response.get.return_value = "text/html; charset=utf-8"
        response.streaming = False

        mock_is_preview.return_value = True
        mock_handle_preview.return_value = response

        get_response = mock.Mock(return_value=response)
        middleware = AssetPublisherMiddleware(get_response)

        middleware(request)

        mock_handle_preview.assert_called_once_with(response)

    @mock.patch("wagtail_asset_publisher.preview.get_tailwind_cdn_script")
    @mock.patch("wagtail_asset_publisher.preview.is_tailwind_builder")
    def test_preview_injects_tailwind_cdn(self, mock_is_tailwind, mock_cdn_script):
        """Preview with Tailwind builder injects CDN script before </head>.

        Purpose: Verify that the Tailwind CDN script is injected into preview
            responses when the CSS builder is Tailwind-based.
        Category: Normal case
        Target: _handle_preview(response)
        Technique: Equivalence partitioning (Tailwind builder)
        Test data: HTML response with </head>, Tailwind builder configured
        """
        from wagtail_asset_publisher.middleware import _handle_preview

        mock_is_tailwind.return_value = True
        mock_cdn_script.return_value = '<script src="https://cdn/tailwind.js"></script>'

        response = mock.MagicMock()
        response.charset = "utf-8"
        response.content = b"<html><head></head><body></body></html>"

        result = _handle_preview(response)

        new_content = result.content
        if isinstance(new_content, bytes):
            new_content = new_content.decode("utf-8")
        assert '<script src="https://cdn/tailwind.js"></script>' in new_content

    @mock.patch("wagtail_asset_publisher.preview.is_tailwind_builder")
    def test_preview_no_cdn_for_raw_builder(self, mock_is_tailwind):
        """Preview with raw builder does not inject CDN script.

        Purpose: Verify that the CDN script is NOT injected when the CSS
            builder is not Tailwind-based (e.g., RawAssetBuilder).
        Category: Normal case
        Target: _handle_preview(response)
        Technique: Equivalence partitioning (non-Tailwind builder)
        Test data: Response with raw builder configured
        """
        from wagtail_asset_publisher.middleware import _handle_preview

        mock_is_tailwind.return_value = False

        response = mock.Mock()
        response.content = b"<html><head></head><body></body></html>"

        result = _handle_preview(response)

        assert result is response

    @mock.patch("wagtail_asset_publisher.preview.get_tailwind_cdn_script")
    @mock.patch("wagtail_asset_publisher.preview.is_tailwind_builder")
    def test_preview_no_head_tag_returns_unmodified(self, mock_is_tailwind, mock_cdn):
        """Preview response without </head> is returned unmodified.

        Purpose: Verify graceful handling of HTML without a head section.
        Category: Edge case
        Target: _handle_preview(response)
        Technique: Boundary value analysis (no </head> in HTML)
        Test data: HTML fragment without </head>
        """
        from wagtail_asset_publisher.middleware import _handle_preview

        mock_is_tailwind.return_value = True

        response = mock.Mock()
        response.charset = "utf-8"
        response.content = b"<div>No head tag here</div>"

        result = _handle_preview(response)

        assert result is response
        mock_cdn.assert_not_called()


class TestInvalidateCache:
    """Tests for invalidate_cache function."""

    @mock.patch("wagtail_asset_publisher.middleware.cache")
    def test_cache_invalidation(self, mock_cache):
        """invalidate_cache removes the cached entry for a page.

        Purpose: Verify that calling invalidate_cache deletes the correct
            cache key so the next request fetches fresh data.
        Category: Normal case
        Target: invalidate_cache(page_id)
        Technique: Equivalence partitioning
        Test data: Page ID 42
        """
        invalidate_cache(42)

        mock_cache.delete.assert_called_once_with(f"{CACHE_KEY_PREFIX}42")

    @mock.patch("wagtail_asset_publisher.middleware.cache")
    def test_cache_invalidation_different_page(self, mock_cache):
        """invalidate_cache uses correct key for different page IDs.

        Purpose: Verify that the cache key is correctly composed with
            the given page ID.
        Category: Normal case
        Target: invalidate_cache(page_id)
        Technique: Equivalence partitioning (different input)
        Test data: Page ID 999
        """
        invalidate_cache(999)

        mock_cache.delete.assert_called_once_with(f"{CACHE_KEY_PREFIX}999")


class TestTagStripperHandlers:
    """Tests for _TagStripper HTML entity and special tag handlers."""

    def test_html_comments_preserved_outside_stripped_tags(self):
        """HTML comments outside stripped tags are preserved.

        Purpose: Verify that the tag stripper preserves HTML comments
            that are not inside stripped tags.
        Category: Edge case
        Target: _strip_matching_tags via _TagStripper
        Technique: Error guessing (comment handling)
        Test data: HTML with comment alongside style tag
        """
        css_content = "a { color: red; }"
        css_hash = compute_content_hash(css_content)
        html = f"<!-- keep this --><style>{css_content}</style>"

        result = _strip_matching_tags(html, {css_hash}, set())

        assert "<!-- keep this -->" in result
        assert "<style>" not in result

    def test_entity_references_preserved(self):
        """HTML entity references (&amp;) are preserved in non-stripped content.

        Purpose: Verify that entity references in content outside stripped
            tags are correctly preserved.
        Category: Edge case
        Target: _strip_matching_tags via _TagStripper
        Technique: Error guessing (entity handling)
        Test data: HTML with entity reference
        """
        html = "<p>Tom &amp; Jerry</p>"

        result = _strip_matching_tags(html, set(), set())

        assert "&amp;" in result

    def test_doctype_preserved(self):
        """<!DOCTYPE> declaration is preserved.

        Purpose: Verify that HTML declarations are not affected by stripping.
        Category: Edge case
        Target: _strip_matching_tags via _TagStripper
        Technique: Error guessing (declaration handling)
        Test data: HTML with DOCTYPE
        """
        css_content = "body {}"
        css_hash = compute_content_hash(css_content)
        html = f"<!DOCTYPE html><html><style>{css_content}</style></html>"

        result = _strip_matching_tags(html, {css_hash}, set())

        assert "<!DOCTYPE html>" in result
        assert "<style>" not in result


class TestMinifyHtml:
    """Tests for _minify_html: HTML minification with optional minify-html library."""

    @mock.patch("wagtail_asset_publisher.conf.get_setting")
    def test_minify_disabled_returns_original_html(self, mock_get_setting):
        """MINIFY_HTML=False setting returns the input HTML unchanged.

        Purpose: Verify that _minify_html respects the MINIFY_HTML=False setting
            and returns the original HTML without attempting to import minify-html,
            ensuring operators can disable minification in their configuration.
        Category: Normal case
        Target: _minify_html(html)
        Technique: Equivalence partitioning (disabled setting)
        Test data: Sample HTML with MINIFY_HTML=False
        """
        mock_get_setting.return_value = False
        html = "<html><head></head><body>  <p>Hello</p>  </body></html>"

        result = _minify_html(html)

        assert result == html
        mock_get_setting.assert_called_once_with("MINIFY_HTML")

    @mock.patch("wagtail_asset_publisher.conf.get_setting")
    def test_minify_html_not_installed_returns_original(self, mock_get_setting):
        """Missing minify-html library returns the input HTML unchanged.

        Purpose: Verify that when MINIFY_HTML=True but the minify-html package
            is not installed, the function gracefully falls back to returning
            the original HTML, enabling optional dependency behavior.
        Category: Edge case
        Target: _minify_html(html)
        Technique: Error guessing (missing optional dependency)
        Test data: Sample HTML with minify-html not installed
        """
        mock_get_setting.return_value = True
        html = "<html><head></head><body>  <p>Hello</p>  </body></html>"

        with mock.patch.dict(sys.modules, {"minify_html": None}):
            result = _minify_html(html)

        assert result == html

    @mock.patch("wagtail_asset_publisher.conf.get_setting")
    def test_minify_exception_returns_original_and_logs_warning(
        self, mock_get_setting, caplog
    ):
        """Exception in minify_html.minify() returns original HTML and logs warning.

        Purpose: Verify that if the minify-html library raises an exception during
            minification, the original HTML is returned and a warning is logged,
            ensuring the middleware never breaks page rendering due to minification errors.
        Category: Abnormal case
        Target: _minify_html(html)
        Technique: Error guessing (library exception)
        Test data: Sample HTML with minify() raising RuntimeError
        """
        mock_get_setting.return_value = True
        html = "<html><head></head><body>  <p>Hello</p>  </body></html>"
        mock_minify_module = mock.MagicMock()
        mock_minify_module.minify.side_effect = RuntimeError("minification failed")

        with mock.patch.dict("sys.modules", {"minify_html": mock_minify_module}):
            with caplog.at_level(
                logging.WARNING, logger="wagtail_asset_publisher.middleware"
            ):
                result = _minify_html(html)

        assert result == html
        assert "HTML minification failed" in caplog.text

    @mock.patch("wagtail_asset_publisher.conf.get_setting")
    def test_minify_success_delegates_with_correct_options(self, mock_get_setting):
        """Successful minification delegates to minify_html.minify() with correct options.

        Purpose: Verify that when MINIFY_HTML=True and the library is available,
            _minify_html calls minify_html.minify() with the expected configuration
            options (minify_css, minify_js, keep_closing_tags,
            keep_html_and_head_opening_tags) and returns the minified result.
        Category: Normal case
        Target: _minify_html(html)
        Technique: Equivalence partitioning (successful minification)
        Test data: Sample HTML with mocked minify_html returning minified output
        """
        mock_get_setting.return_value = True
        html = "<html><head></head><body>  <p>Hello</p>  </body></html>"
        minified = "<html><head></head><body><p>Hello</p></body></html>"
        mock_minify_module = mock.MagicMock()
        mock_minify_module.minify.return_value = minified

        with mock.patch.dict("sys.modules", {"minify_html": mock_minify_module}):
            result = _minify_html(html)

        assert result == minified
        mock_minify_module.minify.assert_called_once_with(
            html,
            minify_css=True,
            minify_js=True,
            keep_closing_tags=True,
            keep_html_and_head_opening_tags=True,
        )


class TestMiddlewareStreamingGuard:
    """Tests for AssetPublisherMiddleware.__call__ streaming response guard."""

    def test_streaming_response_passes_through(self):
        """StreamingHttpResponse (response.streaming=True) is returned untouched.

        Purpose: Verify that streaming responses bypass all middleware processing
            because their content cannot be accessed via response.content, ensuring
            the middleware does not break file downloads or server-sent events.
        Category: Edge case
        Target: AssetPublisherMiddleware.__call__(request)
        Technique: Equivalence partitioning (streaming response)
        Test data: Response with streaming=True and text/html content type
        """
        request = mock.Mock()
        response = mock.Mock()
        response.get.return_value = "text/html; charset=utf-8"
        response.streaming = True

        get_response = mock.Mock(return_value=response)
        middleware = AssetPublisherMiddleware(get_response)

        result = middleware(request)

        assert result is response
