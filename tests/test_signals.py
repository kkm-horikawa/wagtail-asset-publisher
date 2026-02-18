"""Tests for wagtail-asset-publisher v2 signal handlers.

Verifies that the ``published`` signal handler correctly dispatches
to ``build_page_assets`` for pages and handles snippet references
via ``ReferenceIndex``.
"""

from __future__ import annotations

import logging
from unittest import mock

from wagtail_asset_publisher.signals import (
    _handle_page_published,
    _handle_snippet_published,
    on_published,
)


class TestOnPublishedDispatch:
    @mock.patch("wagtail_asset_publisher.signals._handle_snippet_published")
    @mock.patch("wagtail_asset_publisher.signals._handle_page_published")
    def test_page_published_triggers_build(self, mock_handle_page, mock_handle_snippet):
        """Publishing a Page dispatches to _handle_page_published with page.specific.

        Purpose: Verify that on_published() calls _handle_page_published(page.specific)
                 when the instance is a Page.
        Category: Normal case
        Target: on_published(sender, instance)
        Technique: Equivalence partitioning
        Test data: Mock Wagtail Page instance with pk=42
        """
        from wagtail.models import Page

        page_instance = mock.MagicMock(spec=Page)
        page_instance.pk = 42
        page_instance.title = "Test Page"
        specific_page = mock.Mock()
        page_instance.specific = specific_page

        on_published(sender=type(page_instance), instance=page_instance)

        mock_handle_page.assert_called_once_with(specific_page)
        mock_handle_snippet.assert_not_called()

    @mock.patch("wagtail_asset_publisher.signals._handle_snippet_published")
    @mock.patch("wagtail_asset_publisher.signals._handle_page_published")
    def test_snippet_published_dispatches_to_snippet_handler(
        self, mock_handle_page, mock_handle_snippet
    ):
        """Publishing a non-Page instance dispatches to _handle_snippet_published.

        Purpose: Verify that on_published() calls _handle_snippet_published
                 for non-Page instances (e.g., DraftStateMixin snippets).
        Category: Normal case
        Target: on_published(sender, instance)
        Technique: Equivalence partitioning
        Test data: Plain mock object (not a Page)
        """
        snippet = mock.Mock(spec=[])
        snippet.pk = 10

        on_published(sender=type(snippet), instance=snippet)

        mock_handle_snippet.assert_called_once_with(snippet)
        mock_handle_page.assert_not_called()


class TestHandlePagePublished:
    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    def test_calls_build_page_assets(self, mock_build):
        """_handle_page_published calls build_page_assets with the page.

        Purpose: Verify that _handle_page_published delegates to
                 build_page_assets with the page argument.
        Category: Normal case
        Target: _handle_page_published(page)
        Technique: Equivalence partitioning
        Test data: Mock page with pk=42
        """
        page = mock.Mock()
        page.pk = 42
        page.title = "Test Page"

        _handle_page_published(page)

        mock_build.assert_called_once_with(page)


class TestHandleSnippetPublished:
    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    def test_snippet_published_finds_referencing_pages(self, mock_build):
        """Publishing a snippet rebuilds all referencing pages via ReferenceIndex.

        Purpose: Verify that _handle_snippet_published finds pages referencing
                 the snippet via ReferenceIndex and calls build_page_assets for each.
        Category: Normal case
        Target: _handle_snippet_published(instance)
        Technique: Equivalence partitioning
        Test data: Snippet referenced by 2 pages (pk=1 and pk=2)
        """
        from wagtail.models import Page

        snippet = mock.Mock()
        snippet.pk = 10

        ref1 = mock.Mock()
        ref1.base_content_type.model_class.return_value = Page
        ref1.object_id = "1"

        ref2 = mock.Mock()
        ref2.base_content_type.model_class.return_value = Page
        ref2.object_id = "2"

        page1 = mock.Mock(pk=1)
        page2 = mock.Mock(pk=2)
        mock_page_qs = mock.MagicMock()
        mock_page_qs.specific.return_value = [page1, page2]

        with (
            mock.patch(
                "wagtail.models.ReferenceIndex",
            ) as mock_ref_index,
            mock.patch.object(
                Page.objects,
                "filter",
                return_value=mock_page_qs,
            ),
        ):
            mock_ref_index.get_references_to.return_value = [ref1, ref2]
            _handle_snippet_published(snippet)

        assert mock_build.call_count == 2
        mock_build.assert_any_call(page1)
        mock_build.assert_any_call(page2)

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    def test_snippet_with_no_page_references_does_nothing(self, mock_build):
        """Snippet referenced only by non-Page models triggers no rebuild.

        Purpose: Verify that when ReferenceIndex returns references only to
                 non-Page models, build_page_assets is not called.
        Category: Edge case
        Target: _handle_snippet_published(instance)
        Technique: Boundary value analysis (zero page references)
        Test data: Snippet referenced only by a non-Page model
        """
        from wagtail.models import Page

        snippet = mock.Mock()
        snippet.pk = 10

        ref_non_page = mock.Mock()
        non_page_model = type("SomeSnippet", (), {})
        ref_non_page.base_content_type.model_class.return_value = non_page_model
        ref_non_page.object_id = "99"

        with (
            mock.patch(
                "wagtail.models.ReferenceIndex",
            ) as mock_ref_index,
            mock.patch.object(
                Page.objects,
                "filter",
            ) as mock_filter,
        ):
            mock_ref_index.get_references_to.return_value = [ref_non_page]
            _handle_snippet_published(snippet)

        mock_build.assert_not_called()
        mock_filter.assert_not_called()

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    def test_snippet_with_empty_references_does_nothing(self, mock_build):
        """Snippet with zero references triggers no rebuild.

        Purpose: Verify that when ReferenceIndex returns an empty result set,
                 build_page_assets is not called.
        Category: Edge case
        Target: _handle_snippet_published(instance)
        Technique: Boundary value analysis (empty reference set)
        Test data: Snippet with no references at all
        """
        from wagtail.models import Page

        snippet = mock.Mock()
        snippet.pk = 10

        with (
            mock.patch(
                "wagtail.models.ReferenceIndex",
            ) as mock_ref_index,
            mock.patch.object(
                Page.objects,
                "filter",
            ) as mock_filter,
        ):
            mock_ref_index.get_references_to.return_value = []
            _handle_snippet_published(snippet)

        mock_build.assert_not_called()
        mock_filter.assert_not_called()

    def test_reference_index_import_error_handled(self, caplog):
        """If ReferenceIndex import fails, a warning is logged and no error raised.

        Purpose: Verify that ImportError from ReferenceIndex import is
                 caught and logged as a warning without propagating.
        Category: Error case
        Target: _handle_snippet_published(instance)
        Technique: Error guessing
        Test data: Snippet with ReferenceIndex unavailable
        """
        snippet = mock.Mock()
        snippet.pk = 10

        original_import = (
            __builtins__["__import__"]
            if isinstance(__builtins__, dict)
            else __builtins__.__import__
        )

        def patched_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "wagtail.models" and fromlist and "ReferenceIndex" in fromlist:
                raise ImportError("No ReferenceIndex available")
            return original_import(name, globals, locals, fromlist, level)

        with (
            caplog.at_level(logging.WARNING, logger="wagtail_asset_publisher.signals"),
            mock.patch("builtins.__import__", side_effect=patched_import),
        ):
            _handle_snippet_published(snippet)

        assert "ReferenceIndex not available" in caplog.text

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    def test_model_class_returns_none_skipped(self, mock_build):
        """References where model_class() returns None are skipped.

        Purpose: Verify that references with model_class returning None
                 (e.g., deleted content types) are gracefully skipped.
        Category: Edge case
        Target: _handle_snippet_published(instance)
        Technique: Error guessing
        Test data: Reference with model_class() returning None
        """
        snippet = mock.Mock()
        snippet.pk = 10

        ref_with_none = mock.Mock()
        ref_with_none.base_content_type.model_class.return_value = None
        ref_with_none.object_id = "1"

        with mock.patch(
            "wagtail.models.ReferenceIndex",
        ) as mock_ref_index:
            mock_ref_index.get_references_to.return_value = [ref_with_none]
            _handle_snippet_published(snippet)

        mock_build.assert_not_called()

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    def test_duplicate_page_ids_deduplicated(self, mock_build):
        """Duplicate page IDs from multiple references are deduplicated.

        Purpose: Verify that when multiple references point to the same page,
                 the page is only rebuilt once (via set-based deduplication).
        Category: Edge case
        Target: _handle_snippet_published(instance)
        Technique: Equivalence partitioning
        Test data: Two references to the same page (pk=1)
        """
        from wagtail.models import Page

        snippet = mock.Mock()
        snippet.pk = 10

        ref1 = mock.Mock()
        ref1.base_content_type.model_class.return_value = Page
        ref1.object_id = "1"

        ref2 = mock.Mock()
        ref2.base_content_type.model_class.return_value = Page
        ref2.object_id = "1"

        page1 = mock.Mock(pk=1)
        mock_page_qs = mock.MagicMock()
        mock_page_qs.specific.return_value = [page1]

        with (
            mock.patch(
                "wagtail.models.ReferenceIndex",
            ) as mock_ref_index,
            mock.patch.object(
                Page.objects,
                "filter",
                return_value=mock_page_qs,
            ) as mock_filter,
        ):
            mock_ref_index.get_references_to.return_value = [ref1, ref2]
            _handle_snippet_published(snippet)

        mock_filter.assert_called_once_with(pk__in=[1])
        mock_build.assert_called_once_with(page1)


class TestSignalRegistration:
    def test_dispatch_uid_prevents_double_registration(self):
        """The published signal uses dispatch_uid to prevent duplicate handlers.

        Purpose: Verify that the signal connection uses dispatch_uid so
                 the handler cannot be registered multiple times even if
                 the module is re-imported.
        Category: Normal case
        Target: Module-level signal connection
        Technique: Error guessing
        Test data: N/A - inspects signal registration
        """
        from wagtail.signals import published

        # Django 6.0 changed receivers from 2-tuples to 4-tuples.
        # Use _live_receivers to get resolved receiver functions.
        receivers = published._live_receivers(sender=None)
        handler_count = sum(1 for r in receivers if r is on_published)

        assert handler_count <= 1, (
            f"on_published registered {handler_count} times; "
            "dispatch_uid should prevent duplicates"
        )

    def test_dispatch_uid_value(self):
        """The dispatch_uid matches the expected convention.

        Purpose: Verify that the dispatch_uid string used for signal
                 registration is 'wagtail_asset_publisher.on_published'.
        Category: Normal case
        Target: Module-level signal connection
        Technique: Equivalence partitioning
        Test data: N/A
        """
        from wagtail.signals import published

        uid_str = "wagtail_asset_publisher.on_published"

        # Django 6.0 changed receivers from 2-tuples to 4-tuples.
        # Extract the first element (lookup key) from each entry.
        uid_keys = [entry[0] for entry in published.receivers]
        found = any(uid_str in str(key) for key in uid_keys)

        assert found, (
            f"dispatch_uid '{uid_str}' not found in signal receivers. "
            f"Found keys: {uid_keys}"
        )
