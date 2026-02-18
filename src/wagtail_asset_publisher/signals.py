"""Signal handlers for wagtail-asset-publisher.

Listens to Wagtail's ``published`` signal which fires for both Page and
DraftStateMixin snippets (e.g., ReusableBlock). When a snippet is published,
finds all pages referencing it via ReferenceIndex and rebuilds their assets.
"""

from __future__ import annotations

import logging
from typing import Any

from wagtail.models import Page
from wagtail.signals import published

logger = logging.getLogger(__name__)


def on_published(sender: type, instance: Any, **kwargs: Any) -> None:
    """Handle publish events for pages and snippets."""
    if isinstance(instance, Page):
        _handle_page_published(instance.specific)
    else:
        _handle_snippet_published(instance)


def _handle_page_published(page: Page) -> None:
    """Build assets for a directly published page."""
    from .utils import build_page_assets

    logger.info("Building assets for page %d: %s", page.pk, page.title)
    build_page_assets(page)


def _handle_snippet_published(instance: Any) -> None:
    """Find pages referencing this snippet and rebuild their assets."""
    from .utils import build_page_assets

    try:
        from wagtail.models import ReferenceIndex
    except ImportError:
        logger.warning(
            "ReferenceIndex not available. Cannot rebuild pages "
            "referencing %s (pk=%s).",
            type(instance).__name__,
            instance.pk,
        )
        return

    refs = ReferenceIndex.get_references_to(instance)
    page_ids: set[int] = set()
    for ref in refs:
        model_class = ref.base_content_type.model_class()
        if model_class and issubclass(model_class, Page):
            page_ids.add(int(ref.object_id))

    if not page_ids:
        return

    rebuild_ids = sorted(page_ids)

    pages = Page.objects.filter(pk__in=rebuild_ids).specific()
    for page in pages:
        logger.info(
            "Rebuilding assets for page %d (referenced by %s pk=%s)",
            page.pk,
            type(instance).__name__,
            instance.pk,
        )
        build_page_assets(page)


published.connect(on_published, dispatch_uid="wagtail_asset_publisher.on_published")
