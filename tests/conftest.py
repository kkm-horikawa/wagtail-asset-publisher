"""Pytest fixtures for wagtail-asset-publisher v2 tests."""

from unittest import mock

import pytest


@pytest.fixture
def sample_html_with_style():
    """HTML content with inline <style> tag."""
    return "<div><style>body { color: red; }</style><p>Hello</p></div>"


@pytest.fixture
def sample_html_with_script():
    """HTML content with inline <script> tag."""
    return '<div><script>console.log("hello");</script><p>Hello</p></div>'


@pytest.fixture
def sample_html_with_both():
    """HTML content with both <style> and <script> tags."""
    return (
        "<div>"
        "<style>.hero { color: red; }</style>"
        '<script>alert("hi");</script>'
        "<p>Hello</p>"
        "</div>"
    )


@pytest.fixture
def sample_html_with_no_extract():
    """HTML content with data-no-extract attribute."""
    return (
        "<div>"
        "<style data-no-extract>.critical { display: block; }</style>"
        "<style>.hero { color: red; }</style>"
        "</div>"
    )


@pytest.fixture
def sample_html_with_external_script():
    """HTML content with external script (src attribute)."""
    return (
        "<div>"
        '<script src="https://example.com/lib.js"></script>'
        '<script>console.log("inline");</script>'
        "</div>"
    )


@pytest.fixture
def mock_storage():
    """Mock storage backend."""
    storage = mock.Mock()
    storage.save.return_value = (
        "https://cdn.example.com/page-assets/css/42-abcd1234.css"
    )
    storage.exists.return_value = False
    return storage
