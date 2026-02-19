"""Integration tests for script loading attribute preservation.

Verifies the end-to-end flow of extracting scripts with different loading
strategies (defer, async, type="module"), building them into separate files
grouped by strategy, and injecting the correct HTML attributes via middleware.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.test import RequestFactory, override_settings
from wagtail.models import Page

from wagtail_asset_publisher.extractors import ExtractedAsset, compute_content_hash
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
}

JS_BLOCKING = "var x = 1;"
JS_DEFER = "document.addEventListener('DOMContentLoaded', function() {});"
JS_ASYNC = "fetch('/api/data');"
JS_MODULE = "import { foo } from './foo.js';"
JS_MODULE_ASYNC = "const data = await fetch('/api');"


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
        instance=Page(title="Script Loading Test", slug="script-load")
    )


@pytest.mark.django_db
class TestFullPipelineMixedStrategies:
    """Extract + Build + DB record creation for mixed loading strategies."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_mixed_strategies_create_separate_records(self, wagtail_page):
        """Mixed script loading strategies create separate PublishedAsset records per group.

        Purpose: Verify that building a page with 5 loading strategies (blocking,
            defer, async, module, module-async) creates separate PublishedAsset
            records with the correct loading field value for each.
        Category: Normal case
        Target: build_page_assets -> _process_js -> PublishedAsset
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _process_js -> RawAssetBuilder -> DjangoStorageBackend -> PublishedAsset
        Test data: Five scripts, one per loading strategy
        Verification scenario:
            1. Inject 5 scripts with different loading strategies as extraction results
            2. Execute build_page_assets
            3. Confirm 5 JS PublishedAsset records are created
            4. Confirm each record has the correct loading field value
        """
        scripts = [
            _asset(JS_BLOCKING, ""),
            _asset(JS_DEFER, "defer"),
            _asset(JS_ASYNC, "async"),
            _asset(JS_MODULE, "module"),
            _asset(JS_MODULE_ASYNC, "module-async"),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        js_assets = PublishedAsset.objects.filter(
            page=wagtail_page, asset_type="js"
        ).order_by("loading")
        assert js_assets.count() == 5

        loading_values = set(js_assets.values_list("loading", flat=True))
        assert loading_values == {"", "defer", "async", "module", "module-async"}

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_each_strategy_has_correct_content_hashes(self, wagtail_page):
        """Each PublishedAsset stores the content hash of scripts in its loading group.

        Purpose: Verify that each PublishedAsset record's content_hashes field
            contains only the hashes of scripts belonging to that loading group.
        Category: Normal case
        Target: build_page_assets -> grouping -> PublishedAsset.content_hashes
        Technique: Model lifecycle
        Integration targets: build_page_assets -> grouping -> PublishedAsset.content_hashes
        Test data: Two scripts: blocking and defer
        Verification scenario:
            1. Inject blocking and defer scripts and build
            2. Confirm blocking record contains only the blocking script hash
            3. Confirm defer record contains only the defer script hash
        """
        scripts = [
            _asset(JS_BLOCKING, ""),
            _asset(JS_DEFER, "defer"),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        blocking_asset = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="js", loading=""
        )
        defer_asset = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="js", loading="defer"
        )

        assert compute_content_hash(JS_BLOCKING) in blocking_asset.content_hashes
        assert compute_content_hash(JS_DEFER) not in blocking_asset.content_hashes
        assert compute_content_hash(JS_DEFER) in defer_asset.content_hashes
        assert compute_content_hash(JS_BLOCKING) not in defer_asset.content_hashes

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_loading_suffix_in_filename(self, wagtail_page):
        """Non-empty loading strategy is included as filename suffix.

        Purpose: Verify that non-empty loading strategies such as "defer"
            are reflected as a suffix in the asset URL filename.
        Category: Normal case
        Target: build_page_assets -> filename generation -> PublishedAsset.url
        Technique: Model lifecycle
        Integration targets: build_page_assets -> filename generation -> DjangoStorageBackend -> PublishedAsset.url
        Test data: Two scripts: blocking (no loading) and defer
        Verification scenario:
            1. Inject blocking and defer scripts and build
            2. Confirm blocking record URL does not contain "-defer"
            3. Confirm defer record URL contains the "-defer" suffix
        """
        scripts = [
            _asset(JS_BLOCKING, ""),
            _asset(JS_DEFER, "defer"),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        blocking_asset = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="js", loading=""
        )
        defer_asset = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="js", loading="defer"
        )

        assert "-defer" not in blocking_asset.url
        assert "-defer" in defer_asset.url
        assert defer_asset.url.endswith(".js")

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_multiple_scripts_same_strategy_merged(self, wagtail_page):
        """Multiple scripts with the same loading strategy are merged into one record.

        Purpose: Verify that multiple scripts sharing the same loading strategy
            are merged into a single PublishedAsset record, with content_hashes
            containing hashes of all scripts in the group.
        Category: Normal case
        Target: build_page_assets -> grouping -> PublishedAsset
        Technique: Model lifecycle
        Integration targets: build_page_assets -> grouping -> RawAssetBuilder.build -> PublishedAsset
        Test data: Two scripts with the same loading strategy (defer)
        Verification scenario:
            1. Inject two defer strategy scripts and build
            2. Confirm only one JS PublishedAsset record is created
            3. Confirm content_hashes contains hashes for both scripts
        """
        defer_a = "console.log('a');"
        defer_b = "console.log('b');"
        scripts = [
            _asset(defer_a, "defer"),
            _asset(defer_b, "defer"),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        js_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="js")
        assert js_assets.count() == 1

        asset = js_assets.first()
        assert asset.loading == "defer"
        assert compute_content_hash(defer_a) in asset.content_hashes
        assert compute_content_hash(defer_b) in asset.content_hashes


@pytest.mark.django_db
class TestMiddlewareScriptInjection:
    """Middleware strips inline scripts and injects <script> tags with correct attributes."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_defer_script_injected_with_defer_attribute(self, wagtail_page):
        """Middleware injects <script defer> for defer-loaded assets.

        Purpose: Verify that after a defer script is saved as a PublishedAsset,
            the middleware injects a <script defer> tag into the response HTML.
        Category: Normal case
        Target: build_page_assets -> _process_html
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _get_published_assets -> _process_html
        Test data: One script with defer loading strategy
        Verification scenario:
            1. Build a defer script to create a PublishedAsset
            2. Run _process_html to transform the HTML
            3. Confirm the output HTML contains a <script src="..." defer> tag
        """
        scripts = [_asset(JS_DEFER, "defer")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = "<html><head></head><body><p>hello</p></body></html>"
        result = _process_html(html, assets)

        assert " defer>" in result
        assert "</body>" in result

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_async_script_injected_with_async_attribute(self, wagtail_page):
        """Middleware injects <script async> for async-loaded assets.

        Purpose: Verify that after an async script is saved as a PublishedAsset,
            the middleware injects a <script async> tag into the response HTML.
        Category: Normal case
        Target: build_page_assets -> _process_html
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _get_published_assets -> _process_html
        Test data: One script with async loading strategy
        Verification scenario:
            1. Build an async script to create a PublishedAsset
            2. Run _process_html to transform the HTML
            3. Confirm the output HTML contains a <script src="..." async> tag
        """
        scripts = [_asset(JS_ASYNC, "async")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = "<html><head></head><body><p>hello</p></body></html>"
        result = _process_html(html, assets)

        assert " async>" in result
        assert "</body>" in result

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_module_script_injected_with_type_module(self, wagtail_page):
        """Middleware injects <script type="module"> for module-loaded assets.

        Purpose: Verify that after a module script is saved as a PublishedAsset,
            the middleware injects a <script type="module"> tag into the response HTML.
        Category: Normal case
        Target: build_page_assets -> _process_html
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _get_published_assets -> _process_html
        Test data: One script with module loading strategy
        Verification scenario:
            1. Build a module script to create a PublishedAsset
            2. Run _process_html to transform the HTML
            3. Confirm the output HTML contains a <script src="..." type="module"> tag
        """
        scripts = [_asset(JS_MODULE, "module")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = "<html><head></head><body><p>hello</p></body></html>"
        result = _process_html(html, assets)

        assert 'type="module"' in result
        assert " async>" not in result

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_module_async_script_injected_with_type_module_async(self, wagtail_page):
        """Middleware injects <script type="module" async> for module-async assets.

        Purpose: Verify that after a module-async script is saved as a PublishedAsset,
            the middleware injects a <script type="module" async> tag into the response HTML.
        Category: Normal case
        Target: build_page_assets -> _process_html
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _get_published_assets -> _process_html
        Test data: One script with module-async loading strategy
        Verification scenario:
            1. Build a module-async script to create a PublishedAsset
            2. Run _process_html to transform the HTML
            3. Confirm the output HTML contains both type="module" and async attributes
        """
        scripts = [_asset(JS_MODULE_ASYNC, "module-async")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = "<html><head></head><body><p>hello</p></body></html>"
        result = _process_html(html, assets)

        assert 'type="module" async>' in result

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_blocking_script_injected_without_extra_attributes(self, wagtail_page):
        """Middleware injects plain <script> without extra attributes for blocking assets.

        Purpose: Verify that after a blocking (loading="") script is saved as a
            PublishedAsset, the middleware injects a plain <script> tag without
            defer, async, or type attributes.
        Category: Normal case
        Target: build_page_assets -> _process_html
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _get_published_assets -> _process_html
        Test data: One script with empty loading strategy (blocking)
        Verification scenario:
            1. Build a blocking script to create a PublishedAsset
            2. Run _process_html to transform the HTML
            3. Confirm the output script tag has no defer/async/type attributes
        """
        scripts = [_asset(JS_BLOCKING, "")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = "<html><head></head><body><p>hello</p></body></html>"
        result = _process_html(html, assets)

        js_asset = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="js", loading=""
        )
        expected_tag = f'<script src="{js_asset.url}"></script>'
        assert expected_tag in result

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_mixed_strategies_injection_order(self, wagtail_page):
        """Script tags are injected in the defined order: blocking, defer, module, async, module-async.

        Purpose: Verify that when multiple loading strategies are present,
            the middleware injects script tags in the defined order:
            blocking -> defer -> module -> async -> module-async.
        Category: Normal case
        Target: build_page_assets -> _process_html -> _JS_LOADING_ORDER
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _process_html -> _JS_LOADING_ORDER
        Test data: Five scripts: blocking, defer, async, module, module-async
        Verification scenario:
            1. Build 5 loading strategy scripts to create PublishedAssets
            2. Run _process_html to transform the HTML
            3. Confirm the script tag order in the output follows the defined order
        """
        scripts = [
            _asset(JS_BLOCKING, ""),
            _asset(JS_DEFER, "defer"),
            _asset(JS_ASYNC, "async"),
            _asset(JS_MODULE, "module"),
            _asset(JS_MODULE_ASYNC, "module-async"),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = "<html><head></head><body><p>hello</p></body></html>"
        result = _process_html(html, assets)

        blocking_pos = result.find("></script>")
        defer_pos = result.find(" defer>")
        module_pos = result.find('type="module">')
        async_pos = result.find(" async>")
        module_async_pos = result.find('type="module" async>')

        assert blocking_pos < defer_pos < module_pos < async_pos < module_async_pos

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_inline_scripts_stripped_and_external_preserved(self, wagtail_page):
        """Matching inline scripts are stripped; static file references injected before </body>.

        Purpose: Verify that the middleware strips inline scripts whose content
            hash matches a PublishedAsset and injects external file references
            before </body>.
        Category: Normal case
        Target: build_page_assets -> _strip_matching_tags -> _process_html
        Technique: Middleware behavior
        Integration targets: build_page_assets -> _strip_matching_tags -> _process_html
        Test data: Page with inline HTML containing the defer script content
        Verification scenario:
            1. Build a defer script
            2. Run _process_html on HTML containing the inline script
            3. Confirm the inline script content is stripped
            4. Confirm an external file reference script tag is injected
        """
        scripts = [_asset(JS_DEFER, "defer")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = (
            "<html><head></head><body>"
            f"<script defer>{JS_DEFER}</script>"
            "<p>content</p>"
            "</body></html>"
        )
        result = _process_html(html, assets)

        assert JS_DEFER not in result
        assert "<script src=" in result
        assert " defer>" in result


@pytest.mark.django_db
class TestRepublishUpdate:
    """Republishing clears old JS assets and creates new ones correctly."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_republish_clears_old_js_assets_and_creates_new(self, wagtail_page):
        """Republishing with different scripts replaces all JS PublishedAsset records.

        Purpose: Verify that when page content changes and is rebuilt, all old
            JS PublishedAsset records are deleted and only records for the new
            scripts remain.
        Category: Normal case
        Target: build_page_assets -> _clear_js_assets -> _process_js -> PublishedAsset
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _clear_js_assets -> _process_js -> PublishedAsset
        Test data:
            - First build: blocking + defer (2 scripts)
            - Rebuild: async only (1 script)
        Verification scenario:
            1. Build with blocking + defer scripts -> 2 records created
            2. Rebuild with async script only -> old 2 records deleted, only async record remains
            3. Confirm only the loading="async" record exists
        """
        scripts_v1 = [
            _asset(JS_BLOCKING, ""),
            _asset(JS_DEFER, "defer"),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts_v1),
        ):
            build_page_assets(wagtail_page)

        assert (
            PublishedAsset.objects.filter(page=wagtail_page, asset_type="js").count()
            == 2
        )

        scripts_v2 = [_asset(JS_ASYNC, "async")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts_v2),
        ):
            build_page_assets(wagtail_page)

        js_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="js")
        assert js_assets.count() == 1
        assert js_assets.first().loading == "async"

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_republish_with_no_js_clears_all_js_records(self, wagtail_page):
        """Republishing with no scripts removes all JS PublishedAsset records.

        Purpose: Verify that when a page is rebuilt without any scripts,
            all existing JS PublishedAsset records are deleted.
        Category: Normal case
        Target: build_page_assets -> _clear_js_assets -> PublishedAsset.delete
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _clear_js_assets -> PublishedAsset.delete
        Test data:
            - First build: defer + module (2 scripts)
            - Rebuild: no scripts
        Verification scenario:
            1. Build with defer + module scripts -> 2 records created
            2. Rebuild with no scripts -> all records deleted
        """
        scripts = [
            _asset(JS_DEFER, "defer"),
            _asset(JS_MODULE, "module"),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        assert (
            PublishedAsset.objects.filter(page=wagtail_page, asset_type="js").count()
            == 2
        )

        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], []),
        ):
            build_page_assets(wagtail_page)

        assert (
            PublishedAsset.objects.filter(page=wagtail_page, asset_type="js").count()
            == 0
        )

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_republish_preserves_css_when_only_js_changes(self, wagtail_page):
        """CSS asset is preserved when only JS content changes on republish.

        Purpose: Verify that when only JS content changes on rebuild, the CSS
            PublishedAsset is not affected and remains intact.
        Category: Normal case
        Target: build_page_assets -> _process_css + _process_js -> PublishedAsset
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _process_css + _process_js -> PublishedAsset
        Test data: Build with CSS + defer JS, then rebuild with CSS + async JS
        Verification scenario:
            1. Build with CSS + defer JS
            2. Rebuild with CSS + async JS
            3. Confirm CSS PublishedAsset is preserved
            4. Confirm JS PublishedAsset has changed to async only
        """
        css_asset = ExtractedAsset(
            content="body { color: red; }",
            content_hash=compute_content_hash("body { color: red; }"),
        )

        scripts_v1 = [_asset(JS_DEFER, "defer")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], scripts_v1),
        ):
            build_page_assets(wagtail_page)

        css_url_v1 = PublishedAsset.objects.get(page=wagtail_page, asset_type="css").url

        scripts_v2 = [_asset(JS_ASYNC, "async")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], scripts_v2),
        ):
            build_page_assets(wagtail_page)

        css_url_v2 = PublishedAsset.objects.get(page=wagtail_page, asset_type="css").url
        assert css_url_v1 == css_url_v2

        js_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="js")
        assert js_assets.count() == 1
        assert js_assets.first().loading == "async"


@pytest.mark.django_db
class TestNonJsTypeExclusion:
    """Non-JS script types (importmap, speculationrules) are not extracted."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_importmap_not_extracted_stays_inline(self, wagtail_page):
        """Scripts with type="importmap" are skipped by extraction and stay inline.

        Purpose: Verify that script tags with type="importmap" are excluded from
            extraction and no PublishedAsset record is created for them.
        Category: Normal case
        Target: extract_assets -> build_page_assets
        Technique: API endpoint
        Integration targets: extract_assets -> _resolve_loading_strategy -> build_page_assets
        Test data: Page with only one type="importmap" script
        Verification scenario:
            1. Run extraction on HTML containing only an importmap script
            2. Confirm the extraction result is empty (extractor skips it)
            3. Confirm build_page_assets does not create any JS PublishedAsset
        """
        from wagtail_asset_publisher.extractors import extract_assets

        importmap_html = (
            '<script type="importmap">{"imports": {"foo": "./foo.js"}}</script>'
        )
        _, scripts = extract_assets(importmap_html)
        assert len(scripts) == 0

        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], []),
        ):
            build_page_assets(wagtail_page)

        assert not PublishedAsset.objects.filter(
            page=wagtail_page, asset_type="js"
        ).exists()

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_speculationrules_not_extracted(self, wagtail_page):
        """Scripts with type="speculationrules" are skipped by extraction.

        Purpose: Verify that script tags with type="speculationrules" are
            excluded from extraction.
        Category: Normal case
        Target: extract_assets -> _resolve_loading_strategy
        Technique: API endpoint
        Integration targets: extract_assets -> _resolve_loading_strategy
        Test data: One script with type="speculationrules"
        Verification scenario:
            1. Run extraction on HTML containing a speculationrules script
            2. Confirm the extraction result is empty
        """
        from wagtail_asset_publisher.extractors import extract_assets

        speculation_html = (
            '<script type="speculationrules">'
            '{"prefetch": [{"source": "list", "urls": ["/page2"]}]}'
            "</script>"
        )
        _, scripts = extract_assets(speculation_html)
        assert len(scripts) == 0

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_importmap_alongside_normal_js_only_normal_extracted(self, wagtail_page):
        """When importmap and normal JS coexist, only normal JS is extracted.

        Purpose: Verify that when importmap and normal JS scripts coexist on a
            page, only the normal JS is extracted and built, while the importmap
            stays inline.
        Category: Normal case
        Target: extract_assets -> build_page_assets -> PublishedAsset
        Technique: Model lifecycle
        Integration targets: extract_assets -> build_page_assets -> PublishedAsset
        Test data: One type="importmap" script and one normal defer script
        Verification scenario:
            1. Run extraction on HTML with importmap + defer script
            2. Confirm only the defer script is extracted
            3. Confirm build_page_assets creates only a defer JS PublishedAsset
        """
        from wagtail_asset_publisher.extractors import extract_assets

        html = (
            '<script type="importmap">{"imports": {}}</script>'
            f"<script defer>{JS_DEFER}</script>"
        )
        _, scripts = extract_assets(html)
        assert len(scripts) == 1
        assert scripts[0].loading == "defer"

        extracted_scripts = [_asset(JS_DEFER, "defer")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], extracted_scripts),
        ):
            build_page_assets(wagtail_page)

        js_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="js")
        assert js_assets.count() == 1
        assert js_assets.first().loading == "defer"


@pytest.mark.django_db
class TestBackwardCompatibility:
    """Pages with only plain <script> tags (no defer/async) work as before."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_plain_scripts_create_single_blocking_record(self, wagtail_page):
        """Plain scripts without defer/async create a single PublishedAsset with loading="".

        Purpose: Verify that building a page with only plain script tags (no
            defer/async) creates exactly one PublishedAsset record with loading=""
            (blocking), maintaining backward compatibility.
        Category: Normal case (backward compatibility)
        Target: build_page_assets -> _process_js -> PublishedAsset
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _process_js -> PublishedAsset
        Test data: Two plain scripts without loading attributes
        Verification scenario:
            1. Inject two plain scripts and build
            2. Confirm exactly one JS PublishedAsset is created
            3. Confirm the loading field is empty string
        """
        plain_a = "var a = 1;"
        plain_b = "var b = 2;"
        scripts = [
            _asset(plain_a, ""),
            _asset(plain_b, ""),
        ]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        js_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="js")
        assert js_assets.count() == 1
        assert js_assets.first().loading == ""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_plain_script_middleware_injects_plain_tag(self, wagtail_page):
        """Middleware injects <script src="..."></script> without extra attributes for plain scripts.

        Purpose: Verify that for plain blocking scripts, the middleware injects
            a simple script tag without defer/async/type attributes, maintaining
            backward compatibility.
        Category: Normal case (backward compatibility)
        Target: build_page_assets -> PublishedAsset -> _process_html
        Technique: Middleware behavior
        Integration targets: build_page_assets -> PublishedAsset -> _process_html
        Test data: One plain script without loading attributes
        Verification scenario:
            1. Build a plain script to create a PublishedAsset
            2. Run _process_html to transform the HTML
            3. Confirm the script tag has no defer/async/type attributes
        """
        scripts = [_asset(JS_BLOCKING, "")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)
        assets = _get_published_assets(wagtail_page.pk)

        html = "<html><head></head><body><p>hello</p></body></html>"
        result = _process_html(html, assets)

        assert "<script src=" in result
        assert " defer>" not in result
        assert " async>" not in result
        assert 'type="module"' not in result

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_idempotent_rebuild_plain_scripts(self, wagtail_page):
        """Rebuilding with the same plain scripts does not create duplicate records.

        Purpose: Verify that building twice with the same plain scripts does not
            create duplicate PublishedAsset records, ensuring idempotency.
        Category: Idempotency
        Target: build_page_assets -> update_or_create -> PublishedAsset
        Technique: Model lifecycle
        Integration targets: build_page_assets -> update_or_create -> PublishedAsset
        Test data: One plain script built twice
        Verification scenario:
            1. Execute first build with a plain script
            2. Execute second build with the same plain script
            3. Confirm only one JS PublishedAsset record exists
        """
        scripts = [_asset(JS_BLOCKING, "")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)
            build_page_assets(wagtail_page)

        js_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="js")
        assert js_assets.count() == 1


@pytest.mark.django_db
class TestMiddlewareRoundTrip:
    """Full middleware round-trip: request → response with injected scripts."""

    @override_settings(WAGTAIL_ASSET_PUBLISHER=SETTINGS_BASE)
    def test_middleware_full_roundtrip_with_defer(self, wagtail_page):
        """Full middleware round-trip injects defer script tag into HTML response.

        Purpose: Verify that a full round-trip through AssetPublisherMiddleware
            correctly injects a defer script tag into the HTML response when
            the request has a wagtailpage attribute set.
        Category: Normal case
        Target: AssetPublisherMiddleware.__call__ -> _get_page -> _get_published_assets -> _process_html
        Technique: Middleware behavior
        Integration targets: AssetPublisherMiddleware.__call__ -> _get_page -> _get_published_assets -> _process_html
        Test data:
            - One script with defer loading strategy
            - HTML response with wagtailpage attribute set
        Verification scenario:
            1. Build a defer script to create a PublishedAsset
            2. Pass the request with wagtailpage attribute through the middleware
            3. Confirm the response HTML contains a script tag with the defer attribute
        """
        scripts = [_asset(JS_DEFER, "defer")]
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], scripts),
        ):
            build_page_assets(wagtail_page)

        invalidate_cache(wagtail_page.pk)

        from django.http import HttpResponse

        request = RequestFactory().get("/test-page/")
        request.wagtailpage = wagtail_page

        response_html = (
            "<html><head><title>Test</title></head><body><p>content</p></body></html>"
        )
        inner_response = HttpResponse(
            response_html, content_type="text/html; charset=utf-8"
        )

        def get_response(req):
            return inner_response

        middleware = AssetPublisherMiddleware(get_response)
        result = middleware(request)

        content = result.content.decode("utf-8")
        assert "<script src=" in content
        assert " defer>" in content
