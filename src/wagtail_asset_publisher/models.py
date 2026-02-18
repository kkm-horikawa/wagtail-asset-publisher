"""Models for wagtail-asset-publisher."""

from __future__ import annotations

from django.db import models


class AssetType(models.TextChoices):
    CSS = "css", "CSS"
    JS = "js", "JavaScript"


class PublishedAsset(models.Model):
    """Stores published asset URLs and extraction metadata.

    Separate from the Page model — no mixin, no migration on user tables.
    Cleaned up automatically via CASCADE on page delete.
    """

    page = models.ForeignKey(
        "wagtailcore.Page",
        on_delete=models.CASCADE,
        related_name="published_assets",
        db_index=True,
    )
    asset_type = models.CharField(max_length=3, choices=AssetType.choices)
    url = models.URLField(max_length=2048)
    content_hashes = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("page", "asset_type")]

    def __str__(self) -> str:
        return f"PublishedAsset({self.page_id}, {self.asset_type})"
