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

        【目的】blocking, defer, async, module, module-async の5種類のscriptを含むページを
               ビルドした際、それぞれ独立したPublishedAssetレコードが作成され、
               loadingフィールドに正しい戦略値が保存されることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → _process_js → RawAssetBuilder → DjangoStorageBackend → PublishedAsset
        【テストデータ】
        - 5種類のloading strategy（blocking, defer, async, module, module-async）
        - 各1スクリプトずつ
        【検証シナリオ】
        1. 5種類のloading strategyを持つscriptを抽出結果として注入
        2. build_page_assetsを実行
        3. 5つのJS PublishedAssetレコードが作成されていることを確認
        4. 各レコードのloadingフィールドが正しいことを確認
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

        【目的】ビルド後のPublishedAssetレコードのcontent_hashesフィールドに、
               当該グループのスクリプトのハッシュのみが含まれることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → grouping → PublishedAsset.content_hashes
        【テストデータ】
        - blocking scriptとdefer scriptの2種類
        【検証シナリオ】
        1. blocking, deferのscriptを注入してビルド
        2. blockingレコードにはblocking scriptのハッシュのみ含まれることを確認
        3. deferレコードにはdefer scriptのハッシュのみ含まれることを確認
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

        【目的】defer等の非空loading strategyがファイル名のサフィックスとして
               URL内に反映されることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → filename generation → DjangoStorageBackend → PublishedAsset.url
        【テストデータ】
        - blocking script（loadingなし）とdefer scriptの2種類
        【検証シナリオ】
        1. blocking, deferのscriptを注入してビルド
        2. blockingレコードのURLに「-defer」が含まれないことを確認
        3. deferレコードのURLに「-defer」サフィックスが含まれることを確認
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

        【目的】同じloading strategyを持つ複数スクリプトが1つのPublishedAssetレコードに
               まとめられ、content_hashesに全スクリプトのハッシュが含まれることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → grouping → RawAssetBuilder.build → PublishedAsset
        【テストデータ】
        - 同一loading strategy（defer）の2スクリプト
        【検証シナリオ】
        1. defer strategyの2スクリプトを注入してビルド
        2. JS PublishedAssetレコードが1つだけ作成されることを確認
        3. content_hashesに両方のスクリプトのハッシュが含まれることを確認
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

        【目的】deferスクリプトがPublishedAssetとして保存された後、ミドルウェアが
               レスポンスHTMLに<script defer>タグを注入することを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → PublishedAsset → _get_published_assets → _process_html
        【テストデータ】
        - defer loading strategyの1スクリプト
        【検証シナリオ】
        1. defer scriptをビルドしてPublishedAssetを作成
        2. _process_htmlでHTML変換を実行
        3. 出力HTMLに<script src="..." defer>タグが含まれることを確認
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

        【目的】asyncスクリプトがPublishedAssetとして保存された後、ミドルウェアが
               レスポンスHTMLに<script async>タグを注入することを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → PublishedAsset → _get_published_assets → _process_html
        【テストデータ】
        - async loading strategyの1スクリプト
        【検証シナリオ】
        1. async scriptをビルドしてPublishedAssetを作成
        2. _process_htmlでHTML変換を実行
        3. 出力HTMLに<script src="..." async>タグが含まれることを確認
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

        【目的】moduleスクリプトがPublishedAssetとして保存された後、ミドルウェアが
               レスポンスHTMLに<script type="module">タグを注入することを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → PublishedAsset → _get_published_assets → _process_html
        【テストデータ】
        - module loading strategyの1スクリプト
        【検証シナリオ】
        1. module scriptをビルドしてPublishedAssetを作成
        2. _process_htmlでHTML変換を実行
        3. 出力HTMLに<script src="..." type="module">タグが含まれることを確認
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

        【目的】module-asyncスクリプトがPublishedAssetとして保存された後、ミドルウェアが
               レスポンスHTMLに<script type="module" async>タグを注入することを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → PublishedAsset → _get_published_assets → _process_html
        【テストデータ】
        - module-async loading strategyの1スクリプト
        【検証シナリオ】
        1. module-async scriptをビルドしてPublishedAssetを作成
        2. _process_htmlでHTML変換を実行
        3. 出力HTMLにtype="module"とasync属性の両方が含まれることを確認
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

        【目的】blocking（loading=""）スクリプトがPublishedAssetとして保存された後、
               ミドルウェアがdefer/async/type属性なしのプレーンな<script>タグを
               注入することを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → PublishedAsset → _get_published_assets → _process_html
        【テストデータ】
        - blocking（空文字loading strategy）の1スクリプト
        【検証シナリオ】
        1. blocking scriptをビルドしてPublishedAssetを作成
        2. _process_htmlでHTML変換を実行
        3. 出力HTMLのscriptタグにdefer/async/type属性が含まれないことを確認
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

        【目的】複数のloading strategyが存在する場合、ミドルウェアが定義された順序
               （blocking → defer → module → async → module-async）で
               scriptタグを注入することを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → PublishedAsset → _process_html → _JS_LOADING_ORDER
        【テストデータ】
        - blocking, defer, async, module, module-asyncの5種類のスクリプト
        【検証シナリオ】
        1. 5種類のloading strategyのscriptをビルドしてPublishedAssetを作成
        2. _process_htmlでHTML変換を実行
        3. 出力HTMLでscriptタグの順序が定義された順序に従うことを確認
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

        【目的】ミドルウェアが、PublishedAssetのcontent_hashesと一致するインラインscriptを
               除去し、外部ファイル参照を</body>前に注入することを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → _strip_matching_tags → _process_html
        【テストデータ】
        - defer scriptの内容をインラインHTMLに含むページ
        【検証シナリオ】
        1. defer scriptをビルド
        2. _process_htmlでインラインscriptを含むHTMLを変換
        3. インラインscript内容が除去されていることを確認
        4. 外部ファイル参照scriptタグが注入されていることを確認
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

        【目的】ページ内容を変更して再ビルドした際、古いJS PublishedAssetレコードが
               全て削除され、新しいスクリプトに対応するレコードのみ残ることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → _clear_js_assets → _process_js → PublishedAsset
        【テストデータ】
        - 初回ビルド: blocking + defer の2スクリプト
        - 再ビルド: async の1スクリプトのみ
        【検証シナリオ】
        1. blocking + defer scriptでビルド → 2レコード作成
        2. async scriptのみで再ビルド → 古い2レコードが削除、asyncの1レコードのみ残存
        3. loading="async"のレコードのみ存在することを確認
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

        【目的】スクリプトのないページに変更して再ビルドした際、
               全てのJS PublishedAssetレコードが削除されることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → _clear_js_assets → PublishedAsset.delete
        【テストデータ】
        - 初回ビルド: defer + module の2スクリプト
        - 再ビルド: スクリプトなし
        【検証シナリオ】
        1. defer + module scriptでビルド → 2レコード作成
        2. スクリプトなしで再ビルド → 全レコード削除
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

        【目的】JS内容だけが変更された再ビルドで、CSS PublishedAssetが影響を受けず
               そのまま維持されることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → _process_css + _process_js → PublishedAsset
        【テストデータ】
        - CSS + defer JS でビルド後、CSS + async JS で再ビルド
        【検証シナリオ】
        1. CSS + defer JSでビルド
        2. CSS + async JSで再ビルド
        3. CSS PublishedAssetが維持されていることを確認
        4. JS PublishedAssetがasyncのみに変更されていることを確認
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

        【目的】type="importmap"のscriptタグが抽出対象から除外され、
               PublishedAssetレコードが作成されないことを保証する
        【種別】正常系
        【技法】APIエンドポイント
        【連携対象】extract_assets → _resolve_loading_strategy → build_page_assets
        【テストデータ】
        - type="importmap"スクリプト1つのみのページ
        【検証シナリオ】
        1. importmap scriptのみを含むHTMLから抽出を実行
        2. 抽出結果が空であることを確認（extractorがスキップ）
        3. build_page_assetsを実行してもJS PublishedAssetが作成されないことを確認
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

        【目的】type="speculationrules"のscriptタグが抽出対象から除外されることを保証する
        【種別】正常系
        【技法】APIエンドポイント
        【連携対象】extract_assets → _resolve_loading_strategy
        【テストデータ】
        - type="speculationrules"スクリプト1つ
        【検証シナリオ】
        1. speculationrules scriptを含むHTMLから抽出を実行
        2. 抽出結果が空であることを確認
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

        【目的】importmapと通常JSが同じページに存在する場合、通常JSのみが
               抽出・ビルドされ、importmapはインラインのまま残ることを保証する
        【種別】正常系
        【技法】モデルライフサイクル
        【連携対象】extract_assets → build_page_assets → PublishedAsset
        【テストデータ】
        - type="importmap"スクリプトと通常のdeferスクリプトの2つ
        【検証シナリオ】
        1. importmap + defer scriptを含むHTMLから抽出
        2. 抽出結果がdefer scriptの1つのみであることを確認
        3. build_page_assetsを実行してdefer JS PublishedAssetのみ作成されることを確認
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

        【目的】defer/async属性のないプレーンなscriptタグのみを含むページをビルドした際、
               loading=""（blocking）のPublishedAssetレコードが1つだけ作成されることを保証する
        【種別】正常系（後方互換性）
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → _process_js → PublishedAsset
        【テストデータ】
        - loading属性なしの通常スクリプト2つ
        【検証シナリオ】
        1. 2つの通常scriptを注入してビルド
        2. JS PublishedAssetが1つだけ作成されることを確認
        3. loadingフィールドが空文字であることを確認
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

        【目的】プレーンなblockingスクリプトに対して、ミドルウェアがdefer/async/type属性なしの
               シンプルなscriptタグを注入することを保証する（後方互換性）
        【種別】正常系（後方互換性）
        【技法】ミドルウェア動作
        【連携対象】build_page_assets → PublishedAsset → _process_html
        【テストデータ】
        - loading属性なしの通常スクリプト1つ
        【検証シナリオ】
        1. 通常scriptをビルドしてPublishedAssetを作成
        2. _process_htmlでHTML変換を実行
        3. scriptタグにdefer/async/type属性が含まれないことを確認
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

        【目的】同じ通常スクリプトで2回ビルドしても、PublishedAssetレコードが
               重複せず1つのまま維持されることを保証する（冪等性）
        【種別】冪等性
        【技法】モデルライフサイクル
        【連携対象】build_page_assets → update_or_create → PublishedAsset
        【テストデータ】
        - 通常スクリプト1つで2回ビルド
        【検証シナリオ】
        1. 通常scriptで1回目のビルドを実行
        2. 同じ通常scriptで2回目のビルドを実行
        3. JS PublishedAssetレコードが1つのみ存在することを確認
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

        【目的】AssetPublisherMiddleware全体を通したラウンドトリップで、
               wagtailpageが設定されたHTMLレスポンスにdefer scriptタグが
               正しく注入されることを保証する
        【種別】正常系
        【技法】ミドルウェア動作
        【連携対象】AssetPublisherMiddleware.__call__ → _get_page → _get_published_assets → _process_html
        【テストデータ】
        - defer loading strategyの1スクリプト
        - wagtailpage属性がセットされたHTMLレスポンス
        【検証シナリオ】
        1. defer scriptをビルドしてPublishedAssetを作成
        2. wagtailpage属性付きリクエストでミドルウェアを通過
        3. レスポンスHTMLにdefer属性付きscriptタグが注入されていることを確認
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
