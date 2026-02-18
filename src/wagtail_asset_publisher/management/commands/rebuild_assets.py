"""Management command to rebuild published assets."""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandParser
from wagtail.models import Page

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Rebuild published CSS/JS assets for Wagtail pages."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--page-ids",
            nargs="+",
            type=int,
            help="Specific page IDs to rebuild. If omitted, rebuilds all pages with published assets.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="rebuild_all",
            help="Rebuild assets for ALL live pages (not just those with existing assets).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be rebuilt without actually building.",
        )

    def handle(self, **options: object) -> None:
        from wagtail_asset_publisher.utils import build_page_assets

        page_ids = options.get("page_ids")
        rebuild_all = options.get("rebuild_all")
        dry_run = options.get("dry_run")

        pages = self._resolve_pages(page_ids, rebuild_all)  # type: ignore[arg-type]
        self.stdout.write(f"Rebuilding assets for {len(pages)} page(s)...")

        rebuilt = 0
        errors = 0
        for page in pages:
            if dry_run:
                self.stdout.write(
                    f"  [DRY RUN] Would rebuild: {page.pk} - {page.title}"
                )
                rebuilt += 1
                continue

            try:
                build_page_assets(page)
                self.stdout.write(f"  Rebuilt: {page.pk} - {page.title}")
                rebuilt += 1
            except Exception:
                logger.exception("Failed to rebuild assets for page %d", page.pk)
                self.stderr.write(f"  ERROR: {page.pk} - {page.title}")
                errors += 1

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(f"\n{prefix}Done. Rebuilt: {rebuilt}, Errors: {errors}")
        )

    def _resolve_pages(
        self, page_ids: list[int] | None, rebuild_all: bool | None
    ) -> list[Page]:
        """Resolve the set of pages to rebuild based on CLI arguments."""
        from wagtail_asset_publisher.models import PublishedAsset

        if page_ids:
            return list(Page.objects.filter(pk__in=page_ids, live=True).specific())

        if rebuild_all:
            return list(Page.objects.filter(live=True).specific())

        # Default: only pages that already have published assets
        asset_page_ids = PublishedAsset.objects.values_list(
            "page_id", flat=True
        ).distinct()
        return list(Page.objects.filter(pk__in=asset_page_ids, live=True).specific())
