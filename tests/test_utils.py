"""Tests for wagtail-asset-publisher v2 build orchestration utilities.

Pipeline: Extract -> Build -> Publish -> Record
"""

from __future__ import annotations

from unittest import mock

import pytest

from wagtail_asset_publisher.utils import (
    _clear_asset,
    _clear_js_assets,
    _extract_path_from_url,
    _find_terser,
    _minify_css,
    _optimize_js,
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
            "MINIFY_CSS": False,
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
            "MINIFY_CSS": False,
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
        Test data: Page with one extracted script block (blocking loading)
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-js123456.js"

        script = mock.Mock()
        script.content = "console.log('hello');"
        script.content_hash = "jshash1"
        script.loading = ""
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "console.log('hello');"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
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
    @mock.patch("wagtail_asset_publisher.utils._clear_js_assets")
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
        """When no scripts are extracted, all existing JS assets are cleared.

        Purpose: Verify that _process_js clears all existing JS assets when
                 no scripts are extracted from the page.
        Category: Edge case
        Target: _process_js(page, storage)
        Technique: Decision coverage (C1) - empty extraction branch
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

        mock_clear.assert_called_once_with(page, storage)
        storage.save.assert_not_called()
        mock_invalidate.assert_called_with(42)


class TestProcessJsLoadingGroups:
    """Tests for JS grouping by loading strategy in _process_js."""

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="grp12345"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_scripts_grouped_by_loading_strategy(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """異なるloading strategyのスクリプトが別ファイルに保存されることを検証する。

        【目的】_process_jsがloading strategy別にスクリプトをグループ化し、
               各グループを別ファイルとしてstorage.saveすることをもって、
               スクリプト読み込み戦略のファイル分離要件を保証する
        【種別】正常系テスト
        【対象】_process_js(page, storage)
        【技法】デシジョンテーブル（loading値ごとのグループ化）
        【テストデータ】blocking, defer, moduleの3つのスクリプト
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-grp12345.js"

        blocking_script = mock.Mock()
        blocking_script.content = "blocking();"
        blocking_script.content_hash = "hash_blocking"
        blocking_script.loading = ""

        defer_script = mock.Mock()
        defer_script.content = "deferred();"
        defer_script.content_hash = "hash_defer"
        defer_script.loading = "defer"

        module_script = mock.Mock()
        module_script.content = "import x from 'y';"
        module_script.content_hash = "hash_module"
        module_script.loading = "module"

        mock_extract.return_value = (
            [],
            [blocking_script, defer_script, module_script],
        )

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "built_js_content"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

            assert mock_pa.objects.update_or_create.call_count == 3

        assert storage.save.call_count == 3
        assert mock_builder.build.call_count == 3

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="fn123456"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_filename_includes_loading_suffix_for_non_blocking(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """non-blockingスクリプトのファイル名にloading suffixが付与されることを検証する。

        【目的】loading値が空でないスクリプトのファイル名に"-{loading}"サフィックスが
               付与されることをもって、ファイル名によるloading strategy識別要件を保証する
        【種別】正常系テスト
        【対象】_process_js(page, storage) のファイル名生成
        【技法】境界値分析（空文字 vs 非空文字のloading値）
        【テストデータ】loading="defer"のスクリプト
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-fn123456-defer.js"

        script = mock.Mock()
        script.content = "deferred();"
        script.content_hash = "hash1"
        script.loading = "defer"
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "deferred();"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

        storage.save.assert_called_once_with(
            "page-assets/js/42-fn123456-defer.js", "deferred();"
        )

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="fn123456"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_filename_no_suffix_for_blocking(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """blockingスクリプトのファイル名にloading suffixが付与されないことを検証する。

        【目的】loading=""（blocking）のスクリプトのファイル名にサフィックスが
               付与されないことをもって、後方互換性を保証する
        【種別】正常系テスト
        【対象】_process_js(page, storage) のファイル名生成
        【技法】境界値分析（空文字のloading値）
        【テストデータ】loading=""のスクリプト
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-fn123456.js"

        script = mock.Mock()
        script.content = "blocking();"
        script.content_hash = "hash1"
        script.loading = ""
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "blocking();"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

        storage.save.assert_called_once_with(
            "page-assets/js/42-fn123456.js", "blocking();"
        )

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="mod12345"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_update_or_create_receives_loading_value(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """PublishedAsset.objects.update_or_createにloading値が渡されることを検証する。

        【目的】_process_jsがPublishedAssetの作成/更新時にloading値を
               正しく渡すことをもって、DB上のloading strategy記録要件を保証する
        【種別】正常系テスト
        【対象】_process_js(page, storage) -> PublishedAsset.objects.update_or_create
        【技法】同値分割（loading値の伝搬）
        【テストデータ】loading="module"のスクリプト
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-mod12345-module.js"

        script = mock.Mock()
        script.content = "import x from 'y';"
        script.content_hash = "hash_module"
        script.loading = "module"
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "import x from 'y';"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

            mock_pa.objects.update_or_create.assert_called_once_with(
                page=page,
                asset_type="js",
                loading="module",
                defaults={
                    "url": "/media/page-assets/js/42-mod12345-module.js",
                    "content_hashes": ["hash_module"],
                },
            )

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="grp12345"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_same_loading_scripts_grouped_together(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """同じloading strategyのスクリプトが1つのファイルにまとめられることを検証する。

        【目的】同じloading値を持つ複数のスクリプトが1つのビルド呼び出しに
               まとめられることをもって、loading strategy別の結合要件を保証する
        【種別】正常系テスト
        【対象】_process_js(page, storage) のグループ化
        【技法】同値分割（同一loading値の複数スクリプト）
        【テストデータ】loading="defer"のスクリプト2つ
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-grp12345-defer.js"

        script1 = mock.Mock()
        script1.content = "deferred1();"
        script1.content_hash = "hash1"
        script1.loading = "defer"

        script2 = mock.Mock()
        script2.content = "deferred2();"
        script2.content_hash = "hash2"
        script2.loading = "defer"

        mock_extract.return_value = ([], [script1, script2])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "deferred1();deferred2();"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

            mock_pa.objects.update_or_create.assert_called_once()

        mock_builder.build.assert_called_once_with(
            None, ["deferred1();", "deferred2();"], "js"
        )
        storage.save.assert_called_once()

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="skip1234"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_empty_build_result_skipped_for_group(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_hash,
        mock_invalidate,
    ):
        """ビルド結果が空のグループはスキップされることを検証する。

        【目的】builderが空文字列を返したloading groupがstorage.saveを
               呼ばずスキップされることをもって、空ファイル生成防止要件を保証する
        【種別】エッジケーステスト
        【対象】_process_js(page, storage)
        【技法】判定条件網羅（C1）- builder空結果分岐
        【テストデータ】builderが空文字列を返すスクリプト
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        script = mock.Mock()
        script.content = "empty_result();"
        script.content_hash = "hash1"
        script.loading = "defer"
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = ""
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

            mock_pa.objects.update_or_create.assert_not_called()

        storage.save.assert_not_called()


class TestClearJsAssets:
    """Tests for _clear_js_assets: remove all JS published assets for a page."""

    def test_deletes_all_js_assets_from_storage_and_db(self):
        """_clear_js_assetsがページの全JSアセットをストレージとDBから削除することを検証する。

        【目的】_clear_js_assetsが指定ページの全JSアセットについて、
               ストレージファイル削除とDBレコード削除を行うことを保証する
        【種別】正常系テスト
        【対象】_clear_js_assets(page, storage)
        【技法】命令網羅（C0）
        【テストデータ】3つのloading strategyの既存JSアセット
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.exists.return_value = True

        asset_blocking = mock.Mock()
        asset_blocking.url = "/media/page-assets/js/42-abc.js"
        asset_blocking.loading = ""

        asset_defer = mock.Mock()
        asset_defer.url = "/media/page-assets/js/42-abc-defer.js"
        asset_defer.loading = "defer"

        asset_module = mock.Mock()
        asset_module.url = "/media/page-assets/js/42-abc-module.js"
        asset_module.loading = "module"

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch(
                "wagtail_asset_publisher.utils._extract_path_from_url",
                side_effect=lambda url: url.removeprefix("/media/"),
            ),
        ):
            mock_pa.objects.filter.return_value = [
                asset_blocking,
                asset_defer,
                asset_module,
            ]
            _clear_js_assets(page, storage)

        assert storage.delete.call_count == 3
        assert asset_blocking.delete.call_count == 1
        assert asset_defer.delete.call_count == 1
        assert asset_module.delete.call_count == 1

    def test_no_existing_js_assets_is_noop(self):
        """既存JSアセットがない場合、_clear_js_assetsがno-opであることを検証する。

        【目的】JSアセットが存在しないページに対して_clear_js_assetsを呼んでも
               エラーにならないことを保証する
        【種別】エッジケーステスト
        【対象】_clear_js_assets(page, storage)
        【技法】境界値分析（空の結果セット）
        【テストデータ】JSアセットなしのページ
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        with mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa:
            mock_pa.objects.filter.return_value = []
            _clear_js_assets(page, storage)

        storage.delete.assert_not_called()

    def test_skips_storage_delete_when_path_empty(self):
        """URLからパスが抽出できない場合、storage.deleteをスキップすることを検証する。

        【目的】_extract_path_from_urlが空文字を返した場合でもDBレコードは
               削除され、storage.deleteはスキップされることを保証する
        【種別】エッジケーステスト
        【対象】_clear_js_assets(page, storage)
        【技法】判定条件網羅（C1）- 空パス分岐
        【テストデータ】パース不可能なURLを持つアセット
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()

        asset = mock.Mock()
        asset.url = "https://unknown.example.com/no-match.js"

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch(
                "wagtail_asset_publisher.utils._extract_path_from_url",
                return_value="",
            ),
        ):
            mock_pa.objects.filter.return_value = [asset]
            _clear_js_assets(page, storage)

        storage.delete.assert_not_called()
        asset.delete.assert_called_once()

    def test_skips_storage_delete_when_file_not_exists(self):
        """ストレージにファイルが存在しない場合、storage.deleteをスキップすることを検証する。

        【目的】storage.exists()がFalseを返した場合にstorage.deleteが
               呼ばれないことを保証する
        【種別】エッジケーステスト
        【対象】_clear_js_assets(page, storage)
        【技法】判定条件網羅（C1）- ファイル不在分岐
        【テストデータ】ストレージにファイルが存在しないアセット
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.exists.return_value = False

        asset = mock.Mock()
        asset.url = "/media/page-assets/js/42-abc.js"

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset") as mock_pa,
            mock.patch(
                "wagtail_asset_publisher.utils._extract_path_from_url",
                return_value="page-assets/js/42-abc.js",
            ),
        ):
            mock_pa.objects.filter.return_value = [asset]
            _clear_js_assets(page, storage)

        storage.delete.assert_not_called()
        asset.delete.assert_called_once()


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
            "MINIFY_CSS": False,
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


class TestOptimizeJs:
    """Tests for _optimize_js() terser/rjsmin fallback logic."""

    @mock.patch(
        "wagtail_asset_publisher.utils._find_terser", return_value="/usr/bin/terser"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=["-c", "-m"])
    @mock.patch("wagtail_asset_publisher.utils.subprocess.run")
    def test_terser_success_returns_stdout(self, mock_run, _mock_setting, _mock_find):
        """_optimize_js returns subprocess.run stdout when terser succeeds.

        Purpose: Verify that _optimize_js returns the stdout of subprocess.run
                 when terser is available and exits successfully.
        Category: Normal case
        Target: _optimize_js(content)
        Technique: Statement coverage (C0)
        Test data: Simple JS code string
        """
        mock_run.return_value = mock.Mock(stdout="var a=1;")
        js_input = "var  a  =  1;"

        result = _optimize_js(js_input)

        assert result == "var a=1;"
        mock_run.assert_called_once_with(
            ["/usr/bin/terser", "-c", "-m"],
            input=js_input,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

    @mock.patch(
        "wagtail_asset_publisher.utils._find_terser", return_value="/usr/bin/terser"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=["-c", "-m"])
    @mock.patch("wagtail_asset_publisher.utils.subprocess.run")
    def test_terser_success_no_warning_logged(
        self, mock_run, _mock_setting, _mock_find
    ):
        """_optimize_js does not log a warning when terser succeeds.

        Purpose: Verify that _optimize_js does not emit any warning log
                 when terser exits successfully.
        Category: Normal case
        Target: _optimize_js(content)
        Technique: Error guessing
        Test data: Simple JS code string
        """
        mock_run.return_value = mock.Mock(stdout="var a=1;")

        with mock.patch("wagtail_asset_publisher.utils.logger") as mock_logger:
            _optimize_js("var  a  =  1;")

        mock_logger.warning.assert_not_called()

    @mock.patch(
        "wagtail_asset_publisher.utils._find_terser", return_value="/usr/bin/terser"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=["-c", "-m"])
    @mock.patch("wagtail_asset_publisher.utils.subprocess.run")
    def test_terser_called_process_error_falls_back_to_rjsmin(
        self, mock_run, _mock_setting, _mock_find
    ):
        """_optimize_js falls back to rjsmin when terser raises CalledProcessError.

        Purpose: Verify that _optimize_js falls back to rjsmin and returns the
                 minified result when terser raises CalledProcessError.
        Category: Error case
        Target: _optimize_js(content)
        Technique: Decision coverage (C1) - CalledProcessError branch
        Test data: subprocess.CalledProcessError simulating terser failure
        """
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(1, "terser")
        js_input = "var  a  =  1;"
        mock_rjsmin = mock.Mock()
        mock_rjsmin.jsmin.return_value = "var a=1;"

        with mock.patch.dict("sys.modules", {"rjsmin": mock_rjsmin}):
            result = _optimize_js(js_input)

        assert result == "var a=1;"

    @mock.patch(
        "wagtail_asset_publisher.utils._find_terser", return_value="/usr/bin/terser"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=["-c", "-m"])
    @mock.patch("wagtail_asset_publisher.utils.subprocess.run")
    def test_terser_timeout_expired_falls_back_to_rjsmin(
        self, mock_run, _mock_setting, _mock_find
    ):
        """_optimize_js falls back to rjsmin when terser raises TimeoutExpired.

        Purpose: Verify that _optimize_js falls back to rjsmin and returns the
                 minified result when terser raises TimeoutExpired.
        Category: Error case
        Target: _optimize_js(content)
        Technique: Decision coverage (C1) - TimeoutExpired branch
        Test data: subprocess.TimeoutExpired simulating terser timeout
        """
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("terser", 30)
        js_input = "var  a  =  1;"
        mock_rjsmin = mock.Mock()
        mock_rjsmin.jsmin.return_value = "var a=1;"

        with mock.patch.dict("sys.modules", {"rjsmin": mock_rjsmin}):
            result = _optimize_js(js_input)

        assert result == "var a=1;"

    @mock.patch(
        "wagtail_asset_publisher.utils._find_terser", return_value="/usr/bin/terser"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=["-c", "-m"])
    @mock.patch("wagtail_asset_publisher.utils.subprocess.run")
    def test_terser_oserror_falls_back_to_rjsmin(
        self, mock_run, _mock_setting, _mock_find
    ):
        """_optimize_js falls back to rjsmin when terser raises OSError.

        Purpose: Verify that _optimize_js falls back to rjsmin and returns the
                 minified result when terser raises OSError.
        Category: Error case
        Target: _optimize_js(content)
        Technique: Decision coverage (C1) - OSError branch
        Test data: OSError simulating terser binary not executable
        """
        mock_run.side_effect = OSError("Permission denied")
        js_input = "var  a  =  1;"
        mock_rjsmin = mock.Mock()
        mock_rjsmin.jsmin.return_value = "var a=1;"

        with mock.patch.dict("sys.modules", {"rjsmin": mock_rjsmin}):
            result = _optimize_js(js_input)

        assert result == "var a=1;"

    @mock.patch("wagtail_asset_publisher.utils._find_terser", return_value=None)
    def test_no_terser_with_rjsmin_returns_rjsmin_result(self, _mock_find):
        """_optimize_js returns rjsmin result when terser is not found.

        Purpose: Verify that _optimize_js falls back to rjsmin and returns the
                 minified result when terser is not found.
        Category: Normal case
        Target: _optimize_js(content)
        Technique: Decision coverage (C1) - terser not found branch
        Test data: None returned from _find_terser simulating terser not found
        """
        js_input = "var  a  =  1;"
        mock_rjsmin = mock.Mock()
        mock_rjsmin.jsmin.return_value = "var a=1;"

        with mock.patch.dict("sys.modules", {"rjsmin": mock_rjsmin}):
            result = _optimize_js(js_input)

        assert result == "var a=1;"

    @mock.patch("wagtail_asset_publisher.utils._find_terser", return_value=None)
    def test_no_terser_no_rjsmin_returns_original(self, _mock_find):
        """_optimize_js returns the original content when neither terser nor rjsmin is available.

        Purpose: Verify that _optimize_js returns the original content string
                 unchanged when both terser and rjsmin are unavailable.
        Category: Edge case
        Target: _optimize_js(content)
        Technique: Decision coverage (C1) - both unavailable branch
        Test data: Neither external tool installed
        """
        js_input = "var  a  =  1;"

        with mock.patch.dict("sys.modules", {"rjsmin": None}):
            result = _optimize_js(js_input)

        assert result == js_input

    @mock.patch(
        "wagtail_asset_publisher.utils._find_terser", return_value="/usr/bin/terser"
    )
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=["-c", "-m"])
    @mock.patch("wagtail_asset_publisher.utils.subprocess.run")
    def test_terser_failure_logs_warning(self, mock_run, _mock_setting, _mock_find):
        """_optimize_js logs a warning when terser fails.

        Purpose: Verify that _optimize_js emits a logger.warning to notify
                 the fallback when terser raises an exception.
        Category: Normal case
        Target: _optimize_js(content)
        Technique: Error guessing
        Test data: terser CalledProcessError
        """
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(1, "terser")
        mock_rjsmin = mock.Mock()
        mock_rjsmin.jsmin.return_value = "var a=1;"

        with (
            mock.patch.dict("sys.modules", {"rjsmin": mock_rjsmin}),
            mock.patch("wagtail_asset_publisher.utils.logger") as mock_logger,
        ):
            _optimize_js("var a = 1;")

        mock_logger.warning.assert_called_once()
        assert "terser failed" in mock_logger.warning.call_args[0][0]

    @mock.patch("wagtail_asset_publisher.utils._find_terser", return_value=None)
    def test_no_terser_no_rjsmin_logs_warning(self, _mock_find):
        """_optimize_js logs a warning when neither terser nor rjsmin is available.

        Purpose: Verify that _optimize_js emits a logger.warning to notify
                 that optimization is skipped when both tools are unavailable.
        Category: Edge case
        Target: _optimize_js(content)
        Technique: Error guessing
        Test data: Neither external tool installed
        """
        with (
            mock.patch.dict("sys.modules", {"rjsmin": None}),
            mock.patch("wagtail_asset_publisher.utils.logger") as mock_logger,
        ):
            _optimize_js("var a = 1;")

        mock_logger.warning.assert_called_once()
        assert "Neither terser nor rjsmin" in mock_logger.warning.call_args[0][0]


class TestMinifyCss:
    """Tests for _minify_css() rcssmin fallback logic."""

    def test_rcssmin_available_returns_minified(self):
        """_minify_css returns the minified result when rcssmin is available.

        Purpose: Verify that _minify_css returns the result of rcssmin.cssmin()
                 when rcssmin is available.
        Category: Normal case
        Target: _minify_css(content)
        Technique: Statement coverage (C0)
        Test data: Simple CSS string
        """
        css_input = "body {  color:  red;  }"
        mock_rcssmin = mock.Mock()
        mock_rcssmin.cssmin.return_value = "body{color:red}"

        with mock.patch.dict("sys.modules", {"rcssmin": mock_rcssmin}):
            result = _minify_css(css_input)

        assert result == "body{color:red}"

    def test_rcssmin_not_available_returns_original(self):
        """_minify_css returns the original content when rcssmin is not available.

        Purpose: Verify that _minify_css returns the original content string
                 unchanged when rcssmin raises an ImportError.
        Category: Edge case
        Target: _minify_css(content)
        Technique: Decision coverage (C1) - ImportError branch
        Test data: rcssmin not installed
        """
        css_input = "body {  color:  red;  }"

        with mock.patch.dict("sys.modules", {"rcssmin": None}):
            result = _minify_css(css_input)

        assert result == css_input

    def test_rcssmin_import_error_logs_warning(self):
        """_minify_css logs a warning when rcssmin raises ImportError.

        Purpose: Verify that _minify_css emits a logger.warning to notify
                 that minification is skipped when rcssmin raises ImportError.
        Category: Edge case
        Target: _minify_css(content)
        Technique: Error guessing
        Test data: rcssmin not installed
        """
        with (
            mock.patch.dict("sys.modules", {"rcssmin": None}),
            mock.patch("wagtail_asset_publisher.utils.logger") as mock_logger,
        ):
            _minify_css("body { color: red; }")

        mock_logger.warning.assert_called_once()
        assert "rcssmin is not installed" in mock_logger.warning.call_args[0][0]


class TestFindTerser:
    """Tests for _find_terser() search priority logic."""

    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    def test_explicit_terser_path_returns_immediately(self, mock_get_setting):
        """_find_terser returns the TERSER_PATH setting immediately when configured.

        Purpose: Verify that _find_terser returns the configured TERSER_PATH value
                 without performing any further search.
        Category: Normal case
        Target: _find_terser()
        Technique: Decision coverage (C1) - explicit path branch
        Test data: Explicit terser path configured via TERSER_PATH setting
        """
        mock_get_setting.return_value = "/custom/path/terser"

        result = _find_terser()

        assert result == "/custom/path/terser"

    @mock.patch("wagtail_asset_publisher.utils.shutil.which")
    @mock.patch("wagtail_asset_publisher.utils.Path.exists", return_value=True)
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=None)
    def test_node_modules_terser_found(self, _mock_setting, _mock_exists, mock_which):
        """_find_terser returns the path when terser exists in BASE_DIR/node_modules/.bin/.

        Purpose: Verify that _find_terser returns the node_modules path when
                 TERSER_PATH is not set and terser exists under BASE_DIR/node_modules.
        Category: Normal case
        Target: _find_terser()
        Technique: Decision coverage (C1) - node_modules branch
        Test data: BASE_DIR=/app, node_modules/.bin/terser present
        """
        with mock.patch("django.conf.settings") as mock_django_settings:
            mock_django_settings.BASE_DIR = "/app"
            result = _find_terser()

        assert "node_modules" in result
        assert result.endswith("terser")
        mock_which.assert_not_called()

    @mock.patch(
        "wagtail_asset_publisher.utils.shutil.which",
        return_value="/usr/local/bin/terser",
    )
    @mock.patch("wagtail_asset_publisher.utils.Path.exists", return_value=False)
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=None)
    def test_node_modules_not_found_falls_back_to_which(
        self, _mock_setting, _mock_exists, mock_which
    ):
        """_find_terser falls back to shutil.which when terser is not in node_modules.

        Purpose: Verify that _find_terser returns the result of shutil.which("terser")
                 when terser is not found in node_modules.
        Category: Normal case
        Target: _find_terser()
        Technique: Decision coverage (C1) - which fallback branch
        Test data: node_modules absent, terser present in PATH
        """
        with mock.patch("django.conf.settings") as mock_django_settings:
            mock_django_settings.BASE_DIR = "/app"
            result = _find_terser()

        assert result == "/usr/local/bin/terser"

    @mock.patch(
        "wagtail_asset_publisher.utils.shutil.which",
        return_value="/usr/local/bin/terser",
    )
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=None)
    def test_no_base_dir_falls_back_to_which(self, _mock_setting, mock_which):
        """_find_terser falls back to shutil.which when BASE_DIR is not set.

        Purpose: Verify that _find_terser skips the node_modules search and
                 returns the shutil.which result when BASE_DIR is None.
        Category: Edge case
        Target: _find_terser()
        Technique: Decision coverage (C1) - no BASE_DIR branch
        Test data: BASE_DIR not defined
        """
        mock_settings_obj = mock.Mock(spec=[])

        with mock.patch("django.conf.settings", mock_settings_obj):
            result = _find_terser()

        assert result == "/usr/local/bin/terser"

    @mock.patch("wagtail_asset_publisher.utils.shutil.which", return_value=None)
    @mock.patch("wagtail_asset_publisher.utils.get_setting", return_value=None)
    def test_terser_not_found_anywhere_returns_none(self, _mock_setting, _mock_which):
        """_find_terser returns None when terser is not found in any search path.

        Purpose: Verify that _find_terser returns None when terser cannot be
                 found through any of the available search paths.
        Category: Edge case
        Target: _find_terser()
        Technique: Boundary value analysis - all paths exhausted
        Test data: terser not installed
        """
        mock_settings_obj = mock.Mock(spec=[])

        with mock.patch("django.conf.settings", mock_settings_obj):
            result = _find_terser()

        assert result is None


class TestProcessCssMinification:
    """Tests for MINIFY_CSS integration in _process_css."""

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="min12345"
    )
    @mock.patch(
        "wagtail_asset_publisher.utils._minify_css", return_value="body{color:red}"
    )
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_minify_css_called_when_enabled(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_minify,
        mock_hash,
        mock_invalidate,
    ):
        """_process_css calls _minify_css when MINIFY_CSS is True.

        Purpose: Verify that _process_css calls _minify_css on the build result
                 when the MINIFY_CSS setting is True.
        Category: Normal case
        Target: _process_css(page, storage)
        Technique: Decision coverage (C1) - MINIFY_CSS=True branch
        Test data: MINIFY_CSS=True setting
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/css/42-min12345.css"

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
            "MINIFY_CSS": True,
            "HASH_LENGTH": 8,
            "CSS_PREFIX": "page-assets/css/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_asset"),
        ):
            _process_css(page, storage)

        mock_minify.assert_called_once_with("body { color: red; }")

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="raw12345"
    )
    @mock.patch("wagtail_asset_publisher.utils._minify_css")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_minify_css_not_called_when_disabled(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_minify,
        mock_hash,
        mock_invalidate,
    ):
        """_process_css does not call _minify_css when MINIFY_CSS is False.

        Purpose: Verify that _process_css does not call _minify_css and uses
                 the build result as-is when the MINIFY_CSS setting is False.
        Category: Normal case
        Target: _process_css(page, storage)
        Technique: Decision coverage (C1) - MINIFY_CSS=False branch
        Test data: MINIFY_CSS=False setting
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/css/42-raw12345.css"

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
            "MINIFY_CSS": False,
            "HASH_LENGTH": 8,
            "CSS_PREFIX": "page-assets/css/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_asset"),
        ):
            _process_css(page, storage)

        mock_minify.assert_not_called()


class TestProcessJsOptimization:
    """Tests for OBFUSCATE_JS integration in _process_js."""

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="opt12345"
    )
    @mock.patch("wagtail_asset_publisher.utils._optimize_js", return_value="var a=1;")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_optimize_js_called_when_enabled(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_optimize,
        mock_hash,
        mock_invalidate,
    ):
        """_process_js calls _optimize_js when OBFUSCATE_JS is True.

        Purpose: Verify that _process_js calls _optimize_js on the build result
                 when the OBFUSCATE_JS setting is True.
        Category: Normal case
        Target: _process_js(page, storage)
        Technique: Decision coverage (C1) - OBFUSCATE_JS=True branch
        Test data: OBFUSCATE_JS=True setting
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-opt12345.js"

        script = mock.Mock()
        script.content = "var  a  =  1;"
        script.content_hash = "jshash1"
        script.loading = ""
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "var  a  =  1;"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": True,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

        mock_optimize.assert_called_once_with("var  a  =  1;")

    @mock.patch("wagtail_asset_publisher.utils.invalidate_cache")
    @mock.patch(
        "wagtail_asset_publisher.utils.compute_content_hash", return_value="raw12345"
    )
    @mock.patch("wagtail_asset_publisher.utils._optimize_js")
    @mock.patch("wagtail_asset_publisher.utils.extract_assets_from_page")
    @mock.patch("wagtail_asset_publisher.utils.get_setting")
    @mock.patch("wagtail_asset_publisher.utils.get_builder")
    def test_optimize_js_not_called_when_disabled(
        self,
        mock_get_builder,
        mock_get_setting,
        mock_extract,
        mock_optimize,
        mock_hash,
        mock_invalidate,
    ):
        """_process_js does not call _optimize_js when OBFUSCATE_JS is False.

        Purpose: Verify that _process_js does not call _optimize_js and uses
                 the build result as-is when the OBFUSCATE_JS setting is False.
        Category: Normal case
        Target: _process_js(page, storage)
        Technique: Decision coverage (C1) - OBFUSCATE_JS=False branch
        Test data: OBFUSCATE_JS=False setting
        """
        page = mock.Mock(pk=42)
        storage = mock.Mock()
        storage.save.return_value = "/media/page-assets/js/42-raw12345.js"

        script = mock.Mock()
        script.content = "console.log('hello');"
        script.content_hash = "jshash1"
        script.loading = ""
        mock_extract.return_value = ([], [script])

        mock_builder = mock.Mock()
        mock_builder.build.return_value = "console.log('hello');"
        mock_get_builder.return_value = mock_builder

        mock_get_setting.side_effect = lambda key: {
            "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
            "OBFUSCATE_JS": False,
            "HASH_LENGTH": 8,
            "JS_PREFIX": "page-assets/js/",
        }[key]

        with (
            mock.patch("wagtail_asset_publisher.models.PublishedAsset"),
            mock.patch("wagtail_asset_publisher.utils._clear_js_assets"),
        ):
            _process_js(page, storage)

        mock_optimize.assert_not_called()
