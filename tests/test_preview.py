"""Tests for wagtail_asset_publisher.preview module.

Covers is_tailwind_builder() and get_tailwind_cdn_script() functions
used for Tailwind CDN injection in page preview mode.
"""

from unittest import mock

import pytest

from wagtail_asset_publisher.preview import get_tailwind_cdn_script, is_tailwind_builder


class TestIsTailwindBuilder:
    """Tests for is_tailwind_builder() CSS builder detection."""

    @pytest.mark.parametrize(
        "builder_path,expected",
        [
            pytest.param(
                "wagtail_asset_publisher.builders.tailwind.TailwindCSSBuilder",
                True,
                id="standard-tailwind-builder",
            ),
            pytest.param(
                "myapp.builders.CustomTailwindBuilder",
                True,
                id="custom-tailwind-builder-in-name",
            ),
            pytest.param(
                "wagtail_asset_publisher.builders.TAILWIND.UpperCaseBuilder",
                True,
                id="case-insensitive-tailwind",
            ),
        ],
    )
    def test_is_tailwind_builder_true(self, builder_path, expected):
        """Returns True when CSS_BUILDER path contains 'tailwind' (case-insensitive).

        Purpose: Verify that various Tailwind builder paths are correctly
            identified, enabling CDN injection in preview mode.
        Category: Normal case
        Target: is_tailwind_builder()
        Technique: Equivalence partitioning (paths containing 'tailwind')
        Test data: Builder paths with 'tailwind' in various positions/cases
        """
        with mock.patch(
            "wagtail_asset_publisher.preview.get_setting", return_value=builder_path
        ):
            result = is_tailwind_builder()

        assert result is expected

    @pytest.mark.parametrize(
        "builder_path,expected",
        [
            pytest.param(
                "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
                False,
                id="raw-builder",
            ),
            pytest.param(
                "myapp.builders.SassBuilder",
                False,
                id="sass-builder",
            ),
            pytest.param(
                "myapp.builders.PostCSSBuilder",
                False,
                id="postcss-builder",
            ),
        ],
    )
    def test_is_tailwind_builder_false(self, builder_path, expected):
        """Returns False when CSS_BUILDER path does not contain 'tailwind'.

        Purpose: Verify that non-Tailwind builder paths are correctly
            rejected, preventing CDN injection for non-Tailwind setups.
        Category: Normal case
        Target: is_tailwind_builder()
        Technique: Equivalence partitioning (paths without 'tailwind')
        Test data: Various non-Tailwind builder paths
        """
        with mock.patch(
            "wagtail_asset_publisher.preview.get_setting", return_value=builder_path
        ):
            result = is_tailwind_builder()

        assert result is expected


class TestGetTailwindCdnScript:
    """Tests for get_tailwind_cdn_script() script tag generation."""

    def test_get_tailwind_cdn_script_default_url(self):
        """Returns correct <script> tag with default CDN URL.

        Purpose: Verify that the default Tailwind CDN URL is used when
            no custom URL is configured.
        Category: Normal case
        Target: get_tailwind_cdn_script()
        Technique: Equivalence partitioning (default config)
        Test data: Default TAILWIND_CDN_URL
        """
        default_url = "https://unpkg.com/@tailwindcss/browser@4"

        with mock.patch(
            "wagtail_asset_publisher.preview.get_setting", return_value=default_url
        ):
            result = get_tailwind_cdn_script()

        assert result == f'<script src="{default_url}"></script>'

    def test_get_tailwind_cdn_script_custom_url(self):
        """Returns correct <script> tag with custom CDN URL.

        Purpose: Verify that a user-configured TAILWIND_CDN_URL is used
            in the generated script tag.
        Category: Normal case
        Target: get_tailwind_cdn_script()
        Technique: Equivalence partitioning (custom config)
        Test data: Custom CDN URL
        """
        custom_url = "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"

        with mock.patch(
            "wagtail_asset_publisher.preview.get_setting", return_value=custom_url
        ):
            result = get_tailwind_cdn_script()

        assert result == f'<script src="{custom_url}"></script>'

    def test_get_tailwind_cdn_script_format(self):
        """Script tag has correct HTML structure.

        Purpose: Verify the script tag format matches what browsers expect
            for external script loading.
        Category: Normal case
        Target: get_tailwind_cdn_script()
        Technique: Equivalence partitioning
        Test data: Any URL
        """
        with mock.patch(
            "wagtail_asset_publisher.preview.get_setting",
            return_value="https://example.com/tw.js",
        ):
            result = get_tailwind_cdn_script()

        assert result.startswith("<script src=")
        assert result.endswith("></script>")
        assert '"https://example.com/tw.js"' in result
