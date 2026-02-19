"""Configuration and settings for wagtail-asset-publisher."""

from typing import Any

from django.conf import settings

DEFAULTS: dict[str, Any] = {
    # Builder settings
    "CSS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
    "JS_BUILDER": "wagtail_asset_publisher.builders.raw.RawAssetBuilder",
    # Storage settings
    "STORAGE_BACKEND": "wagtail_asset_publisher.storage.django_storage.DjangoStorageBackend",
    # Path prefix for assets
    "CSS_PREFIX": "page-assets/css/",
    "JS_PREFIX": "page-assets/js/",
    # Tailwind settings
    "TAILWIND_CLI_PATH": None,
    "TAILWIND_CONFIG": None,
    "TAILWIND_BASE_CSS": None,
    # Asset optimization
    "OBFUSCATE_JS": False,
    "MINIFY_CSS": True,
    "TERSER_PATH": None,
    "TERSER_OPTIONS": ["-c", "-m"],
    # Asset generation
    "HASH_LENGTH": 8,
    # HTML minification
    "MINIFY_HTML": True,
    # Tailwind preview CDN URL
    "TAILWIND_CDN_URL": "https://unpkg.com/@tailwindcss/browser@4",
}


_UNSET = object()


def get_setting(key: str, default: Any = _UNSET) -> Any:
    """Get a setting from WAGTAIL_ASSET_PUBLISHER dict or return default."""
    user_settings: dict[str, Any] = getattr(settings, "WAGTAIL_ASSET_PUBLISHER", {})
    fallback = DEFAULTS.get(key) if default is _UNSET else default
    return user_settings.get(key, fallback)
