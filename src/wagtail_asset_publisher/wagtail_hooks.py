"""Wagtail hooks for asset publisher integration."""

from wagtail import hooks


@hooks.register("before_serve_page")
def set_page_on_request(page, request, args, kwargs):
    """Expose the served page to the asset publisher middleware.

    The AssetPublisherMiddleware needs to know which Wagtail page is being
    served in order to look up its published assets.  Wagtail does not set
    the page on the request by default, so this hook bridges page serving
    with middleware processing.
    """
    request.wagtailpage = page
