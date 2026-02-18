"""Tests for wagtail_hooks module."""

from django.http import HttpRequest

from wagtail_asset_publisher.wagtail_hooks import set_page_on_request


class TestSetPageOnRequest:
    """Test before_serve_page hook."""

    def test_sets_wagtailpage_attribute(self):
        """Hook sets request.wagtailpage to the served page."""
        request = HttpRequest()
        page = object()

        result = set_page_on_request(page, request, args=(), kwargs={})

        assert request.wagtailpage is page
        assert result is None

    def test_overwrites_existing_attribute(self):
        """Hook overwrites any pre-existing wagtailpage attribute."""
        request = HttpRequest()
        request.wagtailpage = "old"
        page = object()

        set_page_on_request(page, request, args=(), kwargs={})

        assert request.wagtailpage is page
