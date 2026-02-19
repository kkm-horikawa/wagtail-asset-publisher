"""Integration tests for build_page_assets with MINIFY_CSS / OBFUSCATE_JS settings.

Runs build_page_assets against a real Wagtail Page, a real database, and
DjangoStorageBackend, verifying PublishedAsset record creation, URL generation,
and settings application.

Note: Because the test Wagtail page model has no StreamField, only
extract_assets_from_page is replaced with a minimal mock to inject asset
extraction results. Everything else — build -> minify/optimize -> hash ->
storage save -> DB record — uses real components.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest
from django.test import override_settings
from wagtail.models import Page

from wagtail_asset_publisher.extractors import ExtractedAsset, compute_content_hash
from wagtail_asset_publisher.models import PublishedAsset
from wagtail_asset_publisher.utils import build_page_assets


def _make_extracted_asset(content: str) -> ExtractedAsset:
    return ExtractedAsset(content=content, content_hash=compute_content_hash(content))


CSS_CONTENT = "body { color: red; }\n  .hero { margin: 0; }\n"
JS_CONTENT = "var x = 1;\nfunction hello() { return x; }\n"


@pytest.fixture
def wagtail_page(db):
    root = Page.objects.first()
    return root.add_child(instance=Page(title="Test Page", slug="test-opt"))


@pytest.fixture
def _patch_extract_css():
    """Patch extract_assets_from_page to return CSS only."""
    asset = _make_extracted_asset(CSS_CONTENT)
    with mock.patch(
        "wagtail_asset_publisher.utils.extract_assets_from_page",
        return_value=([asset], []),
    ):
        yield


@pytest.fixture
def _patch_extract_js():
    """Patch extract_assets_from_page to return JS only."""
    asset = _make_extracted_asset(JS_CONTENT)
    with mock.patch(
        "wagtail_asset_publisher.utils.extract_assets_from_page",
        return_value=([], [asset]),
    ):
        yield


@pytest.fixture
def _patch_extract_both():
    """Patch extract_assets_from_page to return both CSS and JS."""
    css_asset = _make_extracted_asset(CSS_CONTENT)
    js_asset = _make_extracted_asset(JS_CONTENT)
    with mock.patch(
        "wagtail_asset_publisher.utils.extract_assets_from_page",
        return_value=([css_asset], [js_asset]),
    ):
        yield


@pytest.mark.django_db
class TestCssMinificationIntegration:
    """Integration tests for the full CSS build flow controlled by MINIFY_CSS."""

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_css")
    def test_css_stored_without_minification(self, wagtail_page):
        """CSS is stored unminified when MINIFY_CSS=False.

        Purpose: Verify that build_page_assets stores CSS without minification
                 when MINIFY_CSS is disabled, and that PublishedAsset is created
                 correctly.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> RawAssetBuilder -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - MINIFY_CSS=False
        - Page with inline CSS
        Verification:
        1. Call build_page_assets with MINIFY_CSS=False
        2. Verify CSS PublishedAsset is created
        3. Verify URL hash matches unminified content hash
        """
        build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        expected_hash = compute_content_hash(CSS_CONTENT, 8)
        assert expected_hash in asset.url
        assert asset.url.endswith(".css")

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": True,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_css")
    def test_minify_css_changes_hash_when_rcssmin_available(self, wagtail_page):
        """Hash differs from unminified when MINIFY_CSS=True and rcssmin is available.

        Purpose: Verify that build_page_assets minifies CSS when MINIFY_CSS=True
                 and rcssmin is available, producing a URL with a different hash
                 than the unminified version.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> RawAssetBuilder -> _minify_css -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - MINIFY_CSS=True
        - CSS content with whitespace (so minification has an effect)
        Verification:
        1. Call build_page_assets with MINIFY_CSS=True
        2. Verify CSS PublishedAsset is created
        3. If rcssmin is installed: verify hash differs from unminified hash
        4. If rcssmin is not installed: verify fallback produces the same hash
        """
        build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        unminified_hash = compute_content_hash(CSS_CONTENT, 8)

        try:
            import rcssmin  # noqa: F401

            rcssmin_available = True
        except ImportError:
            rcssmin_available = False

        if rcssmin_available:
            assert unminified_hash not in asset.url
        else:
            assert unminified_hash in asset.url

        assert asset.url.endswith(".css")

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": True,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_css")
    def test_minify_css_graceful_fallback_without_rcssmin(self, wagtail_page):
        """Asset is created without error when MINIFY_CSS=True but rcssmin is unavailable.

        Purpose: Verify that when rcssmin is not installed and MINIFY_CSS=True,
                 _minify_css falls back to the original content without raising an
                 error, and PublishedAsset is created successfully.
        Category: Error case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _minify_css (ImportError fallback) -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - MINIFY_CSS=True
        - rcssmin import mocked to raise ImportError
        Verification:
        1. Mock rcssmin import to fail
        2. Call build_page_assets
        3. Verify PublishedAsset is created without error
        4. Verify URL contains the unminified content hash
        """
        import builtins

        original_import = builtins.__import__
        saved_module = sys.modules.pop("rcssmin", None)

        def _block_rcssmin(name, *args, **kwargs):
            if name == "rcssmin":
                raise ImportError("rcssmin not installed")
            return original_import(name, *args, **kwargs)

        try:
            with mock.patch("builtins.__import__", side_effect=_block_rcssmin):
                build_page_assets(wagtail_page)
        finally:
            if saved_module is not None:
                sys.modules["rcssmin"] = saved_module

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        unminified_hash = compute_content_hash(CSS_CONTENT, 8)
        assert unminified_hash in asset.url


@pytest.mark.django_db
class TestJsOptimizationIntegration:
    """Integration tests for the full JS build flow controlled by OBFUSCATE_JS."""

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_js")
    def test_js_stored_without_optimization(self, wagtail_page):
        """JS is stored without optimization when OBFUSCATE_JS=False.

        Purpose: Verify that build_page_assets stores JS without optimization
                 when OBFUSCATE_JS is disabled, and that PublishedAsset is created
                 correctly.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> RawAssetBuilder -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - OBFUSCATE_JS=False
        - Page with inline JS
        Verification:
        1. Call build_page_assets with OBFUSCATE_JS=False
        2. Verify JS PublishedAsset is created
        3. Verify URL hash matches unoptimized content hash
        """
        build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="js")
        expected_hash = compute_content_hash(JS_CONTENT, 8)
        assert expected_hash in asset.url
        assert asset.url.endswith(".js")

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": True,
            "TERSER_PATH": None,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_js")
    def test_obfuscate_js_graceful_fallback_without_tools(self, wagtail_page):
        """Asset is created without error when neither terser nor rjsmin is available.

        Purpose: Verify that when OBFUSCATE_JS=True but neither terser nor rjsmin
                 is available, _optimize_js falls back to the original content
                 without raising an error, and PublishedAsset is created successfully.
        Category: Error case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _optimize_js (full fallback) -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - OBFUSCATE_JS=True
        - No terser, rjsmin import mocked to raise ImportError
        Verification:
        1. Mock _find_terser to return None
        2. Mock rjsmin import to fail
        3. Call build_page_assets
        4. Verify PublishedAsset is created without error
        5. Verify URL contains the unoptimized content hash
        """
        import builtins

        original_import = builtins.__import__
        saved_module = sys.modules.pop("rjsmin", None)

        def _block_rjsmin(name, *args, **kwargs):
            if name == "rjsmin":
                raise ImportError("rjsmin not installed")
            return original_import(name, *args, **kwargs)

        try:
            with (
                mock.patch(
                    "wagtail_asset_publisher.utils._find_terser", return_value=None
                ),
                mock.patch("builtins.__import__", side_effect=_block_rjsmin),
            ):
                build_page_assets(wagtail_page)
        finally:
            if saved_module is not None:
                sys.modules["rjsmin"] = saved_module

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="js")
        unoptimized_hash = compute_content_hash(JS_CONTENT, 8)
        assert unoptimized_hash in asset.url

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": True,
            "TERSER_PATH": None,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_js")
    def test_obfuscate_js_changes_hash_when_rjsmin_available(self, wagtail_page):
        """Hash differs from unoptimized when OBFUSCATE_JS=True and rjsmin is available.

        Purpose: Verify that build_page_assets optimizes JS when OBFUSCATE_JS=True
                 and rjsmin is available, producing a URL with a different hash
                 than the unoptimized version.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _optimize_js (rjsmin fallback) -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - OBFUSCATE_JS=True
        - No terser (falls back to rjsmin)
        - JS content with whitespace and comments
        Verification:
        1. Mock _find_terser to return None
        2. Call build_page_assets
        3. If rjsmin is installed: verify hash differs from unoptimized hash
        4. If rjsmin is not installed: verify fallback produces the same hash
        """
        with mock.patch(
            "wagtail_asset_publisher.utils._find_terser", return_value=None
        ):
            build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="js")
        unoptimized_hash = compute_content_hash(JS_CONTENT, 8)

        try:
            import rjsmin  # noqa: F401

            rjsmin_available = True
        except ImportError:
            rjsmin_available = False

        if rjsmin_available:
            assert unoptimized_hash not in asset.url
        else:
            assert unoptimized_hash in asset.url

        assert asset.url.endswith(".js")


@pytest.mark.django_db
class TestSettingsToggleUrlChange:
    """Verify that toggling MINIFY_CSS / OBFUSCATE_JS changes the asset URL."""

    def test_minify_css_toggle_changes_asset_url(self, wagtail_page):
        """Toggling MINIFY_CSS changes the PublishedAsset URL.

        Purpose: Verify that running build_page_assets with MINIFY_CSS=False then
                 MINIFY_CSS=True on the same page produces different URLs (or the
                 same URL when falling back without rcssmin).
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _minify_css -> compute_content_hash -> PublishedAsset
        Test data:
        - Same CSS content
        - Run with MINIFY_CSS=False first, then MINIFY_CSS=True
        Verification:
        1. Run build_page_assets with MINIFY_CSS=False and record the URL
        2. Run build_page_assets with MINIFY_CSS=True and record the URL
        3. If rcssmin is available: verify URLs differ
        4. If rcssmin is unavailable: verify URLs are the same (fallback)
        """
        css_asset = _make_extracted_asset(CSS_CONTENT)

        with (
            mock.patch(
                "wagtail_asset_publisher.utils.extract_assets_from_page",
                return_value=([css_asset], []),
            ),
            override_settings(
                WAGTAIL_ASSET_PUBLISHER={
                    "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
                    "CSS_PREFIX": "page-assets/css/",
                    "JS_PREFIX": "page-assets/js/",
                    "HASH_LENGTH": 8,
                    "MINIFY_CSS": False,
                    "OBFUSCATE_JS": False,
                }
            ),
        ):
            build_page_assets(wagtail_page)

        url_without_minify = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="css"
        ).url

        with (
            mock.patch(
                "wagtail_asset_publisher.utils.extract_assets_from_page",
                return_value=([css_asset], []),
            ),
            override_settings(
                WAGTAIL_ASSET_PUBLISHER={
                    "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
                    "CSS_PREFIX": "page-assets/css/",
                    "JS_PREFIX": "page-assets/js/",
                    "HASH_LENGTH": 8,
                    "MINIFY_CSS": True,
                    "OBFUSCATE_JS": False,
                }
            ),
        ):
            build_page_assets(wagtail_page)

        url_with_minify = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="css"
        ).url

        try:
            import rcssmin  # noqa: F401

            rcssmin_available = True
        except ImportError:
            rcssmin_available = False

        if rcssmin_available:
            assert url_without_minify != url_with_minify
        else:
            assert url_without_minify == url_with_minify

    def test_obfuscate_js_toggle_changes_asset_url(self, wagtail_page):
        """Toggling OBFUSCATE_JS changes the PublishedAsset URL.

        Purpose: Verify that running build_page_assets with OBFUSCATE_JS=False then
                 OBFUSCATE_JS=True on the same page produces different URLs (or the
                 same URL when falling back without rjsmin).
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _optimize_js -> compute_content_hash -> PublishedAsset
        Test data:
        - Same JS content
        - Run with OBFUSCATE_JS=False first, then OBFUSCATE_JS=True
        Verification:
        1. Run build_page_assets with OBFUSCATE_JS=False and record the URL
        2. Run build_page_assets with OBFUSCATE_JS=True and record the URL
        3. If rjsmin is available: verify URLs differ
        4. If rjsmin is unavailable: verify URLs are the same (fallback)
        """
        js_asset = _make_extracted_asset(JS_CONTENT)

        with (
            mock.patch(
                "wagtail_asset_publisher.utils.extract_assets_from_page",
                return_value=([], [js_asset]),
            ),
            override_settings(
                WAGTAIL_ASSET_PUBLISHER={
                    "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
                    "CSS_PREFIX": "page-assets/css/",
                    "JS_PREFIX": "page-assets/js/",
                    "HASH_LENGTH": 8,
                    "MINIFY_CSS": False,
                    "OBFUSCATE_JS": False,
                    "TERSER_PATH": None,
                }
            ),
        ):
            build_page_assets(wagtail_page)

        url_without_obfuscate = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="js"
        ).url

        with (
            mock.patch(
                "wagtail_asset_publisher.utils.extract_assets_from_page",
                return_value=([], [js_asset]),
            ),
            mock.patch("wagtail_asset_publisher.utils._find_terser", return_value=None),
            override_settings(
                WAGTAIL_ASSET_PUBLISHER={
                    "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
                    "CSS_PREFIX": "page-assets/css/",
                    "JS_PREFIX": "page-assets/js/",
                    "HASH_LENGTH": 8,
                    "MINIFY_CSS": False,
                    "OBFUSCATE_JS": True,
                    "TERSER_PATH": None,
                }
            ),
        ):
            build_page_assets(wagtail_page)

        url_with_obfuscate = PublishedAsset.objects.get(
            page=wagtail_page, asset_type="js"
        ).url

        try:
            import rjsmin  # noqa: F401

            rjsmin_available = True
        except ImportError:
            rjsmin_available = False

        if rjsmin_available:
            assert url_without_obfuscate != url_with_obfuscate
        else:
            assert url_without_obfuscate == url_with_obfuscate


@pytest.mark.django_db
class TestBuildPageAssetsLifecycle:
    """Integration tests for the PublishedAsset lifecycle managed by build_page_assets."""

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_both")
    def test_creates_both_css_and_js_assets(self, wagtail_page):
        """Both CSS and JS PublishedAssets are created for a page with both asset types.

        Purpose: Verify that build_page_assets correctly processes both CSS and JS
                 assets and creates the corresponding PublishedAsset records in the DB.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _process_css + _process_js -> DjangoStorageBackend -> PublishedAsset
        Test data:
        - Page with both CSS and JS
        - MINIFY_CSS=False, OBFUSCATE_JS=False
        Verification:
        1. Call build_page_assets with a page containing both CSS and JS
        2. Verify CSS PublishedAsset is created
        3. Verify JS PublishedAsset is created
        4. Verify URLs end with .css and .js respectively
        """
        build_page_assets(wagtail_page)

        assets = PublishedAsset.objects.filter(page=wagtail_page)
        assert assets.count() == 2

        css_asset = assets.get(asset_type="css")
        js_asset = assets.get(asset_type="js")
        assert css_asset.url.endswith(".css")
        assert js_asset.url.endswith(".js")

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_css")
    def test_rebuild_updates_existing_asset(self, wagtail_page):
        """Calling build_page_assets twice updates the existing PublishedAsset rather than duplicating it.

        Purpose: Verify that running build_page_assets twice does not create
                 duplicate PublishedAsset records, and that update_or_create
                 correctly updates the existing record.
        Category: Idempotency
        Technique: Model lifecycle
        Integration targets: build_page_assets -> update_or_create -> PublishedAsset
        Test data:
        - Same CSS content
        - build_page_assets called twice in succession
        Verification:
        1. Call build_page_assets a first time
        2. Call build_page_assets a second time
        3. Verify only one PublishedAsset record exists
        """
        build_page_assets(wagtail_page)
        build_page_assets(wagtail_page)

        css_assets = PublishedAsset.objects.filter(page=wagtail_page, asset_type="css")
        assert css_assets.count() == 1

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": False,
        }
    )
    def test_no_assets_clears_existing_record(self, wagtail_page):
        """Existing PublishedAsset is deleted when the page no longer has assets.

        Purpose: Verify that after building a page with assets, if the page
                 subsequently has no assets, the existing PublishedAsset records
                 are correctly deleted.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> _clear_asset -> PublishedAsset.delete
        Test data:
        - Page with CSS initially, then no assets
        Verification:
        1. Run build_page_assets with a CSS-containing page
        2. Run build_page_assets again with no assets
        3. Verify the PublishedAsset record is deleted
        """
        css_asset = _make_extracted_asset(CSS_CONTENT)
        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([css_asset], []),
        ):
            build_page_assets(wagtail_page)

        assert PublishedAsset.objects.filter(
            page=wagtail_page, asset_type="css"
        ).exists()

        with mock.patch(
            "wagtail_asset_publisher.utils.extract_assets_from_page",
            return_value=([], []),
        ):
            build_page_assets(wagtail_page)

        assert not PublishedAsset.objects.filter(
            page=wagtail_page, asset_type="css"
        ).exists()

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_css")
    def test_content_hashes_stored_in_published_asset(self, wagtail_page):
        """PublishedAsset.content_hashes contains the hash of the extracted source asset.

        Purpose: Verify that after build_page_assets runs, the content_hashes
                 field of PublishedAsset correctly stores the content hash of
                 each extracted asset.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> extract -> PublishedAsset.content_hashes
        Test data:
        - One CSS asset
        Verification:
        1. Call build_page_assets
        2. Verify PublishedAsset.content_hashes is not empty
        3. Verify it contains the hash of the original CSS content
        """
        build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        expected_hash = compute_content_hash(CSS_CONTENT)
        assert expected_hash in asset.content_hashes

    @override_settings(
        WAGTAIL_ASSET_PUBLISHER={
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
            "HASH_LENGTH": 8,
            "MINIFY_CSS": False,
            "OBFUSCATE_JS": False,
        }
    )
    @pytest.mark.usefixtures("_patch_extract_css")
    def test_url_contains_page_id_and_prefix(self, wagtail_page):
        """PublishedAsset URL contains the page ID and the configured CSS_PREFIX.

        Purpose: Verify that the generated URL includes the page ID and is stored
                 under the path defined by CSS_PREFIX.
        Category: Normal case
        Technique: Model lifecycle
        Integration targets: build_page_assets -> DjangoStorageBackend.save -> URL generation
        Test data:
        - CSS_PREFIX=page-assets/css/
        - Page ID assigned automatically by the DB
        Verification:
        1. Call build_page_assets
        2. Verify URL contains "page-assets/css/"
        3. Verify URL contains the page ID
        """
        build_page_assets(wagtail_page)

        asset = PublishedAsset.objects.get(page=wagtail_page, asset_type="css")
        assert "page-assets/css/" in asset.url
        assert str(wagtail_page.pk) in asset.url
