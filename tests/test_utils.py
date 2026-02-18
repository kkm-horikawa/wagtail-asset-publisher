"""Tests for wagtail-asset-publisher v2 build orchestration utilities.

Pipeline: Extract -> Build -> Publish -> Record
"""

from __future__ import annotations

from unittest import mock

import pytest

from wagtail_asset_publisher.utils import (
    _clear_asset,
    _extract_path_from_url,
    _process_css,
    _process_js,
    build_page_assets,
    get_builder,
    get_storage,
    import_class,
)


class TestBuildPageAssets:
    @mock.patch("wagtail_asset_publisher.utils._process_js")
    @mock.patch("wagtail_asset_publisher.utils._process_css")
    @mock.patch("wagtail_asset_publisher.utils.get_storage")
    def test_calls_css_and_js_processing(self, mock_get_storage, mock_css, mock_js):
        """build_page_assets calls both _process_css and _process_js.

        Purpose: Verify that build_page_assets orchestrates both CSS and JS
                 processing with the same storage instance.
        Category: Normal case
        Target: build_page_assets(page)
        Technique: Statement coverage (C0)
        Test data: Mock page
        """
        page = mock.Mock(pk=42)
        mock_storage = mock.Mock()
        mock_get_storage.return_value = mock_storage

        build_page_assets(page)

        mock_css.assert_called_once_with(page, mock_storage)
        mock_js.assert_called_once_with(page, mock_storage)


class TestProcessCss:
    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="abcd1234"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_page_html_for_tailwind")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_extracts_builds_saves_and_records(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_get_html,
        mock_hash,
        mock_invalidate,
    ):
        """_process_css extracts styles, builds, saves to storage, creates PublishedAsset.

        Purpose: Verify the full CSS pipeline: extract -> build -> save -> record.
        Category: Normal case
        Target: _process_css(page, storage)
        Technique: Statement coverage (C0)
        Test data: Page with one extracted style block
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/css/42-abcd1234.css"

        style = mock.Mock()
        style.content = "body { color: red; }"
        style.content_hash = "hash1"
        mock_extract.return_value = ([style], [])

        mock_builder = mock.Mock()
        mock_builder.requires_html_content = False
        mock_builder.build.return_value = "body { color: red; }"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "HASH_LENGTH": 8,
            "CSS_PREFIX": "page-assets/css/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch("wagtail_asset_publisher.utils._clear_asset"),
        ):
            _process_css(page, storage)

            mock_pa.objects.update_or_create.assert_called_once()

        mock_builder.build.assert_called_once_with(
            None, ["body { color: red; }"], "css"
        )
        storage.save.assert_called_once_with(
            "page-assets/css/42-abcd1234.css", "body { color: red; }"
        )
        mock_invalidate.assert_called_with(42)

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch("wagtail_asset_publisher.utils._clear_asset")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_clears_when_no_css_content(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_clear,
        mock_invalidate,
    ):
        """When no styles are extracted, existing CSS asset is cleared.

        Purpose: Verify that _process_css clears the existing asset when
                 the builder returns empty content.
        Category: Edge case
        Target: _process_css(page, storage)
        Technique: Decision coverage (C1) - empty build result branch
        Test data: Page with no extracted styles
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        mock_extract.return_value = ([], [])

        mock_builder = mock.Mock()
        mock_builder.requires_html_content = False
        mock_builder.build.return_value = ""
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
        }[key]

        _process_css(page, storage)

        mock_clear.assert_called_once_with(page, "css", storage)
        storage.save.assert_not_called()
        mock_invalidate.assert_called_with(42)

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="tw123456"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_page_html_for_tailwind")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_tailwind_builder_receives_html_content(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_get_html,
        mock_hash,
        mock_invalidate,
    ):
        """When builder.requires_html_content is True, HTML content is passed to build().

        Purpose: Verify that the Tailwind builder receives HTML content
                 from get_page_html_for_tailwind() when requires_html_content is True.
        Category: Normal case
        Target: _process_css(page, storage)
        Technique: Decision coverage (C1) - requires_html_content=True branch
        Test data: Page with Tailwind-style content
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/css/42-tw123456.css"

        style = mock.Mock()
        style.content = ".custom { color: red; }"
        style.content_hash = "hash1"
        mock_extract.return_value = ([style], [])

        mock_builder = mock.Mock()
        mock_builder.requires_html_content = True
        mock_builder.build.return_value = ".bg-red{background:red}"
        mock_get_builder.return_value = mock_builder

        mock_get_html.return_value = "<div class='bg-red-500'>test</div>"

        mock_get_setting.side_effect = lambda key: {
            "CSS_BUILDER": "wagtail_asset_publisher.builders.tailwind.TailwindCSSBuilder",
            "HASH_LENGTH": 8,
            "CSS_PREFIX": "page-assets/css/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_asset"),
        ):
            _process_css(page, storage)

        mock_get_html.assert_called_once_with(page)
        mock_builder.build.assert_called_once_with(
            "<div class='bg-red-500'>test</div>",
            [".custom { color: red; }"],
            "css",
        )


class TestProcessJs:
    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="js123456"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_extracts_builds_saves_and_records_js(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """_process_js extracts scripts, builds, saves to storage, creates PublishedAsset.

        Purpose: Verify the full JS pipeline: extract -> build -> save -> record.
        Category: Normal case
        Target: _process_js(page, storage)
        Technique: Statement coverage (C0)
        Test data: Page with one extracted script block
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-js123456.js"

        script = mock.Mock()
        script.content = "console.log('hello');"
        script.content_hash = "jshash1"
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "console.log('hello');"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch("wagtail_asset_publisher.utils._clear_asset"),
        ):
            _process_js(page, storage)

            mock_pa.objects.update_or_create.assert_called_once()

        mock_builder.build.assert_called_once_with(
            None, ["console.log('hello');"], "js"
        )
        storage.save.assert_called_once_with(
            "page-assets/js/42-js123456.js", "console.log('hello');"
        )
        mock_invalidate.assert_called_with(42)

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch("wagtail_asset_publisher.utils._clear_asset")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_clears_when_no_js_content(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_clear,
        mock_invalidate,
    ):
        """When no scripts are extracted, existing JS asset is cleared.

        Purpose: Verify that _process_js clears the existing asset when
                 the builder returns empty content.
        Category: Edge case
        Target: _process_js(page, storage)
        Technique: Decision coverage (C1) - empty build result branch
        Test data: Page with no extracted scripts
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        mock_extract.return_value = ([], [])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = ""
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
        }[key]

        _process_js(page, storage)

        mock_clear.assert_called_once_with(page, "js", storage)
        storage.save.assert_not_called()
        mock_invalidate.assert_called_with(42)


class TestClearAsset:
    def test_deletes_from_storage_and_db(self):
        """_clear_asset removes the file from storage and deletes the DB record.

        Purpose: Verify that _clear_asset deletes both the storage file
                 and the PublishedAsset database record.
        Category: Normal case
        Target: _clear_asset(page, asset_type, storage)
        Technique: Statement coverage (C0)
        Test data: Existing CSS asset
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.exists.return_value = True

        mock_asset = mock.Mock()
        mock_asset.url = "/media/page-assets/css/42-abcd1234.css"

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch(
                "wagtail_asset_publisher.utils._extract_path_from_url",
                return_value="page-assets/css/42-abcd1234.css",
            ),
        ):
            mock_pa.objects.get.return_value = mock_asset
            _clear_asset(page, "css", storage)

        storage.delete.assert_called_once_with("page-assets/css/42-abcd1234.css")
        mock_asset.delete.assert_called_once()

    def test_nonexistent_asset_is_noop(self):
        """When no existing asset is found, _clear_asset is a no-op.

        Purpose: Verify that _clear_asset gracefully handles the case
                 where no PublishedAsset record exists (DoesNotExist).
        Category: Edge case
        Target: _clear_asset(page, asset_type, storage)
        Technique: Error guessing
        Test data: Page with no published CSS asset
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        with mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa:
            mock_pa.DoesNotExist = type("DoesNotExist", (Exception,), {})
            mock_pa.objects.get.side_effect = mock_pa.DoesNotExist

            _clear_asset(page, "css", storage)

        storage.delete.assert_not_called()

    def test_skips_storage_delete_when_path_empty(self):
        """When _extract_path_from_url returns empty, storage.delete is not called.

        Purpose: Verify that _clear_asset skips storage deletion when
                 the URL cannot be parsed to a valid storage path.
        Category: Edge case
        Target: _clear_asset(page, asset_type, storage)
        Technique: Decision coverage (C1) - empty path branch
        Test data: Asset with unparsable URL
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        mock_asset = mock.Mock()
        mock_asset.url = "https://unknown.example.com/no-match.css"

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch(
                "wagtail_asset_publisher.utils._extract_path_from_url",
                return_value="",
            ),
        ):
            mock_pa.objects.get.return_value = mock_asset
            _clear_asset(page, "css", storage)

        storage.delete.assert_not_called()
        mock_asset.delete.assert_called_once()

    def test_skips_storage_delete_when_file_not_exists(self):
        """When storage reports file does not exist, storage.delete is not called.

        Purpose: Verify that _clear_asset checks storage.exists() before
                 calling storage.delete().
        Category: Edge case
        Target: _clear_asset(page, asset_type, storage)
        Technique: Decision coverage (C1) - file not exists branch
        Test data: Asset with valid path but file missing from storage
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.exists.return_value = False

        mock_asset = mock.Mock()
        mock_asset.url = "/media/page-assets/css/42-abcd1234.css"

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch(
                "wagtail_asset_publisher.utils._extract_path_from_url",
                return_value="page-assets/css/42-abcd1234.css",
            ),
        ):
            mock_pa.objects.get.return_value = mock_asset
            _clear_asset(page, "css", storage)

        storage.delete.assert_not_called()
        mock_asset.delete.assert_called_once()


class TestExtractPathFromUrl:
    @mock.patch(
        "wagtail_asset_publisher.utils.get_setting",
        side_effect=lambda key: {
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
        }[key],
    )
    def test_relative_url(self, _mock_setting):
        """Relative URL with prefix extracts the storage path.

        Purpose: Verify that _extract_path_from_url correctly extracts
                 the storage path from a relative URL starting with '/media/'.
        Category: Normal case
        Target: _extract_path_from_url(url)
        Technique: Equivalence partitioning
        Test data: /media/page-assets/css/42-abc.css
        """
        result = _extract_path_from_url("/media/page-assets/css/42-abc.css")

        assert result == "page-assets/css/42-abc.css"

    @mock.patch(
        "wagtail_asset_publisher.utils.get_setting",
        side_effect=lambda key: {
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
        }[key],
    )
    def test_absolute_url_with_prefix(self, _mock_setting):
        """Full URL with prefix extracts the storage path.

        Purpose: Verify that _extract_path_from_url correctly extracts
                 the storage path from a full CDN URL.
        Category: Normal case
        Target: _extract_path_from_url(url)
        Technique: Equivalence partitioning
        Test data: https://cdn.example.com/media/page-assets/css/42-abc.css
        """
        result = _extract_path_from_url(
            "https://cdn.example.com/media/page-assets/css/42-abc.css"
        )

        assert result == "page-assets/css/42-abc.css"

    @mock.patch(
        "wagtail_asset_publisher.utils.get_setting",
        side_effect=lambda key: {
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
        }[key],
    )
    def test_js_url_extracts_path(self, _mock_setting):
        """JS URL extracts the storage path using JS_PREFIX.

        Purpose: Verify that _extract_path_from_url works for JS paths.
        Category: Normal case
        Target: _extract_path_from_url(url)
        Technique: Equivalence partitioning
        Test data: /media/page-assets/js/42-efgh.js
        """
        result = _extract_path_from_url("/media/page-assets/js/42-efgh.js")

        assert result == "page-assets/js/42-efgh.js"

    @mock.patch(
        "wagtail_asset_publisher.utils.get_setting",
        side_effect=lambda key: {
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
        }[key],
    )
    def test_no_match_returns_empty(self, _mock_setting):
        """URL without known prefix returns empty string.

        Purpose: Verify that _extract_path_from_url returns empty string
                 when the URL does not contain any known prefix.
        Category: Edge case
        Target: _extract_path_from_url(url)
        Technique: Error guessing
        Test data: URL with no matching prefix
        """
        result = _extract_path_from_url("https://example.com/unknown/path.txt")

        assert result == ""

    @mock.patch(
        "wagtail_asset_publisher.utils.get_setting",
        side_effect=lambda key: {
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
        }[key],
    )
    def test_empty_url_returns_empty(self, _mock_setting):
        """Empty URL returns empty string.

        Purpose: Verify that _extract_path_from_url handles empty input.
        Category: Edge case
        Target: _extract_path_from_url(url)
        Technique: Boundary value analysis
        Test data: Empty string
        """
        result = _extract_path_from_url("")

        assert result == ""

    @mock.patch(
        "wagtail_asset_publisher.utils.get_setting",
        side_effect=lambda key: {
            "CSS_PREFIX": "page-assets/css/",
            "JS_PREFIX": "page-assets/js/",
        }[key],
    )
    def test_path_only_url_starting_with_prefix(self, _mock_setting):
        """Path that directly starts with a prefix is returned as-is.

        Purpose: Verify that _extract_path_from_url returns the path
                 when it directly starts with a known prefix.
        Category: Normal case
        Target: _extract_path_from_url(url)
        Technique: Equivalence partitioning
        Test data: page-assets/css/42-abc.css (no leading /)
        """
        result = _extract_path_from_url("page-assets/css/42-abc.css")

        assert result == "page-assets/css/42-abc.css"


class TestImportClass:
    def test_imports_existing_class(self):
        """import_class imports a class from a valid dotted path.

        Purpose: Verify that import_class resolves a dotted path to
                 the correct class.
        Category: Normal case
        Target: import_class(dotted_path)
        Technique: Equivalence partitioning
        Test data: RawAssetBuilder dotted path
        """
        from wagtail_asset_publisher.builders.raw import RawAssetBuilder

        result = import_class("wagtail_asset_publisher.builders.raw.RawAssetBuilder")

        assert result is RawAssetBuilder

    def test_raises_module_not_found_for_invalid_module(self):
        """import_class raises ModuleNotFoundError for nonexistent module.

        Purpose: Verify error handling for invalid module paths.
        Category: Error case
        Target: import_class(dotted_path)
        Technique: Error guessing
        Test data: Nonexistent module path
        """
        with pytest.raises(ModuleNotFoundError):
            import_class("nonexistent.module.ClassName")

    def test_raises_attribute_error_for_invalid_class(self):
        """import_class raises AttributeError for nonexistent class name.

        Purpose: Verify error handling for invalid class names.
        Category: Error case
        Target: import_class(dotted_path)
        Technique: Error guessing
        Test data: Valid module with nonexistent class
        """
        with pytest.raises(AttributeError):
            import_class("wagtail_asset_publisher.builders.raw.NonExistentClass")


class TestGetBuilder:
    def test_returns_builder_instance(self):
        """get_builder returns an instance of the specified builder class.

        Purpose: Verify that get_builder imports and instantiates a builder.
        Category: Normal case
        Target: get_builder(builder_path)
        Technique: Equivalence partitioning
        Test data: RawAssetBuilder dotted path
        """
        from wagtail_asset_publisher.builders.raw import RawAssetBuilder

        result = get_builder("wagtail_asset_publisher.builders.raw.RawAssetBuilder")

        assert isinstance(result, RawAssetBuilder)


class TestGetStorage:
    def test_returns_storage_instance(self):
        """get_storage returns an instance of the configured storage backend.

        Purpose: Verify that get_storage imports and instantiates the storage.
        Category: Normal case
        Target: get_storage()
        Technique: Equivalence partitioning
        Test data: Default STORAGE_BACKEND setting
        """
        from wagtail_asset_publisher.storage.django_storage import DjangoStorageBackend

        with mock.patch(
            "wagtail_asset_publisher.utils.get_setting",
            return_value="wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
        ):
            result = get_storage()

        assert isinstance(result, DjangoStorageBackend)


class TestCacheInvalidation:
    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="abc12345"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_cache_invalidated_after_publish(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """invalidate_cache is called after successfully saving a CSS asset.

        Purpose: Verify that the middleware cache is invalidated after
                 publishing a new asset so the next request picks up the new URL.
        Category: Normal case
        Target: _process_css(page, storage) -> invalidate_cache
        Technique: Equivalence partitioning
        Test data: Page with CSS content
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/css/42-abc12345.css"

        style = mock.Mock()
        style.content = "body{}"
        style.content_hash = "h1"
        mock_extract.return_value = ([style], [])

        mock_builder = mock.Mock()
        mock_builder.requires_html_content = False
        mock_builder.build.return_value = "body{}"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "HASH_LENGTH": 8,
            "CSS_PREFIX": "page-assets/css/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_asset"),
        ):
            _process_css(page, storage)

        mock_invalidate.assert_called_with(42)

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch("wagtail_asset_publisher.utils._clear_asset")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_cache_invalidated_after_clear(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_clear,
        mock_invalidate,
    ):
        """invalidate_cache is called after clearing a CSS asset.

        Purpose: Verify that the middleware cache is invalidated after
                 clearing an asset (when builder returns empty).
        Category: Normal case
        Target: _process_css(page, storage) -> invalidate_cache
        Technique: Equivalence partitioning
        Test data: Page with no CSS content (builder returns empty)
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        mock_extract.return_value = ([], [])

        mock_builder = mock.Mock()
        mock_builder.requires_html_content = False
        mock_builder.build.return_value = ""
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
        }[key]

        _process_css(page, storage)

        mock_invalidate.assert_called_with(42)
