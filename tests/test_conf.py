"""Tests for wagtail_asset_publisher.conf module.

## Decision table: DT-GET-SETTING

| ID  | User setting | default arg | DEFAULTS key | Expected return        |
|-----|-------------|-------------|-------------|------------------------|
| DT1 | present     | _UNSET      | present     | user setting value     |
| DT2 | present     | explicit    | present     | user setting value     |
| DT3 | absent      | _UNSET      | present     | DEFAULTS value         |
| DT4 | absent      | explicit    | present     | explicit default value |
| DT5 | absent      | None        | present     | None (not DEFAULTS)    |
| DT6 | absent      | _UNSET      | absent      | None                   |
"""

from unittest import mock

import pytest

from wagtail_asset_publisher.conf import DEFAULTS, get_setting


class TestGetSettingDecisionTable:
    """Decision table coverage for get_setting() priority logic."""

    @pytest.mark.parametrize(
        "user_settings,key,kwargs,expected",
        [
            pytest.param(
                {"CSS_BUILDER": "custom.Builder"},
                "CSS_BUILDER",
                {},
                "custom.Builder",
                id="DT1-user-setting-wins-over-defaults",
            ),
            pytest.param(
                {"CSS_BUILDER": "custom.Builder"},
                "CSS_BUILDER",
                {"default": "fallback.Builder"},
                "custom.Builder",
                id="DT2-user-setting-wins-over-explicit-default",
            ),
            pytest.param(
                {},
                "CSS_BUILDER",
                {},
                DEFAULTS["CSS_BUILDER"],
                id="DT3-no-user-setting-returns-defaults-value",
            ),
            pytest.param(
                {},
                "CSS_BUILDER",
                {"default": "fallback.Builder"},
                "fallback.Builder",
                id="DT4-explicit-default-overrides-defaults",
            ),
            pytest.param(
                {},
                "CSS_BUILDER",
                {"default": None},
                None,
                id="DT5-explicit-none-default-returns-none",
            ),
            pytest.param(
                {},
                "NONEXISTENT_KEY",
                {},
                None,
                id="DT6-unknown-key-returns-none",
            ),
        ],
    )
    def test_get_setting(self, user_settings, key, kwargs, expected):
        """DT-GET-SETTING: verify priority of user settings > default arg > DEFAULTS.

        Purpose: Verify get_setting() returns the correct value based on the
            priority chain: user_settings > explicit default > DEFAULTS > None.
        Category: Normal case
        Target: get_setting(key, default)
        Technique: Decision table (DT-GET-SETTING)
        Test data: All 6 combinations from decision table
        """
        with mock.patch("wagtail_asset_publisher.conf.settings") as mock_settings:
            mock_settings.WAGTAIL_ASSET_PUBLISHER = user_settings

            result = get_setting(key, **kwargs)

        assert result == expected


class TestGetSettingEdgeCases:
    """Edge cases for get_setting()."""

    def test_get_setting_without_wagtail_asset_publisher_attr(self):
        """Settings object without WAGTAIL_ASSET_PUBLISHER returns DEFAULTS value.

        Purpose: Verify graceful handling when WAGTAIL_ASSET_PUBLISHER is not
            defined in Django settings (getattr returns empty dict).
        Category: Edge case
        Target: get_setting(key)
        Technique: Error guessing (missing attribute)
        Test data: Mock settings without WAGTAIL_ASSET_PUBLISHER attribute
        """
        mock_settings = mock.Mock(spec=[])

        with mock.patch("wagtail_asset_publisher.conf.settings", mock_settings):
            result = get_setting("CSS_BUILDER")

        assert result == DEFAULTS["CSS_BUILDER"]

    def test_get_setting_user_value_is_falsy_but_present(self):
        """User setting with falsy value (empty string) is still returned.

        Purpose: Verify that falsy but present user values are not confused
            with missing values.
        Category: Edge case
        Target: get_setting(key)
        Technique: Boundary value analysis (falsy but present)
        Test data: Empty string as user setting
        """
        with mock.patch("wagtail_asset_publisher.conf.settings") as mock_settings:
            mock_settings.WAGTAIL_ASSET_PUBLISHER = {"CSS_PREFIX": ""}

            result = get_setting("CSS_PREFIX")

        assert result == ""

    def test_get_setting_user_value_is_zero(self):
        """User setting with zero value is returned (not treated as missing).

        Purpose: Verify that numeric zero user values are respected.
        Category: Edge case
        Target: get_setting(key)
        Technique: Boundary value analysis (zero value)
        Test data: 0 as user setting for HASH_LENGTH
        """
        with mock.patch("wagtail_asset_publisher.conf.settings") as mock_settings:
            mock_settings.WAGTAIL_ASSET_PUBLISHER = {"HASH_LENGTH": 0}

            result = get_setting("HASH_LENGTH")

        assert result == 0


class TestDefaultValues:
    """Tests for specific DEFAULTS entries relevant to v2 architecture."""

    def test_tailwind_cdn_url_default(self):
        """TAILWIND_CDN_URL defaults to the unpkg Tailwind browser URL.

        Purpose: Verify the default CDN URL for Tailwind preview injection.
        Category: Normal case
        Target: DEFAULTS["TAILWIND_CDN_URL"]
        Technique: Equivalence partitioning
        Test data: DEFAULTS dict value
        """
        assert (
            DEFAULTS["TAILWIND_CDN_URL"] == "https://unpkg.com/@tailwindcss/browser@4"
        )

    def test_hash_length_default(self):
        """HASH_LENGTH defaults to 8.

        Purpose: Verify the default hash truncation length.
        Category: Normal case
        Target: DEFAULTS["HASH_LENGTH"]
        Technique: Equivalence partitioning
        Test data: DEFAULTS dict value
        """
        assert DEFAULTS["HASH_LENGTH"] == 8

    def test_defaults_contains_v2_required_keys(self):
        """DEFAULTS contains all keys required by v2 architecture.

        Purpose: Verify that DEFAULTS has all necessary configuration keys
            for the v2 extraction-based pipeline.
        Category: Normal case
        Target: DEFAULTS dict
        Technique: Equivalence partitioning
        Test data: Set of required key names
        """
        required_keys = {
            "CSS_BUILDER",
            "JS_BUILDER",
            "STORAGE_BACKEND",
            "CSS_PREFIX",
            "JS_PREFIX",
            "HASH_LENGTH",
            "TAILWIND_CDN_URL",
            "TAILWIND_CLI_PATH",
            "TAILWIND_CONFIG",
            "TAILWIND_BASE_CSS",
        }

        assert required_keys.issubset(set(DEFAULTS.keys()))
