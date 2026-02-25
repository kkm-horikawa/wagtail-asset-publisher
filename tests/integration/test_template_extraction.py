"""Integration tests for Issue #37: full-HTML template asset extraction.

Verifies the end-to-end pipeline when EXTRACT_FROM_TEMPLATES is enabled
(default) or disabled, including CSS/JS extraction from templates, bundling
with StreamField assets, data-no-extract handling, external reference
skipping, and middleware asset injection.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from wagtail.models import Page

from wagtail_asset_publisher.extractors import (
    ExtractedAsset,
    compute_content_hash,
    extract_assets,
)
from wagtail_asset_publisher.middleware import (
    AssetPublisherMiddleware,
    _get_published_assets,
    _process_html,
    invalidate_cache,
)
from wagtail_asset_publisher.models import PublishedAsset
from wagtail_asset_publisher.utils import build_page_assets

SETTINGS_BASE = {
    "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
    "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
    "CSS_PREFIX": "page-assets/css/",
    "JS_PREFIX": "page-assets/js/",
    "HASH_LENGTH": 8,
    "MINIFY_CSS": False,
    "OBFUSCATE_JS": False,
    "MINIFY_HTML": False,
    "EXTRACT_FROM_TEMPLATES": True,
}

TEMPLATE_CSS = "body { background: #fff; font-family: sans-serif; }"
TEMPLATE_JS = "document.addEventListener('DOMContentLoaded', function() { init(); });"
STREAMFIELD_CSS = ".hero { color: blue; margin: 0 auto; }"
STREAMFIELD_JS = "console.log('streamfield');"


def _asset(content: str, loading: str = "") -> ExtractedAsset:
    return ExtractedAsset(
        content=content,
        content_hash=compute_content_hash(content),
        loading=loading,
    )


@pytest.fixture
def wagtail_page(db):
    root = Page.objects.first()
    return root.add_child(
        instance=Page(title="Template Extraction Test", slug="tmpl-extract")
    )


@pytest.mark.django_db
class TestTemplateCssExtraction:
    """Build pipeline creates PublishedAsset records from template-extracted CSS."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_template_css_creates_published_asset(self, wagtail_page):
        """Template-extracted CSS creates a PublishedAsset with a valid CSS URL.

        Purpose: Verify that when extract_assets_from_page returns CSS extracted
                 from a rendered template, build_page_assets stores it as a
                 PublishedAsset with a URL ending in .css and containing the
                 page ID.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> extract_assets_from_page -> RawAssetBuilder -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - Single CSS block from template rendering
        - EXTRACT_FROM_TEMPLATES=True (default)
        Verification scenario:
        1. Mock extract_assets_from_page to return template CSS
        2. Call build_page_assets
        3. Verify a CSS PublishedAsset is created with correct URL format
        4. Verify content_hashes contains the template CSS hash
        """
        css_asset = _asset(TEMPLATE_CSS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], []),
        ):
            build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        assert asset.url.endswith(".css")
        assert str(wagtail_page.pk) in asset.url
        assert "page-assets/css/" in asset.url
        assert compute_content_hash(TEMPLATE_CSS) in asset.content_hashes


@pytest.mark.django_db
class TestTemplateJsExtraction:
    """Build pipeline creates PublishedAsset records from template-extracted JS."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_template_js_creates_published_asset(self, wagtail_page):
        """Template-extracted JS creates a PublishedAsset with a valid JS URL.

        Purpose: Verify that when extract_assets_from_page returns JS extracted
                 from a rendered template, build_page_assets stores it as a
                 PublishedAsset with a URL ending in .js.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> extract_assets_from_page -> RawAssetBuilder -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - Single JS block from template rendering
        - EXTRACT_FROM_TEMPLATES=True (default)
        Verification scenario:
        1. Mock extract_assets_from_page to return template JS
        2. Call build_page_assets
        3. Verify a JS PublishedAsset is created with correct URL format
        4. Verify content_hashes contains the template JS hash
        """
        js_asset = _asset(TEMPLATE_JS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], [js_asset]),
        ):
            build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="js")
        assert asset.url.endswith(".js")
        assert str(wagtail_page.pk) in asset.url
        assert "page-assets/js/" in asset.url
        assert compute_content_hash(TEMPLATE_JS) in asset.content_hashes


@pytest.mark.django_db
class TestTemplatePlusStreamFieldBundling:
    """Template and StreamField assets are bundled into single files."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_template_and_streamfield_css_bundled_into_single_file(self, wagtail_page):
        """Template CSS and StreamField CSS are bundled into a single CSS file.

        Purpose: Verify that when extract_assets_from_page returns multiple CSS
                 assets (e.g. from both template and StreamField blocks in the
                 rendered HTML), they are bundled into a single PublishedAsset
                 record with both content hashes stored.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> extract_assets_from_page -> RawAssetBuilder (concatenation) -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - Two CSS assets: one from template, one from StreamField
        - EXTRACT_FROM_TEMPLATES=True
        Verification scenario:
        1. Mock extract_assets_from_page to return two CSS assets
        2. Call build_page_assets
        3. Verify exactly one CSS PublishedAsset is created
        4. Verify content_hashes contains both source hashes
        """
        template_css_asset = _asset(TEMPLATE_CSS)
        streamfield_css_asset = _asset(STREAMFIELD_CSS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([template_css_asset, streamfield_css_asset], []),
        ):
            build_page_assets(wagtail_page)

        css_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="css")
        assert css_assets.count() == 1

        asset = css_assets.first()
        assert compute_content_hash(TEMPLATE_CSS) in asset.content_hashes
        assert compute_content_hash(STREAMFIELD_CSS) in asset.content_hashes

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_template_and_streamfield_js_bundled_into_single_file(self, wagtail_page):
        """Template JS and StreamField JS (same loading strategy) are bundled.

        Purpose: Verify that when extract_assets_from_page returns multiple JS
                 assets with the same loading strategy, they are bundled into a
                 single PublishedAsset record.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> extract_assets_from_page -> RawAssetBuilder (concatenation) -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - Two blocking JS assets: one from template, one from StreamField
        Verification scenario:
        1. Mock extract_assets_from_page to return two JS assets
        2. Call build_page_assets
        3. Verify exactly one JS PublishedAsset is created
        4. Verify content_hashes contains both source hashes
        """
        template_js_asset = _asset(TEMPLATE_JS)
        streamfield_js_asset = _asset(STREAMFIELD_JS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], [template_js_asset, streamfield_js_asset]),
        ):
            build_page_assets(wagtail_page)

        js_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="js")
        assert js_assets.count() == 1

        asset = js_assets.first()
        assert compute_content_hash(TEMPLATE_JS) in asset.content_hashes
        assert compute_content_hash(STREAMFIELD_JS) in asset.content_hashes

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_combined_css_and_js_from_templates_and_streamfields(self, wagtail_page):
        """Full page with template+StreamField CSS and JS creates both asset records.

        Purpose: Verify the complete pipeline when a page has both CSS and JS
                 from templates and StreamFields. All assets are extracted once
                 and processed into separate CSS and JS PublishedAsset records.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> cached_render -> extract_assets_from_page -> _process_css + _process_js -> PublishedAsset
        Test data:
        - Two CSS assets + two JS assets (template + StreamField each)
        Verification scenario:
        1. Mock extract_assets_from_page to return CSS and JS assets
        2. Call build_page_assets
        3. Verify one CSS and one JS PublishedAsset are created
        4. Verify each record contains the correct content_hashes
        """
        all_css = [_asset(TEMPLATE_CSS), _asset(STREAMFIELD_CSS)]
        all_js = [_asset(TEMPLATE_JS), _asset(STREAMFIELD_JS)]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=(all_css, all_js),
        ):
            build_page_assets(wagtail_page)

        assert (
            PublishedAsset.objects.filter(page=wagtail_page, asset_type="css").count()
            == 1
        )
        assert (
            PublishedAsset.objects.filter(page=wagtail_page, asset_type="js").count()
            == 1
        )

        css_asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        js_asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="js")
        assert len(css_asset.content_hashes) == 2
        assert len(js_asset.content_hashes) == 2


@pytest.mark.django_db
class TestDataNoExtract:
    """Tags with data-no-extract attribute are not extracted from HTML."""

    def test_style_with_data_no_extract_is_skipped(self):
        """Inline <style data-no-extract> tags are not included in extraction results.

        Purpose: Verify that the extract_assets function respects the
                 data-no-extract attribute on style tags and excludes them
                 from the extraction results.
        Category: Normal case
        Technique: API endpoint
        Integration targets: extract_assets -> AssetExtractor -> data-no-extract handling
        Test data:
        - HTML with two style blocks: one with data-no-extract, one without
        Verification scenario:
        1. Parse HTML containing both marked and unmarked style tags
        2. Verify only the unmarked style tag is extracted
        3. Verify the marked tag's content is not in the results
        """
        html = (
            "<html><head>"
            "<style data-no-extract>.critical { display: block; }</style>"
            "<style>.hero { color: red; }</style>"
            "</head><body></body></html>"
        )
        styles, scripts = extract_assets(html)

        assert len(styles) == 1
        assert styles[0].content == ".hero { color: red; }"
        assert len(scripts) == 0

    def test_script_with_data_no_extract_is_skipped(self):
        """Inline <script data-no-extract> tags are not included in extraction results.

        Purpose: Verify that the extract_assets function respects the
                 data-no-extract attribute on script tags.
        Category: Normal case
        Technique: API endpoint
        Integration targets: extract_assets -> AssetExtractor -> data-no-extract handling
        Test data:
        - HTML with two script blocks: one with data-no-extract, one without
        Verification scenario:
        1. Parse HTML containing both marked and unmarked script tags
        2. Verify only the unmarked script tag is extracted
        """
        html = (
            "<html><head></head><body>"
            "<script data-no-extract>var critical = true;</script>"
            "<script>var app = 1;</script>"
            "</body></html>"
        )
        styles, scripts = extract_assets(html)

        assert len(scripts) == 1
        assert scripts[0].content == "var app = 1;"
        assert len(styles) == 0

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_data_no_extract_asset_not_in_published_asset_hashes(self, wagtail_page):
        """Assets with data-no-extract are not stored in PublishedAsset content_hashes.

        Purpose: Verify the full pipeline: when extract_assets_from_page
                 returns only the non-marked assets, the resulting
                 PublishedAsset only contains hashes for extracted content.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: extract_assets_from_page -> build_page_assets -> PublishedAsset.content_hashes
        Test data:
        - One extractable CSS and one data-no-extract CSS (only extractable returned by mock)
        Verification scenario:
        1. Mock extraction to return only the extractable CSS
        2. Call build_page_assets
        3. Verify PublishedAsset has exactly one content hash
        """
        extractable_css = ".hero { color: red; }"
        css_asset = _asset(extractable_css)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], []),
        ):
            build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        assert len(asset.content_hashes) == 1
        assert compute_content_hash(extractable_css) in asset.content_hashes


@pytest.mark.django_db
class TestExternalReferencesNotExtracted:
    """External <script src> and <link href> are skipped by extraction."""

    def test_external_script_src_not_extracted(self):
        """<script src="..."> tags are not included in extraction results.

        Purpose: Verify that external script tags with a src attribute are
                 not extracted, while inline scripts are.
        Category: Normal case
        Technique: API endpoint
        Integration targets: extract_assets -> AssetExtractor -> external script handling
        Test data:
        - HTML with one external script (src) and one inline script
        Verification scenario:
        1. Parse HTML containing both external and inline script tags
        2. Verify only the inline script is extracted
        """
        html = (
            "<html><head></head><body>"
            '<script src="https://cdn.example.com/lib.js"></script>'
            "<script>var inline = true;</script>"
            "</body></html>"
        )
        styles, scripts = extract_assets(html)

        assert len(scripts) == 1
        assert scripts[0].content == "var inline = true;"

    def test_link_stylesheet_not_extracted(self):
        """<link rel="stylesheet" href="..."> tags are not extracted.

        Purpose: Verify that external stylesheet links are not treated as
                 inline styles. Only <style> tags with inline content are
                 extracted.
        Category: Normal case
        Technique: API endpoint
        Integration targets: extract_assets -> AssetExtractor -> tag filtering
        Test data:
        - HTML with one <link> stylesheet and one inline <style>
        Verification scenario:
        1. Parse HTML with both link and style tags
        2. Verify only the inline style is extracted
        """
        html = (
            "<html><head>"
            '<link rel="stylesheet" href="/static/base.css">'
            "<style>.inline { color: red; }</style>"
            "</head><body></body></html>"
        )
        styles, scripts = extract_assets(html)

        assert len(styles) == 1
        assert styles[0].content == ".inline { color: red; }"

    def test_external_script_with_content_not_extracted(self):
        """<script src="...">content</script> ignores both the src and the body.

        Purpose: Verify that if a script tag has both src and inline content,
                 it is treated as external and the inline content is not extracted.
        Category: Edge case
        Technique: API endpoint
        Integration targets: extract_assets -> AssetExtractor -> external script handling
        Test data:
        - HTML with a script tag that has both src attribute and inline content
        Verification scenario:
        1. Parse HTML with script having both src and inline content
        2. Verify no scripts are extracted
        """
        html = (
            "<html><head></head><body>"
            '<script src="app.js">var x = 1;</script>'
            "</body></html>"
        )
        _, scripts = extract_assets(html)
        assert len(scripts) == 0


@pytest.mark.django_db
class TestExtractFromTemplatesFalse:
    """EXTRACT_FROM_TEMPLATES=False falls back to StreamField-only extraction."""

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            **SETTINGS_BASE,
            "EXTRACT_FROM_TEMPLATES": False,
        }
    )
    def test_streamfield_only_extraction_creates_assets(self, wagtail_page):
        """With EXTRACT_FROM_TEMPLATES=False, only StreamField assets are extracted.

        Purpose: Verify that when EXTRACT_FROM_TEMPLATES is disabled,
                 extract_assets_from_page falls back to scanning only
                 StreamField blocks. Since the test page has no StreamFields,
                 no assets should be created.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> extract_assets_from_page -> _extract_assets_from_streamfields -> PublishedAsset
        Test data:
        - EXTRACT_FROM_TEMPLATES=False
        - Wagtail Page without StreamFields
        Verification scenario:
        1. Call build_page_assets with EXTRACT_FROM_TEMPLATES=False
        2. Verify no PublishedAssets are created (page has no StreamFields)
        """
        build_page_assets(wagtail_page)

        assert not PublishedAsset.objects.filter(page=wagtail_page).exists()

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            **SETTINGS_BASE,
            "EXTRACT_FROM_TEMPLATES": False,
        }
    )
    def test_extract_from_templates_false_does_not_call_render(self, wagtail_page):
        """With EXTRACT_FROM_TEMPLATES=False, render_page_html is not called.

        Purpose: Verify that disabling EXTRACT_FROM_TEMPLATES prevents the
                 page from being rendered via RequestFactory.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: extract_assets_from_page -> _extract_assets_from_streamfields (no rendering)
        Test data:
        - EXTRACT_FROM_TEMPLATES=False
        Verification scenario:
        1. Patch render_page_html to track calls
        2. Call build_page_assets
        3. Verify render_page_html was not called
        """
        with mock.patch(
            "wagtail_asset_publisher.extractors.render_page_html"
        ) as mock_render:
            build_page_assets(wagtail_page)
            mock_render.assert_not_called()

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            **SETTINGS_BASE,
            "EXTRACT_FROM_TEMPLATES": True,
        }
    )
    def test_extract_from_templates_true_calls_render(self, wagtail_page):
        """With EXTRACT_FROM_TEMPLATES=True, render_page_html is called.

        Purpose: Verify that when EXTRACT_FROM_TEMPLATES is enabled (default),
                 the page rendering path is invoked.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: extract_assets_from_page -> render_page_html
        Test data:
        - EXTRACT_FROM_TEMPLATES=True
        Verification scenario:
        1. Patch render_page_html to return empty HTML
        2. Call build_page_assets
        3. Verify render_page_html was called
        """
        with mock.patch(
            "wagtail_asset_publisher.extractors.render_page_html",
            return_value="",
        ) as mock_render:
            build_page_assets(wagtail_page)
            mock_render.assert_called_once()

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            **SETTINGS_BASE,
            "EXTRACT_FROM_TEMPLATES": False,
        }
    )
    def test_setting_toggle_changes_extraction_behavior(self, wagtail_page):
        """Toggling EXTRACT_FROM_TEMPLATES changes whether assets are created.

        Purpose: Verify that the same page produces different results depending
                 on the EXTRACT_FROM_TEMPLATES setting. With True (and a mock
                 returning CSS), a PublishedAsset is created. With False (no
                 StreamFields), no asset is created.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> extract_assets_from_page -> EXTRACT_FROM_TEMPLATES branching
        Test data:
        - First: EXTRACT_FROM_TEMPLATES=True with mocked template CSS
        - Second: EXTRACT_FROM_TEMPLATES=False with no StreamFields
        Verification scenario:
        1. Build with EXTRACT_FROM_TEMPLATES=True and mocked CSS -> asset created
        2. Build with EXTRACT_FROM_TEMPLATES=False -> asset cleared
        """
        css_asset = _asset(TEMPLATE_CSS)
        with (
            mock.patch(
                "wagtail_asset_publisher.utils.extract_assets_from_page",
                return_value=([css_asset], []),
            ),
            override_settings(
                WAGTAIL_ASSET_PUBLISHER={
                    **SETTINGS_BASE,
                    "EXTRACT_FROM_TEMPLATES": True,
                }
            ),
        ):
            build_page_assets(wagtail_page)

        assert PublishedAsset.objects.filter(
            page=wagtail_page, asset_type="css"
        ).exists()

        build_page_assets(wagtail_page)

        assert not PublishedAsset.objects.filter(
            page=wagtail_page, asset_type="css"
        ).exists()


@pytest.mark.django_db
class TestMiddlewareWithTemplateAssets:
    """Middleware injects CSS/JS references from template-extracted assets."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_middleware_injects_css_link_from_template_extraction(self, wagtail_page):
        """Middleware injects <link> tag for template-extracted CSS.

        Purpose: Verify the full round-trip: template CSS is extracted, built
                 as a PublishedAsset, and then the middleware injects a
                 <link rel="stylesheet"> tag into the HTML response.
        Category: Normal case
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> AssetPublisherMiddleware -> _process_html -> <link> injection
        Test data:
        - One CSS asset from template
        - HTML response with head and body
        Verification scenario:
        1. Build template CSS to create PublishedAsset
        2. Pass request with wagtailpage through middleware
        3. Verify response contains <link rel="stylesheet"> tag
        """
        css_asset = _asset(TEMPLATE_CSS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], []),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)

        request = RequestFactory().get("/test-page/")
        request.wagtailpage = wagtail_page

        response_html = (
            "<html><head><title>Test</title></head><body><p>content</p></body></html>"
        )
        inner_response = HttpResponse(
            response_html, content_type="text/html; charset=utf-8"
        )

        middleware = AssetPublisherMiddleware(lambda req: inner_response)
        result = middleware(request)

        content = result.content.decode("utf-8")
        assert '<link rel="stylesheet" href=' in content
        assert "page-assets/css/" in content

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_middleware_injects_js_script_from_template_extraction(self, wagtail_page):
        """Middleware injects <script> tag for template-extracted JS.

        Purpose: Verify the full round-trip: template JS is extracted, built
                 as a PublishedAsset, and then the middleware injects a
                 <script src="..."> tag into the HTML response.
        Category: Normal case
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> AssetPublisherMiddleware -> _process_html -> <script> injection
        Test data:
        - One JS asset from template
        - HTML response with head and body
        Verification scenario:
        1. Build template JS to create PublishedAsset
        2. Pass request with wagtailpage through middleware
        3. Verify response contains <script src="..."> tag before </body>
        """
        js_asset = _asset(TEMPLATE_JS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], [js_asset]),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)

        request = RequestFactory().get("/test-page/")
        request.wagtailpage = wagtail_page

        response_html = (
            "<html><head><title>Test</title></head><body><p>content</p></body></html>"
        )
        inner_response = HttpResponse(
            response_html, content_type="text/html; charset=utf-8"
        )

        middleware = AssetPublisherMiddleware(lambda req: inner_response)
        result = middleware(request)

        content = result.content.decode("utf-8")
        assert "<script src=" in content
        assert "page-assets/js/" in content

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_middleware_injects_both_css_and_js_from_template(self, wagtail_page):
        """Middleware injects both CSS and JS references from template assets.

        Purpose: Verify that when both CSS and JS template assets exist, the
                 middleware injects both: CSS link in <head> and JS script
                 before </body>.
        Category: Normal case
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> AssetPublisherMiddleware -> _process_html
        Test data:
        - Both CSS and JS assets from templates
        Verification scenario:
        1. Build both CSS and JS assets
        2. Pass request through middleware
        3. Verify both link and script tags are present
        """
        css_asset = _asset(TEMPLATE_CSS)
        js_asset = _asset(TEMPLATE_JS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], [js_asset]),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)

        request = RequestFactory().get("/test-page/")
        request.wagtailpage = wagtail_page

        response_html = (
            "<html><head><title>Test</title></head><body><p>content</p></body></html>"
        )
        inner_response = HttpResponse(
            response_html, content_type="text/html; charset=utf-8"
        )

        middleware = AssetPublisherMiddleware(lambda req: inner_response)
        result = middleware(request)

        content = result.content.decode("utf-8")
        assert '<link rel="stylesheet" href=' in content
        assert "<script src=" in content

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_middleware_strips_inline_and_injects_external(self, wagtail_page):
        """Middleware strips matching inline tags and injects external file references.

        Purpose: Verify that when the HTML response contains inline style/script
                 tags whose content hashes match PublishedAssets, the middleware
                 strips those inline tags and replaces them with external file
                 references.
        Category: Normal case
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _strip_matching_tags -> _process_html
        Test data:
        - HTML with inline style matching published CSS
        - HTML with inline script matching published JS
        Verification scenario:
        1. Build CSS and JS assets
        2. Construct HTML response with matching inline tags
        3. Process through _process_html
        4. Verify inline content is stripped and external references injected
        """
        css_asset = _asset(TEMPLATE_CSS)
        js_asset = _asset(TEMPLATE_JS)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], [js_asset]),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = (
            f"<html><head><style>{TEMPLATE_CSS}</style></head>"
            f"<body><script>{TEMPLATE_JS}</script><p>content</p></body></html>"
        )
        result = _process_html(html, assets)

        assert TEMPLATE_CSS not in result
        assert TEMPLATE_JS not in result
        assert '<link rel="stylesheet" href=' in result
        assert "<script src=" in result


@pytest.mark.django_db
class TestRenderFallback:
    """When render_page_html fails, extraction falls back to StreamField-only."""

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            **SETTINGS_BASE,
            "EXTRACT_FROM_TEMPLATES": True,
        }
    )
    def test_render_failure_falls_back_to_streamfield_extraction(self, wagtail_page):
        """When rendering fails, extraction falls back to StreamField-only mode.

        Purpose: Verify that if render_page_html returns empty string (failure),
                 extract_assets_from_page falls back to StreamField-only
                 extraction. Since the test page has no StreamFields, no
                 PublishedAssets are created.
        Category: Error case
        Technique: Model lifecycle
        Integration targets: extract_assets_from_page -> render_page_html (failure) -> _extract_assets_from_streamfields
        Test data:
        - EXTRACT_FROM_TEMPLATES=True
        - render_page_html mocked to return empty string
        Verification scenario:
        1. Mock render_page_html to return empty string
        2. Call build_page_assets
        3. Verify no PublishedAssets are created (page has no StreamFields)
        """
        with mock.patch(
            "wagtail_asset_publisher.extractors.render_page_html",
            return_value="",
        ):
            build_page_assets(wagtail_page)

        assert not PublishedAsset.objects.filter(page=wagtail_page).exists()


@pytest.mark.django_db
class TestExtractionFromFullHtml:
    """Extract assets from realistic full HTML documents."""

    def test_extract_from_full_html_with_mixed_content(self):
        """Extraction correctly handles a full HTML document with mixed inline assets.

        Purpose: Verify that extract_assets works on a realistic full HTML
                 page containing multiple style and script tags, including
                 templates, StreamFields, data-no-extract, and external refs.
        Category: Normal case
        Technique: API endpoint
        Integration targets: extract_assets -> AssetExtractor -> comprehensive HTML parsing
        Test data:
        - Full HTML document with:
          - One template <style> in <head>
          - One <style data-no-extract> in <head>
          - One <link stylesheet> in <head> (external, ignored)
          - One <script src> in <head> (external, ignored)
          - One inline <script> in <body>
          - One <script data-no-extract> in <body>
        Verification scenario:
        1. Parse the full HTML
        2. Verify exactly 1 style and 1 script are extracted
        3. Verify external refs and data-no-extract tags are excluded
        """
        html = (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<head>\n"
            "  <title>Test Page</title>\n"
            '  <link rel="stylesheet" href="/static/base.css">\n'
            "  <style>.template-header { background: navy; }</style>\n"
            "  <style data-no-extract>.critical { display: block; }</style>\n"
            '  <script src="https://cdn.example.com/analytics.js"></script>\n'
            "</head>\n"
            "<body>\n"
            "  <p>Page content</p>\n"
            "  <script>var app = { init: function() {} };</script>\n"
            "  <script data-no-extract>var preload = true;</script>\n"
            "</body>\n"
            "</html>"
        )
        styles, scripts = extract_assets(html)

        assert len(styles) == 1
        assert styles[0].content == ".template-header { background: navy; }"

        assert len(scripts) == 1
        assert scripts[0].content == "var app = { init: function() {} };"

    def test_extract_empty_style_and_script_tags_ignored(self):
        """Empty <style> and <script> tags produce no extracted assets.

        Purpose: Verify that empty inline tags are not extracted as assets.
        Category: Edge case
        Technique: API endpoint
        Integration targets: extract_assets -> AssetExtractor -> empty content handling
        Test data:
        - HTML with empty <style> and <script> tags
        Verification scenario:
        1. Parse HTML with empty tags
        2. Verify no styles or scripts are extracted
        """
        html = (
            "<html><head><style></style><style>   </style></head>"
            "<body><script></script><script>  </script></body></html>"
        )
        styles, scripts = extract_assets(html)

        assert len(styles) == 0
        assert len(scripts) == 0


@pytest.mark.django_db
class TestIdempotentBuild:
    """Rebuilding with the same template assets does not create duplicates."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_idempotent_rebuild_with_template_assets(self, wagtail_page):
        """Building twice with the same template assets produces the same result.

        Purpose: Verify that running build_page_assets twice with identical
                 template-extracted assets does not create duplicate records
                 and the URL remains stable.
        Category: Idempotency
        Technique: Model lifecycle
        Integration targets: build_page_assets -> update_or_create -> PublishedAsset
        Test data:
        - Same CSS and JS assets from templates
        Verification scenario:
        1. Build with template CSS and JS
        2. Record URLs
        3. Build again with same assets
        4. Verify only one record each and URLs unchanged
        """
        css_asset = _asset(TEMPLATE_CSS)
        js_asset = _asset(TEMPLATE_JS)

        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], [js_asset]),
        ):
            build_page_assets(wagtail_page)

        css_url_1 = PublishedAsset.objects.get(page=wagtail_page, asset_type="css").url
        js_url_1 = PublishedAsset.objects.get(page=wagtail_page, asset_type="js").url

        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], [js_asset]),
        ):
            build_page_assets(wagtail_page)

        assert (
            PublishedAsset.objects.filter(page=wagtail_page, asset_type="css").count()
            == 1
        )
        assert (
            PublishedAsset.objects.filter(page=wagtail_page, asset_type="js").count()
            == 1
        )

        css_url_2 = PublishedAsset.objects.get(page=wagtail_page, asset_type="css").url
        js_url_2 = PublishedAsset.objects.get(page=wagtail_page, asset_type="js").url

        assert css_url_1 == css_url_2
        assert js_url_1 == js_url_2
