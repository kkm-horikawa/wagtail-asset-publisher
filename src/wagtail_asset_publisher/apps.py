"""Django app configuration for wagtail-asset-publisher."""

from django.apps import AppConfig


class WagtailAssetPublisherConfig(AppConfig):
    name = "wagtail_asset_publisher"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Wagtail Asset Publisher"

    def ready(self) -> None:
        from . import signals  # noqa: F401 — register signal handlers
