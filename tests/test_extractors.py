"""Tests for wagtail_asset_publisher.extractors module.

Covers the AssetExtractor HTML parser, compute_content_hash,
extract_assets, extract_assets_from_page functions,
and _resolve_loading_strategy for script loading attributes.
"""

from unittest import mock

import pytest

from wagtail_asset_publisher.extractors import (
    ExtractedAsset,
    compute_content_hash,
    extract_assets,
    extract_assets_from_page,
)


class TestExtractAssetsSingleTags:
    """Tests for extracting individual <style> and <script> tags."""

    def test_extract_single_style(self, sample_html_with_style):
        """Single inline <style> tag is extracted with correct content and hash.

        Purpose: Verify the core extraction of a single <style> tag from HTML,
            confirming both content and hash are captured correctly.
        Category: Normal case
        Target: extract_assets(html)
        Technique: Equivalence partitioning (valid HTML with one style tag)
        Test data: HTML with one <style> containing 'body { color: red; }'
        """
        styles, scripts = extract_assets(sample_html_with_style)

        assert len(styles) == 1
        assert styles[0].content == "body { color: red; }"
        assert styles[0].content_hash == compute_content_hash("body { color: red; }")
        assert scripts == []

    def test_extract_single_script(self, sample_html_with_script):
        """Single inline <script> tag is extracted with correct content and hash.

        Purpose: Verify the core extraction of a single <script> tag from HTML.
        Category: Normal case
        Target: extract_assets(html)
        Technique: Equivalence partitioning (valid HTML with one script tag)
        Test data: HTML with one <script> containing console.log("hello");
        """
        styles, scripts = extract_assets(sample_html_with_script)

        assert styles == []
        assert len(scripts) == 1
        assert scripts[0].content == 'console.log("hello");'

    def test_extract_style_and_script(self, sample_html_with_both):
        """Both <style> and <script> tags are extracted from same HTML.

        Purpose: Verify that mixed asset types are correctly separated
            into their respective lists.
        Category: Normal case
        Target: extract_assets(html)
        Technique: Equivalence partitioning (HTML with both tag types)
        Test data: HTML with one <style> and one <script>
        """
        styles, scripts = extract_assets(sample_html_with_both)

        assert len(styles) == 1
        assert styles[0].content == ".hero { color: red; }"
        assert len(scripts) == 1
        assert scripts[0].content == 'alert("hi");'


class TestExtractAssetsMultipleTags:
    """Tests for extracting multiple tags of same type."""

    def test_extract_multiple_styles(self):
        """Multiple <style> tags are all extracted in order.

        Purpose: Verify that all <style> tags are captured when multiple
            exist in the HTML, preserving order.
        Category: Normal case
        Target: extract_assets(html)
        Technique: Equivalence partitioning (multiple same-type tags)
        Test data: HTML with three <style> tags
        """
        html = (
            "<style>a { color: red; }</style>"
            "<style>b { color: blue; }</style>"
            "<style>c { color: green; }</style>"
        )

        styles, scripts = extract_assets(html)

        assert len(styles) == 3
        assert styles[0].content == "a { color: red; }"
        assert styles[1].content == "b { color: blue; }"
        assert styles[2].content == "c { color: green; }"

    def test_sequential_same_type_tags(self):
        """Consecutive <style> tags are both extracted individually.

        Purpose: Verify that two adjacent <style> tags do not interfere
            with each other during parsing.
        Category: Normal case
        Target: extract_assets(html)
        Technique: Equivalence partitioning (adjacent same-type tags)
        Test data: Two adjacent <style> tags with different content
        """
        html = "<style>A</style><style>B</style>"

        styles, scripts = extract_assets(html)

        assert len(styles) == 2
        assert styles[0].content == "A"
        assert styles[1].content == "B"


class TestExtractAssetsSkipBehavior:
    """Tests for tags that should NOT be extracted."""

    def test_data_no_extract_skips_style(self, sample_html_with_no_extract):
        """<style data-no-extract> is not extracted.

        Purpose: Verify that the data-no-extract attribute prevents a <style>
            tag from being collected, allowing critical CSS to stay inline.
        Category: Normal case (skip behavior)
        Target: extract_assets(html)
        Technique: Equivalence partitioning (data-no-extract attribute present)
        Test data: HTML with one data-no-extract style and one normal style
        """
        styles, scripts = extract_assets(sample_html_with_no_extract)

        assert len(styles) == 1
        assert styles[0].content == ".hero { color: red; }"

    def test_data_no_extract_skips_script(self):
        """<script data-no-extract> is not extracted.

        Purpose: Verify that the data-no-extract attribute also works for
            <script> tags, keeping critical inline JS in place.
        Category: Normal case (skip behavior)
        Target: extract_assets(html)
        Technique: Equivalence partitioning (data-no-extract on script)
        Test data: HTML with data-no-extract script and normal script
        """
        html = (
            "<script data-no-extract>critical();</script>"
            "<script>extractable();</script>"
        )

        styles, scripts = extract_assets(html)

        assert len(scripts) == 1
        assert scripts[0].content == "extractable();"

    def test_external_script_not_extracted(self, sample_html_with_external_script):
        """<script src="..."> (external) is not extracted.

        Purpose: Verify that external scripts with src attribute are skipped,
            since only inline content should be extracted.
        Category: Normal case (skip behavior)
        Target: extract_assets(html)
        Technique: Equivalence partitioning (external script with src)
        Test data: HTML with one external and one inline script
        """
        styles, scripts = extract_assets(sample_html_with_external_script)

        assert len(scripts) == 1
        assert scripts[0].content == 'console.log("inline");'


class TestResolveLoadingStrategy:
    """Tests for _resolve_loading_strategy via extract_assets.

    ## Decision Table: DT-LOADING-STRATEGY

    | ID   | type attr              | async | defer | Expected loading | Extracted? |
    |------|------------------------|-------|-------|------------------|------------|
    | DT1  | (none)                 | no    | no    | ""               | yes        |
    | DT2  | (none)                 | no    | yes   | "defer"          | yes        |
    | DT3  | (none)                 | yes   | no    | "async"          | yes        |
    | DT4  | (none)                 | yes   | yes   | "async"          | yes        |
    | DT5  | "module"               | no    | no    | "module"         | yes        |
    | DT6  | "module"               | yes   | no    | "module-async"   | yes        |
    | DT7  | "module"               | no    | yes   | "module"         | yes        |
    | DT8  | "text/javascript"      | no    | no    | ""               | yes        |
    | DT9  | "application/javascript"| no   | no    | ""               | yes        |
    | DT10 | "importmap"            | no    | no    | N/A              | no         |
    | DT11 | "speculationrules"     | no    | no    | N/A              | no         |
    | DT12 | "text/template"        | no    | no    | N/A              | no         |
    | DT13 | "module"               | yes   | yes   | "module-async"   | yes        |
    """

    @pytest.mark.parametrize(
        "tag,expected_loading",
        [
            pytest.param("<script>code();</script>", "", id="DT1-no-attrs"),
            pytest.param("<script defer>code();</script>", "defer", id="DT2-defer"),
            pytest.param("<script async>code();</script>", "async", id="DT3-async"),
            pytest.param(
                "<script async defer>code();</script>",
                "async",
                id="DT4-async-defer-async-wins",
            ),
            pytest.param(
                '<script type="module">code();</script>',
                "module",
                id="DT5-module",
            ),
            pytest.param(
                '<script type="module" async>code();</script>',
                "module-async",
                id="DT6-module-async",
            ),
            pytest.param(
                '<script type="module" defer>code();</script>',
                "module",
                id="DT7-module-defer-inherently-deferred",
            ),
            pytest.param(
                '<script type="text/javascript">code();</script>',
                "",
                id="DT8-text-javascript-mime",
            ),
            pytest.param(
                '<script type="application/javascript">code();</script>',
                "",
                id="DT9-application-javascript-mime",
            ),
            pytest.param(
                '<script type="module" async defer>code();</script>',
                "module-async",
                id="DT13-module-async-defer",
            ),
        ],
    )
    def test_loading_strategy_for_extracted_scripts(self, tag, expected_loading):
        """DT-LOADING-STRATEGY参照: 各属性パターンに対するloading値を検証する。

        【目的】<script>タグの属性組み合わせに応じて、正しいloading strategy
               が設定されることをもって、スクリプトの読み込み戦略の分類要件を保証する
        【種別】正常系テスト
        【対象】AssetExtractor._resolve_loading_strategy(attr_dict)
        【技法】デシジョンテーブル
        【テストデータ】DT-LOADING-STRATEGYのDT1-DT9, DT13パターン
        """
        _, scripts = extract_assets(tag)

        assert len(scripts) == 1
        assert scripts[0].loading == expected_loading

    @pytest.mark.parametrize(
        "tag",
        [
            pytest.param(
                '<script type="importmap">{"imports": {}}</script>',
                id="DT10-importmap-skipped",
            ),
            pytest.param(
                '<script type="speculationrules">{"prefetch": []}</script>',
                id="DT11-speculationrules-skipped",
            ),
            pytest.param(
                '<script type="text/template"><div>template</div></script>',
                id="DT12-text-template-skipped",
            ),
        ],
    )
    def test_non_js_type_scripts_not_extracted(self, tag):
        """DT-LOADING-STRATEGY参照: 非JSタイプのscriptが抽出されないことを検証する。

        【目的】importmap, speculationrules, text/template等の非JSタイプの
               scriptタグが抽出対象から除外されることをもって、
               非実行スクリプトの保護要件を保証する
        【種別】正常系テスト（スキップ動作）
        【対象】AssetExtractor._resolve_loading_strategy(attr_dict)
        【技法】デシジョンテーブル
        【テストデータ】DT-LOADING-STRATEGYのDT10-DT12パターン
        """
        _, scripts = extract_assets(tag)

        assert scripts == []

    def test_default_script_has_empty_loading(self):
        """属性なし<script>のloading値がデフォルト空文字であることを検証する。

        【目的】<script>タグにasync/defer/type属性がない場合、
               loading=""（ブロッキング）として分類されることを保証する
        【種別】正常系テスト
        【対象】extract_assets(html) -> ExtractedAsset.loading
        【技法】同値分割（属性なしクラスの代表値）
        【テストデータ】属性なしの<script>タグ
        """
        html = "<script>console.log('default');</script>"

        _, scripts = extract_assets(html)

        assert len(scripts) == 1
        assert scripts[0].loading == ""

    def test_mixed_loading_strategies_all_extracted(self):
        """異なるloading strategyのスクリプトが全て正しく抽出されることを検証する。

        【目的】複数のloading strategyが混在するHTMLから、各スクリプトが
               正しいloading値で個別に抽出されることを保証する
        【種別】正常系テスト
        【対象】extract_assets(html)
        【技法】状態遷移（パーサの連続タグ処理）
        【テストデータ】blocking, defer, async, moduleの4種類の<script>タグ
        """
        html = (
            "<script>blocking();</script>"
            "<script defer>deferred();</script>"
            "<script async>asynced();</script>"
            '<script type="module">modular();</script>'
        )

        _, scripts = extract_assets(html)

        assert len(scripts) == 4
        assert scripts[0].loading == ""
        assert scripts[0].content == "blocking();"
        assert scripts[1].loading == "defer"
        assert scripts[1].content == "deferred();"
        assert scripts[2].loading == "async"
        assert scripts[2].content == "asynced();"
        assert scripts[3].loading == "module"
        assert scripts[3].content == "modular();"

    def test_non_js_type_mixed_with_js_scripts(self):
        """非JSタイプのscriptが除外され、JSスクリプトのみ抽出されることを検証する。

        【目的】importmapタグと通常スクリプトが混在する場合、
               importmapのみがスキップされ通常スクリプトが正しく抽出されることを保証する
        【種別】正常系テスト（混在ケース）
        【対象】extract_assets(html)
        【技法】同値分割（抽出対象と非対象の混在）
        【テストデータ】importmapタグ1つ + 通常scriptタグ1つ
        """
        html = (
            '<script type="importmap">{"imports": {}}</script>'
            "<script>normal();</script>"
        )

        _, scripts = extract_assets(html)

        assert len(scripts) == 1
        assert scripts[0].content == "normal();"
        assert scripts[0].loading == ""


class TestExtractedAssetLoadingField:
    """Tests for ExtractedAsset loading field default value."""

    def test_extracted_asset_loading_default(self):
        """ExtractedAssetのloading値がデフォルトで空文字であることを検証する。

        【目的】ExtractedAsset NamedTupleのloading fieldがデフォルトで
               空文字に設定されることを保証する
        【種別】正常系テスト
        【対象】ExtractedAsset(content, content_hash)
        【技法】境界値分析（デフォルト値）
        【テストデータ】loadingを指定しないExtractedAsset
        """
        asset = ExtractedAsset(content="body {}", content_hash="abc12345")

        assert asset.loading == ""

    def test_extracted_asset_loading_explicit(self):
        """ExtractedAssetのloading値を明示的に設定できることを検証する。

        【目的】ExtractedAsset NamedTupleのloading fieldに明示的な値を
               設定できることを保証する
        【種別】正常系テスト
        【対象】ExtractedAsset(content, content_hash, loading)
        【技法】同値分割（明示的なloading値）
        【テストデータ】loading="defer"のExtractedAsset
        """
        asset = ExtractedAsset(
            content="body {}", content_hash="abc12345", loading="defer"
        )

        assert asset.loading == "defer"

    def test_extracted_asset_equality_with_loading(self):
        """同じloading値のExtractedAssetが等価であることを検証する。

        【目的】loading fieldを含むExtractedAssetの等価性が正しく機能することを保証する
        【種別】正常系テスト
        【対象】ExtractedAsset equality
        【技法】同値分割
        【テストデータ】同一のcontent, content_hash, loadingを持つ2つのインスタンス
        """
        asset1 = ExtractedAsset(content="x", content_hash="h", loading="module")
        asset2 = ExtractedAsset(content="x", content_hash="h", loading="module")

        assert asset1 == asset2

    def test_extracted_asset_inequality_by_loading(self):
        """異なるloading値のExtractedAssetが不等であることを検証する。

        【目的】loading fieldが異なるExtractedAssetが不等であることを保証する
        【種別】正常系テスト
        【対象】ExtractedAsset inequality
        【技法】同値分割（異なるloading値）
        【テストデータ】loadingのみ異なる2つのインスタンス
        """
        asset1 = ExtractedAsset(content="x", content_hash="h", loading="defer")
        asset2 = ExtractedAsset(content="x", content_hash="h", loading="async")

        assert asset1 != asset2


class TestExtractAssetsEdgeCases:
    """Edge case tests for the extraction pipeline."""

    def test_empty_style_not_extracted(self):
        """Empty <style></style> produces no extracted asset.

        Purpose: Verify that empty style tags are ignored, avoiding creation
            of empty asset files.
        Category: Edge case
        Target: extract_assets(html)
        Technique: Boundary value analysis (empty content)
        Test data: <style></style> with no content
        """
        html = "<style></style>"

        styles, scripts = extract_assets(html)

        assert styles == []

    def test_empty_script_not_extracted(self):
        """Empty <script></script> produces no extracted asset.

        Purpose: Verify that empty script tags are ignored.
        Category: Edge case
        Target: extract_assets(html)
        Technique: Boundary value analysis (empty content)
        Test data: <script></script> with no content
        """
        html = "<script></script>"

        styles, scripts = extract_assets(html)

        assert scripts == []

    def test_empty_html_returns_empty(self):
        """Empty string input returns empty lists for both styles and scripts.

        Purpose: Verify graceful handling of empty input.
        Category: Edge case
        Target: extract_assets(html)
        Technique: Boundary value analysis (empty input)
        Test data: Empty string
        """
        styles, scripts = extract_assets("")

        assert styles == []
        assert scripts == []

    def test_html_without_any_tags_returns_empty(self):
        """HTML with no <style> or <script> tags returns empty lists.

        Purpose: Verify that normal HTML content without extractable tags
            returns empty results.
        Category: Edge case
        Target: extract_assets(html)
        Technique: Equivalence partitioning (no extractable tags)
        Test data: Plain HTML paragraph
        """
        html = "<div><p>Hello World</p></div>"

        styles, scripts = extract_assets(html)

        assert styles == []
        assert scripts == []

    def test_whitespace_stripped_from_content(self):
        """Whitespace is stripped from extracted content.

        Purpose: Verify that leading/trailing whitespace in tag content is
            stripped before storage and hashing.
        Category: Edge case
        Target: extract_assets(html)
        Technique: Boundary value analysis (whitespace-only edges)
        Test data: <style> with leading/trailing whitespace around content
        """
        html = "<style>  \n  body { color: red; }  \n  </style>"

        styles, _ = extract_assets(html)

        assert len(styles) == 1
        assert styles[0].content == "body { color: red; }"

    def test_whitespace_only_style_not_extracted(self):
        """<style> containing only whitespace is not extracted.

        Purpose: Verify that whitespace-only content is treated as empty
            after stripping.
        Category: Edge case
        Target: extract_assets(html)
        Technique: Boundary value analysis (whitespace-only content)
        Test data: <style> with only spaces and newlines
        """
        html = "<style>   \n\t  </style>"

        styles, _ = extract_assets(html)

        assert styles == []


class TestComputeContentHash:
    """Tests for the compute_content_hash utility function."""

    def test_content_hash_consistency(self):
        """Same content always produces same hash.

        Purpose: Verify hash determinism -- the same input must always yield
            the same output for cache matching to work.
        Category: Normal case
        Target: compute_content_hash(content, length)
        Technique: Equivalence partitioning (deterministic output)
        Test data: Fixed string computed twice
        """
        content = "body { color: red; }"

        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)

        assert hash1 == hash2

    def test_content_hash_different_for_different_content(self):
        """Different content produces different hashes.

        Purpose: Verify that hash collisions do not occur for distinct inputs
            (within practical limits of SHA-256 truncation).
        Category: Normal case
        Target: compute_content_hash(content, length)
        Technique: Equivalence partitioning (different inputs)
        Test data: Two distinct CSS strings
        """
        hash1 = compute_content_hash("body { color: red; }")
        hash2 = compute_content_hash("body { color: blue; }")

        assert hash1 != hash2

    def test_content_hash_default_length(self):
        """Default hash length is 8 characters.

        Purpose: Verify the default truncation length matches HASH_LENGTH default.
        Category: Normal case
        Target: compute_content_hash(content)
        Technique: Boundary value analysis (default parameter)
        Test data: Any non-empty string
        """
        result = compute_content_hash("test content")

        assert len(result) == 8

    def test_content_hash_custom_length(self):
        """Custom length parameter truncates hash correctly.

        Purpose: Verify that the length parameter controls output length.
        Category: Normal case
        Target: compute_content_hash(content, length)
        Technique: Boundary value analysis (non-default parameter)
        Test data: length=12
        """
        result = compute_content_hash("test content", length=12)

        assert len(result) == 12

    def test_content_hash_is_hex(self):
        """Hash output contains only hexadecimal characters.

        Purpose: Verify the hash is valid hex (from SHA-256).
        Category: Normal case
        Target: compute_content_hash(content)
        Technique: Error guessing (invalid characters in hash)
        Test data: Any non-empty string
        """
        result = compute_content_hash("any content")

        assert all(c in "0123456789abcdef" for c in result)


class TestExtractedAssetNamedTuple:
    """Tests for the ExtractedAsset NamedTuple."""

    def test_extracted_asset_fields(self):
        """ExtractedAsset has content and content_hash fields.

        Purpose: Verify the NamedTuple structure is correct.
        Category: Normal case
        Target: ExtractedAsset
        Technique: Equivalence partitioning
        Test data: Simple content and hash
        """
        asset = ExtractedAsset(content="body {}", content_hash="abc12345")

        assert asset.content == "body {}"
        assert asset.content_hash == "abc12345"

    def test_extracted_asset_equality(self):
        """Two ExtractedAssets with same fields are equal.

        Purpose: Verify NamedTuple equality semantics for test assertions.
        Category: Normal case
        Target: ExtractedAsset
        Technique: Equivalence partitioning
        Test data: Two identical ExtractedAsset instances
        """
        asset1 = ExtractedAsset(content="body {}", content_hash="abc")
        asset2 = ExtractedAsset(content="body {}", content_hash="abc")

        assert asset1 == asset2


class TestExtractAssetsFromPage:
    """Tests for extract_assets_from_page with mocked Wagtail pages."""

    def test_extract_assets_from_page_with_streamfield(self):
        """Page with StreamField containing style/script tags yields extracted assets.

        Purpose: Verify that extract_assets_from_page correctly iterates over
            StreamField fields, renders them, and extracts inline assets.
        Category: Normal case
        Target: extract_assets_from_page(page)
        Technique: Equivalence partitioning (page with StreamField)
        Test data: Mock page with one StreamField containing HTML with style
        """
        mock_field = mock.Mock()
        mock_field.name = "body"

        mock_stream_value = mock.Mock()
        mock_stream_value.__str__ = mock.Mock(
            return_value="<style>.hero { color: red; }</style><p>Hello</p>"
        )
        mock_stream_value.__bool__ = mock.Mock(return_value=True)

        mock_page = mock.Mock()
        mock_page._meta.get_fields.return_value = [mock_field]
        mock_page.body = mock_stream_value

        class FakeStreamFieldMeta(type):
            def __instancecheck__(cls, instance):
                return instance is mock_field

        class FakeStreamField(metaclass=FakeStreamFieldMeta):
            pass

        with mock.patch("wagtail.fields.StreamField", FakeStreamField):
            styles, scripts = extract_assets_from_page(mock_page)

        assert len(styles) == 1
        assert styles[0].content == ".hero { color: red; }"

    def test_extract_assets_from_page_no_streamfield(self):
        """Page without StreamField returns empty lists.

        Purpose: Verify that pages with no StreamField fields produce no
            extracted assets.
        Category: Edge case
        Target: extract_assets_from_page(page)
        Technique: Equivalence partitioning (page without StreamField)
        Test data: Mock page with non-StreamField fields only
        """
        mock_field = mock.Mock()
        mock_field.name = "title"

        mock_page = mock.Mock()
        mock_page._meta.get_fields.return_value = [mock_field]

        class FakeStreamFieldMeta(type):
            def __instancecheck__(cls, instance):
                return False

        class FakeStreamField(metaclass=FakeStreamFieldMeta):
            pass

        with mock.patch("wagtail.fields.StreamField", FakeStreamField):
            styles, scripts = extract_assets_from_page(mock_page)

        assert styles == []
        assert scripts == []

    def test_extract_assets_from_page_empty_streamfield(self):
        """Page with empty StreamField returns empty lists.

        Purpose: Verify that a StreamField that exists but is empty
            (falsy stream_value) does not produce assets.
        Category: Edge case
        Target: extract_assets_from_page(page)
        Technique: Boundary value analysis (empty StreamField)
        Test data: Mock page with StreamField returning empty/falsy value
        """
        mock_field = mock.Mock()
        mock_field.name = "body"

        mock_stream_value = mock.Mock()
        mock_stream_value.__bool__ = mock.Mock(return_value=False)

        mock_page = mock.Mock()
        mock_page._meta.get_fields.return_value = [mock_field]
        mock_page.body = mock_stream_value

        class FakeStreamFieldMeta(type):
            def __instancecheck__(cls, instance):
                return instance is mock_field

        class FakeStreamField(metaclass=FakeStreamFieldMeta):
            pass

        with mock.patch("wagtail.fields.StreamField", FakeStreamField):
            styles, scripts = extract_assets_from_page(mock_page)

        assert styles == []
        assert scripts == []
