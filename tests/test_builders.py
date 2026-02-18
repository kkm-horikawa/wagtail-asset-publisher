"""Tests for wagtail-asset-publisher v2 asset builders.

## Builder Interface (v2)

    build(html_content: str | None, extracted_content: list[str], asset_type: str) -> str

## Decision Table: DT-RAW-BUILDER

| ID  | html_content | extracted_content          | asset_type | expected                       |
|-----|-------------|---------------------------|-----------|-------------------------------|
| DT1 | None        | ["a{}", "b{}"]            | css       | "a{}\\n\\nb{}"                 |
| DT2 | None        | ["alert(1)", "alert(2)"]  | js        | "alert(1)\\n\\nalert(2)"      |
| DT3 | None        | []                        | css       | ""                             |
| DT4 | None        | ["single"]                | css       | "single"                       |
| DT5 | "<html>"    | ["a{}"]                   | css       | "a{}"  (html_content ignored) |

## Decision Table: DT-TAILWIND-BUILDER

| ID  | html_content       | extracted_content | asset_type | expected behavior              |
|-----|-------------------|-------------------|-----------|-------------------------------|
| DT6 | None              | ["alert(1)"]      | js        | "alert(1)" (fallback to raw)  |
| DT7 | None              | []                | css       | "" (empty)                     |
| DT8 | "<div class=...>" | [".custom{}"]     | css       | _run_tailwind called           |
| DT9 | CLI error         | [".custom{}"]     | css       | ".custom{}" (fallback)         |
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from wagtail_asset_publisher.builders.raw import RawAssetBuilder
from wagtail_asset_publisher.builders.tailwind import (
    DEFAULT_TAILWIND_INPUT,
    TailwindCSSBuilder,
)


class TestRawAssetBuilder:
    def test_concatenates_css(self):
        """RawAssetBuilder joins multiple CSS strings with double newlines (DT1).

        Purpose: Verify that build() concatenates extracted CSS content
                 with double newlines as separator.
        Category: Normal case
        Target: RawAssetBuilder.build(html_content, extracted_content, asset_type)
        Technique: Equivalence partitioning
        Test data: Two CSS rule blocks
        """
        builder = RawAssetBuilder()

        result = builder.build(None, ["a{}", "b{}"], "css")

        assert result == "a{}\n\nb{}"

    def test_concatenates_js(self):
        """RawAssetBuilder joins multiple JS strings with double newlines (DT2).

        Purpose: Verify that build() concatenates extracted JS content
                 with double newlines as separator.
        Category: Normal case
        Target: RawAssetBuilder.build(html_content, extracted_content, asset_type)
        Technique: Equivalence partitioning
        Test data: Two JS statements
        """
        builder = RawAssetBuilder()

        result = builder.build(None, ["alert(1)", "alert(2)"], "js")

        assert result == "alert(1)\n\nalert(2)"

    def test_empty_content_returns_empty(self):
        """RawAssetBuilder returns empty string for empty list (DT3).

        Purpose: Verify that build() returns empty string when
                 extracted_content is an empty list.
        Category: Edge case
        Target: RawAssetBuilder.build(html_content, extracted_content, asset_type)
        Technique: Boundary value analysis (empty input)
        Test data: Empty list
        """
        builder = RawAssetBuilder()

        result = builder.build(None, [], "css")

        assert result == ""

    def test_single_item_returned_as_is(self):
        """RawAssetBuilder returns single item without separator (DT4).

        Purpose: Verify that build() returns a single item as-is
                 without adding any separator.
        Category: Normal case
        Target: RawAssetBuilder.build(html_content, extracted_content, asset_type)
        Technique: Boundary value analysis (single element)
        Test data: List with one item
        """
        builder = RawAssetBuilder()

        result = builder.build(None, ["single"], "css")

        assert result == "single"

    def test_ignores_html_content(self):
        """RawAssetBuilder ignores html_content parameter (DT5).

        Purpose: Verify that html_content is not used by RawAssetBuilder
                 and the result depends only on extracted_content.
        Category: Normal case
        Target: RawAssetBuilder.build(html_content, extracted_content, asset_type)
        Technique: Equivalence partitioning
        Test data: Non-None html_content with extracted_content
        """
        builder = RawAssetBuilder()

        result_with_html = builder.build("<html>content</html>", ["a{}"], "css")
        result_without_html = builder.build(None, ["a{}"], "css")

        assert result_with_html == result_without_html == "a{}"

    def test_requires_html_content_is_false(self):
        """RawAssetBuilder.requires_html_content defaults to False.

        Purpose: Verify that RawAssetBuilder does not request HTML content
                 from the pipeline.
        Category: Normal case
        Target: RawAssetBuilder.requires_html_content
        Technique: Equivalence partitioning
        Test data: N/A
        """
        builder = RawAssetBuilder()

        assert builder.requires_html_content is False


class TestTailwindCSSBuilder:
    def test_requires_html_content_is_true(self):
        """TailwindCSSBuilder.requires_html_content is True.

        Purpose: Verify that TailwindCSSBuilder declares it needs HTML
                 content for Tailwind JIT class scanning.
        Category: Normal case
        Target: TailwindCSSBuilder.requires_html_content
        Technique: Equivalence partitioning
        Test data: N/A
        """
        builder = TailwindCSSBuilder()

        assert builder.requires_html_content is True

    def test_non_css_falls_back_to_raw(self):
        """For non-CSS asset types, TailwindCSSBuilder concatenates like raw (DT6).

        Purpose: Verify that build() with asset_type="js" falls back to
                 simple concatenation without running Tailwind CLI.
        Category: Normal case
        Target: TailwindCSSBuilder.build(html_content, extracted_content, "js")
        Technique: Equivalence partitioning
        Test data: JS content with asset_type="js"
        """
        builder = TailwindCSSBuilder()

        result = builder.build(None, ["alert(1)", "alert(2)"], "js")

        assert result == "alert(1)\n\nalert(2)"

    def test_non_css_empty_returns_empty(self):
        """For non-CSS asset types with empty content, returns empty string.

        Purpose: Verify that build() with asset_type="js" and empty list
                 returns empty string.
        Category: Edge case
        Target: TailwindCSSBuilder.build(html_content, extracted_content, "js")
        Technique: Boundary value analysis
        Test data: Empty list with asset_type="js"
        """
        builder = TailwindCSSBuilder()

        result = builder.build(None, [], "js")

        assert result == ""

    def test_empty_inputs_returns_empty(self):
        """No HTML and no extracted content returns empty string (DT7).

        Purpose: Verify that build() returns empty string when both
                 html_content is None/empty and extracted_content is empty.
        Category: Edge case
        Target: TailwindCSSBuilder.build(html_content, extracted_content, "css")
        Technique: Boundary value analysis (all empty)
        Test data: None html_content and empty list
        """
        builder = TailwindCSSBuilder()

        result = builder.build(None, [], "css")

        assert result == ""

    def test_empty_html_and_empty_extracted_returns_empty(self):
        """Empty string HTML and empty extracted returns empty string.

        Purpose: Verify that build() returns empty when html_content
                 is explicitly empty string and no extracted content.
        Category: Edge case
        Target: TailwindCSSBuilder.build("", [], "css")
        Technique: Boundary value analysis
        Test data: Empty string html_content
        """
        builder = TailwindCSSBuilder()

        result = builder.build("", [], "css")

        assert result == ""

    def test_runs_tailwind_cli(self):
        """build() runs Tailwind CLI via _run_tailwind (DT8).

        Purpose: Verify that build() delegates to _run_tailwind with
                 html_content and custom CSS when asset_type is "css".
        Category: Normal case
        Target: TailwindCSSBuilder.build(html_content, extracted_content, "css")
        Technique: Statement coverage (C0)
        Test data: HTML content with Tailwind classes
        """
        builder = TailwindCSSBuilder()

        with mock.patch.object(
            builder, "_run_tailwind", return_value=".bg-red-500{background:red}"
        ) as mock_run:
            result = builder.build(
                "<div class='bg-red-500'>test</div>",
                [".custom { color: red; }"],
                "css",
            )

        assert result == ".bg-red-500{background:red}"
        mock_run.assert_called_once_with(
            "<div class='bg-red-500'>test</div>",
            ".custom { color: red; }",
        )

    def test_fallback_on_file_not_found_error(self):
        """FileNotFoundError falls back to extracted CSS (DT9).

        Purpose: Verify that when Tailwind CLI binary is not found,
                 build() falls back to returning stripped custom CSS.
        Category: Error case
        Target: TailwindCSSBuilder.build(html_content, extracted_content, "css")
        Technique: Error guessing
        Test data: FileNotFoundError from _run_tailwind
        """
        builder = TailwindCSSBuilder()

        with mock.patch.object(
            builder, "_run_tailwind", side_effect=FileNotFoundError("not found")
        ):
            result = builder.build(
                "<div>test</div>",
                [".fallback { color: blue; }"],
                "css",
            )

        assert result == ".fallback { color: blue; }"

    def test_fallback_on_subprocess_error(self):
        """SubprocessError falls back to extracted CSS.

        Purpose: Verify that when Tailwind CLI fails with SubprocessError,
                 build() returns stripped custom CSS as fallback.
        Category: Error case
        Target: TailwindCSSBuilder.build(html_content, extracted_content, "css")
        Technique: Error guessing
        Test data: SubprocessError from _run_tailwind
        """
        builder = TailwindCSSBuilder()

        with mock.patch.object(
            builder, "_run_tailwind", side_effect=subprocess.SubprocessError("failed")
        ):
            result = builder.build(
                "<div>test</div>",
                [" .fallback { color: green; } "],
                "css",
            )

        assert result == ".fallback { color: green; }"

    def test_fallback_on_os_error(self):
        """OSError falls back to extracted CSS.

        Purpose: Verify that OSError (e.g., permission denied) triggers
                 fallback to extracted CSS content.
        Category: Error case
        Target: TailwindCSSBuilder.build(html_content, extracted_content, "css")
        Technique: Error guessing
        Test data: OSError from _run_tailwind
        """
        builder = TailwindCSSBuilder()

        with mock.patch.object(
            builder, "_run_tailwind", side_effect=OSError("permission denied")
        ):
            result = builder.build(
                "<div>test</div>",
                [".fallback { color: yellow; }"],
                "css",
            )

        assert result == ".fallback { color: yellow; }"

    def test_fallback_with_no_custom_css_returns_empty(self):
        """Error fallback with no custom CSS returns empty string.

        Purpose: Verify that when CLI fails and there is no extracted
                 CSS content, fallback returns empty string.
        Category: Edge case
        Target: TailwindCSSBuilder.build(html_content, [], "css")
        Technique: Boundary value analysis
        Test data: HTML only, no extracted content, CLI failure
        """
        builder = TailwindCSSBuilder()

        with mock.patch.object(
            builder, "_run_tailwind", side_effect=FileNotFoundError("not found")
        ):
            result = builder.build("<div class='text-red'>test</div>", [], "css")

        assert result == ""


class TestTailwindGetCliPath:
    def test_cli_path_from_settings(self):
        """TAILWIND_CLI_PATH setting is used when configured.

        Purpose: Verify that _get_cli_path() returns the value from
                 TAILWIND_CLI_PATH setting when it is set.
        Category: Normal case
        Target: TailwindCSSBuilder._get_cli_path()
        Technique: Equivalence partitioning
        Test data: Configured CLI path
        """
        builder = TailwindCSSBuilder()

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value="/usr/local/bin/tailwindcss",
        ):
            result = builder._get_cli_path()

        assert result == "/usr/local/bin/tailwindcss"

    def test_cli_path_from_django_tailwind_cli(self):
        """Auto-detects CLI path from django-tailwind-cli when available.

        Purpose: Verify that _get_cli_path() uses django-tailwind-cli's
                 get_config().cli_path when TAILWIND_CLI_PATH is not set.
        Category: Normal case
        Target: TailwindCSSBuilder._get_cli_path()
        Technique: Equivalence partitioning
        Test data: django-tailwind-cli installed environment
        """
        builder = TailwindCSSBuilder()

        mock_config_obj = mock.MagicMock()
        mock_config_obj.cli_path = Path("/home/user/.cache/tailwindcss")
        mock_config_module = mock.MagicMock()
        mock_config_module.get_config.return_value = mock_config_obj

        with (
            mock.patch(
                "wagtail_asset_publisher.builders.tailwind.get_setting",
                return_value=None,
            ),
            mock.patch.dict(
                "sys.modules",
                {
                    "django_tailwind_cli": mock.MagicMock(),
                    "django_tailwind_cli.config": mock_config_module,
                },
            ),
        ):
            result = builder._get_cli_path()

        assert result == "/home/user/.cache/tailwindcss"

    def test_cli_path_fallback_on_value_error(self):
        """Falls back to 'tailwindcss' when get_config() raises ValueError.

        Purpose: Verify that _get_cli_path() catches ValueError from
                 get_config() (e.g. missing STATICFILES_DIRS) and falls
                 back to the PATH-based 'tailwindcss' command.
        Category: Error case
        Target: TailwindCSSBuilder._get_cli_path()
        Technique: Error guessing
        Test data: get_config() raising ValueError
        """
        builder = TailwindCSSBuilder()

        mock_config_module = mock.MagicMock()
        mock_config_module.get_config.side_effect = ValueError(
            "STATICFILES_DIRS is not configured"
        )

        with (
            mock.patch(
                "wagtail_asset_publisher.builders.tailwind.get_setting",
                return_value=None,
            ),
            mock.patch.dict(
                "sys.modules",
                {
                    "django_tailwind_cli": mock.MagicMock(),
                    "django_tailwind_cli.config": mock_config_module,
                },
            ),
        ):
            result = builder._get_cli_path()

        assert result == "tailwindcss"

    def test_cli_path_fallback_to_command_name(self):
        """Falls back to 'tailwindcss' command when no other option available.

        Purpose: Verify that _get_cli_path() returns 'tailwindcss' (PATH lookup)
                 when TAILWIND_CLI_PATH is None and django-tailwind-cli is not installed.
        Category: Edge case
        Target: TailwindCSSBuilder._get_cli_path()
        Technique: Error guessing
        Test data: No configuration, no django-tailwind-cli
        """
        builder = TailwindCSSBuilder()

        with (
            mock.patch(
                "wagtail_asset_publisher.builders.tailwind.get_setting",
                return_value=None,
            ),
            mock.patch.dict("sys.modules", {"django_tailwind_cli": None}),
        ):
            result = builder._get_cli_path()

        assert result == "tailwindcss"


class TestTailwindBuildInputCss:
    def test_uses_default_input_when_no_base_css(self):
        """Uses DEFAULT_TAILWIND_INPUT when TAILWIND_BASE_CSS is not set.

        Purpose: Verify that _build_input_css() uses the default Tailwind
                 import statement when no base CSS file is configured.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Equivalence partitioning
        Test data: No TAILWIND_BASE_CSS, no custom CSS, content_file=None
        """
        builder = TailwindCSSBuilder()

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value=None,
        ):
            result = builder._build_input_css("", content_file=None)

        assert result == DEFAULT_TAILWIND_INPUT

    def test_appends_custom_css_to_input(self):
        """Custom CSS is appended to the Tailwind input.

        Purpose: Verify that _build_input_css() appends custom CSS content
                 after the base Tailwind import.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Equivalence partitioning
        Test data: Custom CSS string, content_file=None
        """
        builder = TailwindCSSBuilder()

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value=None,
        ):
            result = builder._build_input_css(".custom { color: red; }", content_file=None)

        assert DEFAULT_TAILWIND_INPUT in result
        assert ".custom { color: red; }" in result

    def test_reads_base_css_file_when_configured(self):
        """Reads base CSS from file when TAILWIND_BASE_CSS is set.

        Purpose: Verify that _build_input_css() reads a file specified
                 by TAILWIND_BASE_CSS instead of using the default.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Equivalence partitioning
        Test data: Mock base CSS file, content_file=None
        """
        builder = TailwindCSSBuilder()
        base_css_content = '@import "tailwindcss";\n@layer components {}'

        with (
            mock.patch(
                "wagtail_asset_publisher.builders.tailwind.get_setting",
                return_value="/path/to/base.css",
            ),
            mock.patch.object(
                Path,
                "read_text",
                return_value=base_css_content,
            ),
        ):
            result = builder._build_input_css("", content_file=None)

        assert result == base_css_content

    def test_adds_source_directive_for_content_file(self):
        """Adds @source directive when content_file is provided.

        Purpose: Verify that _build_input_css() inserts an @source directive
                 referencing the content file path into the input CSS, enabling
                 Tailwind v4 to scan the file for utility classes.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Equivalence partitioning
        Test data: content_file=/tmp/content.html, no custom CSS
        """
        builder = TailwindCSSBuilder()
        content_file = Path("/tmp/content.html")

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value=None,
        ):
            result = builder._build_input_css("", content_file=content_file)

        assert '@source "/tmp/content.html";' in result
        assert DEFAULT_TAILWIND_INPUT in result

    def test_source_directive_with_custom_css(self):
        """Ordering: base CSS, then @source directive, then custom CSS.

        Purpose: Verify that _build_input_css() produces output in the correct
                 order: base import first, @source directive second, custom CSS
                 last, ensuring Tailwind processes layers correctly.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Statement coverage (C0)
        Test data: content_file with custom CSS
        """
        builder = TailwindCSSBuilder()
        content_file = Path("/tmp/content.html")
        custom_css = ".custom { color: red; }"

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value=None,
        ):
            result = builder._build_input_css(custom_css, content_file=content_file)

        base_pos = result.index('@import "tailwindcss"')
        source_pos = result.index('@source "/tmp/content.html"')
        custom_pos = result.index(".custom { color: red; }")
        assert base_pos < source_pos < custom_pos


class TestTailwindBuildCommand:
    def test_builds_basic_command(self):
        """Builds correct CLI command with input/output/minify flags (no --content).

        Purpose: Verify that _build_command() produces the correct Tailwind CLI
                 command arguments. In v4, --content is no longer used because
                 content scanning is handled via @source directive in input CSS.
        Category: Normal case
        Target: TailwindCSSBuilder._build_command(cli_path, input_file, output_file)
        Technique: Equivalence partitioning
        Test data: Standard path arguments
        """
        builder = TailwindCSSBuilder()
        input_f = Path("/tmp/input.css")
        output_f = Path("/tmp/output.css")

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value=None,
        ):
            result = builder._build_command("tailwindcss", input_f, output_f)

        assert result == [
            "tailwindcss",
            "--input",
            str(input_f),
            "--output",
            str(output_f),
            "--minify",
        ]

    def test_config_passed_to_cli(self):
        """TAILWIND_CONFIG adds --config flag to CLI command.

        Purpose: Verify that _build_command() appends --config when
                 TAILWIND_CONFIG setting is configured.
        Category: Normal case
        Target: TailwindCSSBuilder._build_command()
        Technique: Decision coverage (C1) - config_path branch
        Test data: TAILWIND_CONFIG=/path/to/tailwind.config.js
        """
        builder = TailwindCSSBuilder()
        input_f = Path("/tmp/input.css")
        output_f = Path("/tmp/output.css")

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value="/path/to/tailwind.config.js",
        ):
            result = builder._build_command("tailwindcss", input_f, output_f)

        assert "--config" in result
        assert "/path/to/tailwind.config.js" in result

    def test_no_config_when_setting_is_none(self):
        """No --config or --content flags when TAILWIND_CONFIG is None.

        Purpose: Verify that _build_command() does not add --config
                 when the setting is None, and never includes --content
                 (removed in v4 migration).
        Category: Normal case
        Target: TailwindCSSBuilder._build_command()
        Technique: Decision coverage (C1) - no config branch
        Test data: TAILWIND_CONFIG=None
        """
        builder = TailwindCSSBuilder()
        input_f = Path("/tmp/input.css")
        output_f = Path("/tmp/output.css")

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            return_value=None,
        ):
            result = builder._build_command("tailwindcss", input_f, output_f)

        assert "--config" not in result
        assert "--content" not in result


class TestTailwindRunTailwind:
    @mock.patch("wagtail_asset_publisher.builders.tailwind.subprocess.run")
    def test_run_tailwind_nonzero_exit_raises(self, mock_subprocess_run):
        """Non-zero exit code raises SubprocessError.

        Purpose: Verify that _run_tailwind() raises SubprocessError
                 when the Tailwind CLI exits with a non-zero code.
                 In v4, _run_tailwind passes content_file to
                 _build_input_css instead of _build_command.
        Category: Error case
        Target: TailwindCSSBuilder._run_tailwind(html_content, custom_css)
        Technique: Error guessing
        Test data: subprocess.run returning exit code 1
        """
        builder = TailwindCSSBuilder()

        mock_result = mock.Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: something went wrong"
        mock_subprocess_run.return_value = mock_result

        with (
            mock.patch.object(builder, "_get_cli_path", return_value="tailwindcss"),
            mock.patch.object(
                builder,
                "_build_input_css",
                return_value='@import "tailwindcss";\n@source "/tmp/content.html";',
            ),
            mock.patch("wagtail_asset_publisher.builders.tailwind.Path.write_text"),
            pytest.raises(subprocess.SubprocessError, match="Tailwind CLI failed"),
        ):
            builder._run_tailwind("<div>test</div>", ".custom{}")
