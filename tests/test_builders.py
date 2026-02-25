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
    SAFE_PLUGIN_NAME_RE,
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
            result = builder._build_input_css(
                ".custom { color: red; }", content_file=None
            )

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

    def test_no_plugins_injected_when_not_configured(self):
        """No @plugin directives when TAILWIND_PLUGINS is empty (default).

        Purpose: Verify that _build_input_css() does not inject any @plugin
                 directives when TAILWIND_PLUGINS is an empty list.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Equivalence partitioning
        Test data: TAILWIND_PLUGINS=[], TAILWIND_BASE_CSS=None
        """
        builder = TailwindCSSBuilder()

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": [],
            }
            return settings.get(key)

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            side_effect=mock_get_setting,
        ):
            result = builder._build_input_css("", content_file=None)

        assert "@plugin" not in result

    def test_single_plugin_injected(self):
        """Single @plugin directive injected for one configured plugin.

        Purpose: Verify that _build_input_css() injects a single @plugin
                 directive when TAILWIND_PLUGINS contains one entry.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Equivalence partitioning
        Test data: TAILWIND_PLUGINS=["@tailwindcss/typography"]
        """
        builder = TailwindCSSBuilder()

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": ["@tailwindcss/typography"],
            }
            return settings.get(key)

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            side_effect=mock_get_setting,
        ):
            result = builder._build_input_css("", content_file=None)

        assert '@plugin "@tailwindcss/typography";' in result

    def test_multiple_plugins_injected_in_order(self):
        """Multiple @plugin directives injected in configured order.

        Purpose: Verify that _build_input_css() injects @plugin directives
                 for all entries in TAILWIND_PLUGINS, preserving order.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Equivalence partitioning
        Test data: TAILWIND_PLUGINS with typography and forms
        """
        builder = TailwindCSSBuilder()
        plugins = ["@tailwindcss/typography", "@tailwindcss/forms"]

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": plugins,
            }
            return settings.get(key)

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            side_effect=mock_get_setting,
        ):
            result = builder._build_input_css("", content_file=None)

        typography_pos = result.index('@plugin "@tailwindcss/typography"')
        forms_pos = result.index('@plugin "@tailwindcss/forms"')
        assert typography_pos < forms_pos

    def test_plugins_ignored_when_base_css_set(self):
        """TAILWIND_PLUGINS is ignored when TAILWIND_BASE_CSS is set.

        Purpose: Verify that _build_input_css() does not inject @plugin
                 directives when the user provides a custom base CSS file,
                 since they have full control over the input CSS.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Decision coverage (C1)
        Test data: TAILWIND_BASE_CSS set, TAILWIND_PLUGINS non-empty
        """
        builder = TailwindCSSBuilder()
        base_css_content = '@import "tailwindcss";\n@layer components {}'

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": "/path/to/base.css",
                "TAILWIND_PLUGINS": ["@tailwindcss/typography"],
            }
            return settings.get(key)

        with (
            mock.patch(
                "wagtail_asset_publisher.builders.tailwind.get_setting",
                side_effect=mock_get_setting,
            ),
            mock.patch.object(
                Path,
                "read_text",
                return_value=base_css_content,
            ),
        ):
            result = builder._build_input_css("", content_file=None)

        assert "@plugin" not in result

    def test_plugin_directive_ordering(self):
        """Ordering: @import < @plugin directives < @source < custom CSS.

        Purpose: Verify that _build_input_css() produces output in the correct
                 order: @import first, @plugin directives second, @source
                 third, custom CSS last.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Statement coverage (C0)
        Test data: Plugin + content_file + custom CSS
        """
        builder = TailwindCSSBuilder()
        content_file = Path("/tmp/content.html")
        custom_css = ".custom { color: red; }"

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": ["@tailwindcss/typography"],
            }
            return settings.get(key)

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            side_effect=mock_get_setting,
        ):
            result = builder._build_input_css(custom_css, content_file=content_file)

        import_pos = result.index('@import "tailwindcss"')
        plugin_pos = result.index('@plugin "@tailwindcss/typography"')
        source_pos = result.index('@source "/tmp/content.html"')
        custom_pos = result.index(".custom { color: red; }")
        assert import_pos < plugin_pos < source_pos < custom_pos

    def test_plugin_directives_have_semicolons(self):
        """Each @plugin directive ends with a semicolon.

        Purpose: Verify that every @plugin line has a trailing semicolon,
                 since missing semicolons cause cryptic Tailwind parser errors.
        Category: Normal case
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Error guessing (missing semicolons)
        Test data: Multiple plugins
        """
        builder = TailwindCSSBuilder()
        plugins = ["@tailwindcss/typography", "@tailwindcss/forms"]

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": plugins,
            }
            return settings.get(key)

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            side_effect=mock_get_setting,
        ):
            result = builder._build_input_css("", content_file=None)

        plugin_lines = [
            line for line in result.splitlines() if line.startswith("@plugin")
        ]
        assert len(plugin_lines) == len(plugins)
        for line in plugin_lines:
            assert line.endswith(";")


class TestValidatePlugins:
    """Tests for TailwindCSSBuilder._validate_plugins().

    Validates that TAILWIND_PLUGINS setting values are safe before
    injecting them into generated CSS.
    """

    def test_none_returns_empty_list(self):
        """None value returns empty list without warning.

        Purpose: Verify that _validate_plugins(None) returns an empty list
                 (the common case when the setting is not configured).
        Category: Normal case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Boundary value analysis (None input)
        Test data: None
        """
        builder = TailwindCSSBuilder()

        result = builder._validate_plugins(None)

        assert result == []

    def test_valid_list_passes_through(self):
        """A list of valid plugin names is returned as-is.

        Purpose: Verify that _validate_plugins() passes through a valid list
                 of plugin names without modification.
        Category: Normal case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Equivalence partitioning
        Test data: List with two valid scoped package names
        """
        builder = TailwindCSSBuilder()
        plugins = ["@tailwindcss/typography", "@tailwindcss/forms"]

        result = builder._validate_plugins(plugins)

        assert result == plugins

    def test_string_value_returns_empty_and_warns(self, caplog):
        """A string value (common misconfiguration) is rejected with warning.

        Purpose: Verify that _validate_plugins() returns an empty list and
                 logs a warning when the value is a string instead of a list.
                 This prevents iterating over characters of the string.
        Category: Error case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Error guessing (common misconfiguration)
        Test data: "tailwindcss/typography" (string instead of list)
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins("tailwindcss/typography")

        assert result == []
        assert "TAILWIND_PLUGINS must be a list" in caplog.text
        assert "str" in caplog.text

    def test_tuple_value_returns_empty_and_warns(self, caplog):
        """A tuple value is rejected with warning.

        Purpose: Verify that _validate_plugins() rejects non-list iterables
                 (tuple) to enforce strict type checking.
        Category: Error case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Error guessing (wrong iterable type)
        Test data: Tuple of plugin names
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins(("@tailwindcss/typography",))

        assert result == []
        assert "TAILWIND_PLUGINS must be a list" in caplog.text
        assert "tuple" in caplog.text

    def test_integer_value_returns_empty_and_warns(self, caplog):
        """An integer value is rejected with warning.

        Purpose: Verify that _validate_plugins() rejects non-iterable types.
        Category: Error case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Error guessing (wrong type)
        Test data: Integer 42
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins(42)

        assert result == []
        assert "TAILWIND_PLUGINS must be a list" in caplog.text

    def test_plugin_name_with_double_quote_skipped(self, caplog):
        """Plugin name containing a double-quote is skipped with warning.

        Purpose: Verify that a plugin name with an embedded double-quote
                 is rejected, preventing CSS injection via @plugin "bad"name";
        Category: Security case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Error guessing (CSS injection via quote)
        Test data: ['bad"name']
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins(['bad"name'])

        assert result == []
        assert "Invalid plugin name skipped" in caplog.text

    def test_plugin_name_with_semicolon_skipped(self, caplog):
        """Plugin name containing a semicolon is skipped with warning.

        Purpose: Verify that a plugin name with a semicolon is rejected,
                 preventing premature CSS statement termination.
        Category: Security case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Error guessing (CSS injection via semicolon)
        Test data: ['bad;name']
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins(["bad;name"])

        assert result == []
        assert "Invalid plugin name skipped" in caplog.text

    def test_plugin_name_with_space_skipped(self, caplog):
        """Plugin name containing a space is skipped with warning.

        Purpose: Verify that a plugin name with spaces is rejected.
        Category: Error case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Error guessing (whitespace in name)
        Test data: ['bad name']
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins(["bad name"])

        assert result == []
        assert "Invalid plugin name skipped" in caplog.text

    def test_non_string_entry_skipped(self, caplog):
        """Non-string entries in the list are skipped with warning.

        Purpose: Verify that non-string items (e.g. integers) within
                 the plugin list are skipped individually.
        Category: Error case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Error guessing (mixed types in list)
        Test data: [123, "@tailwindcss/typography"]
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins([123, "@tailwindcss/typography"])

        assert result == ["@tailwindcss/typography"]
        assert "Invalid plugin name skipped" in caplog.text

    def test_mixed_valid_and_invalid_entries(self, caplog):
        """Valid entries pass through while invalid ones are skipped.

        Purpose: Verify that _validate_plugins() filters out only the
                 invalid entries while keeping valid ones in order.
        Category: Normal case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Equivalence partitioning (mixed input)
        Test data: Mix of valid and invalid plugin names
        """
        builder = TailwindCSSBuilder()
        plugins = [
            "@tailwindcss/typography",
            'bad"quote',
            "@tailwindcss/forms",
        ]

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins(plugins)

        assert result == ["@tailwindcss/typography", "@tailwindcss/forms"]
        assert "Invalid plugin name skipped" in caplog.text

    def test_empty_string_entry_skipped(self, caplog):
        """Empty string plugin name is skipped with warning.

        Purpose: Verify that an empty string entry is rejected because
                 it does not match the safe plugin name pattern.
        Category: Edge case
        Target: TailwindCSSBuilder._validate_plugins(raw_value)
        Technique: Boundary value analysis (empty string)
        Test data: [""]
        """
        builder = TailwindCSSBuilder()

        with caplog.at_level("WARNING"):
            result = builder._validate_plugins([""])

        assert result == []
        assert "Invalid plugin name skipped" in caplog.text

    @pytest.mark.parametrize(
        "name",
        [
            "@tailwindcss/typography",
            "@tailwindcss/forms",
            "tailwindcss-animate",
            "daisyui",
            "@myorg/my-plugin",
            "plugin_with_underscore",
            "plugin.with.dots",
        ],
    )
    def test_safe_plugin_name_pattern_accepts_valid_names(self, name):
        """SAFE_PLUGIN_NAME_RE accepts typical Tailwind plugin names.

        Purpose: Verify that the regex pattern matches common valid
                 plugin name formats (scoped packages, hyphens, dots, etc.).
        Category: Normal case
        Target: SAFE_PLUGIN_NAME_RE
        Technique: Equivalence partitioning (valid inputs)
        Test data: Various valid plugin name formats
        """
        assert SAFE_PLUGIN_NAME_RE.match(name)

    @pytest.mark.parametrize(
        "name",
        [
            'bad"quote',
            "bad;semicolon",
            "bad name",
            "bad\nline",
            "",
            "bad{brace",
            "bad}brace",
        ],
    )
    def test_safe_plugin_name_pattern_rejects_invalid_names(self, name):
        """SAFE_PLUGIN_NAME_RE rejects names with unsafe characters.

        Purpose: Verify that the regex pattern rejects plugin names
                 containing characters that could cause CSS parse errors.
        Category: Security case
        Target: SAFE_PLUGIN_NAME_RE
        Technique: Error guessing (unsafe characters)
        Test data: Various invalid plugin name formats
        """
        assert not SAFE_PLUGIN_NAME_RE.match(name)


class TestBuildInputCssPluginValidation:
    """Integration tests: _build_input_css with invalid TAILWIND_PLUGINS values."""

    def test_string_plugins_produces_no_directives(self, caplog):
        """String TAILWIND_PLUGINS produces no @plugin directives.

        Purpose: Verify that _build_input_css() does not produce broken
                 per-character @plugin directives when TAILWIND_PLUGINS is
                 a string instead of a list.
        Category: Error case (integration)
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Error guessing (common misconfiguration)
        Test data: TAILWIND_PLUGINS="tailwindcss/typography" (string)
        """
        builder = TailwindCSSBuilder()

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": "tailwindcss/typography",
            }
            return settings.get(key)

        with (
            caplog.at_level("WARNING"),
            mock.patch(
                "wagtail_asset_publisher.builders.tailwind.get_setting",
                side_effect=mock_get_setting,
            ),
        ):
            result = builder._build_input_css("", content_file=None)

        assert "@plugin" not in result
        assert result == DEFAULT_TAILWIND_INPUT
        assert "TAILWIND_PLUGINS must be a list" in caplog.text

    def test_plugin_with_quote_skipped_in_output(self, caplog):
        """Plugin name with double-quote is excluded from generated CSS.

        Purpose: Verify that _build_input_css() does not produce a broken
                 @plugin directive when a plugin name contains a double-quote.
        Category: Security case (integration)
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Error guessing (CSS injection)
        Test data: TAILWIND_PLUGINS=['bad"name', '@tailwindcss/forms']
        """
        builder = TailwindCSSBuilder()

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": ['bad"name', "@tailwindcss/forms"],
            }
            return settings.get(key)

        with (
            caplog.at_level("WARNING"),
            mock.patch(
                "wagtail_asset_publisher.builders.tailwind.get_setting",
                side_effect=mock_get_setting,
            ),
        ):
            result = builder._build_input_css("", content_file=None)

        assert '@plugin "@tailwindcss/forms";' in result
        assert "bad" not in result
        assert "Invalid plugin name skipped" in caplog.text

    def test_none_plugins_produces_no_directives(self):
        """None TAILWIND_PLUGINS produces no @plugin directives.

        Purpose: Verify that _build_input_css() gracefully handles
                 TAILWIND_PLUGINS=None (the default when not configured).
        Category: Normal case (integration)
        Target: TailwindCSSBuilder._build_input_css(custom_css, content_file)
        Technique: Boundary value analysis (None)
        Test data: TAILWIND_PLUGINS=None
        """
        builder = TailwindCSSBuilder()

        def mock_get_setting(key):
            settings = {
                "TAILWIND_BASE_CSS": None,
                "TAILWIND_PLUGINS": None,
            }
            return settings.get(key)

        with mock.patch(
            "wagtail_asset_publisher.builders.tailwind.get_setting",
            side_effect=mock_get_setting,
        ):
            result = builder._build_input_css("", content_file=None)

        assert "@plugin" not in result
        assert result == DEFAULT_TAILWIND_INPUT


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
