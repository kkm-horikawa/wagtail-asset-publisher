"""Wagtail hooks for asset publisher integration."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from wagtail import hooks
from wagtail.models import Page


@hooks.register("before_serve_page")
def set_page_on_request(
    page: Page,
    request: HttpRequest,
    args: list[Any],
    kwargs: dict[str, Any],
) -> None:
    """Expose the served page to the asset publisher middleware.

    The AssetPublisherMiddleware needs to know which Wagtail page is being
    served in order to look up its published assets.  Wagtail does not set
    the page on the request by default, so this hook bridges page serving
    with middleware processing.
    """
    request.wagtailpage = page  # type: ignore[attr-defined]
