"""Tests for wagtail-asset-publisher v2 rebuild_assets management command.

Verifies the command correctly resolves pages, handles --all / --page-ids
/ --dry-run flags, and provides proper output messaging.
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from wagtail_asset_publisher.management.commands.rebuild_assets import Command


class TestRebuildAssetsCommand:
    def _run_command(self, **options):
        """Helper to run the command with captured output."""
        cmd = Command()
        cmd.stdout = StringIO()
        cmd.stderr = StringIO()
        cmd.style = mock.Mock()
        cmd.style.SUCCESS = lambda x: x
        defaults = {
            "page_ids": None,
            "rebuild_all": False,
            "dry_run": False,
        }
        defaults.update(options)
        cmd.handle(**defaults)
        return cmd.stdout.getvalue(), cmd.stderr.getvalue()

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    @mock.patch("wagtail_asset_publisher.management.commands.rebuild_assets.Page")
    def test_rebuild_specific_pages(self, mock_page_cls, mock_build):
        """--page-ids 1 2 rebuilds only those specific pages.

        Purpose: Verify that passing --page-ids filters to only
                 the specified live pages and rebuilds each.
        Category: Normal case
        Target: Command.handle(page_ids=[1, 2])
        Technique: Equivalence partitioning
        Test data: Two specific page IDs
        """
        page1 = mock.Mock(pk=1, title="Page 1")
        page2 = mock.Mock(pk=2, title="Page 2")
        mock_page_cls.objects.filter.return_value.specific.return_value = [page1, page2]

        stdout, stderr = self._run_command(page_ids=[1, 2])

        mock_page_cls.objects.filter.assert_called_once_with(pk__in=[1, 2], live=True)
        assert mock_build.call_count == 2
        mock_build.assert_any_call(page1)
        mock_build.assert_any_call(page2)
        assert "Rebuilt: 2" in stdout

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    @mock.patch("wagtail_asset_publisher.management.commands.rebuild_assets.Page")
    def test_rebuild_all_live_pages(self, mock_page_cls, mock_build):
        """--all rebuilds assets for ALL live pages.

        Purpose: Verify that --all flag triggers rebuild for every
                 live page regardless of existing assets.
        Category: Normal case
        Target: Command.handle(rebuild_all=True)
        Technique: Equivalence partitioning
        Test data: Three live pages
        """
        pages = [mock.Mock(pk=i, title=f"Page {i}") for i in range(1, 4)]
        mock_page_cls.objects.filter.return_value.specific.return_value = pages

        stdout, _ = self._run_command(rebuild_all=True)

        mock_page_cls.objects.filter.assert_called_once_with(live=True)
        assert mock_build.call_count == 3
        assert "Rebuilt: 3" in stdout

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    @mock.patch("wagtail_asset_publisher.management.commands.rebuild_assets.Page")
    @mock.patch(
        "wagtail_asset_publisher.models.PublishedAsset",
    )
    def test_rebuild_existing_assets_only(
        self, mock_published_asset, mock_page_cls, mock_build
    ):
        """Default mode rebuilds only pages with existing PublishedAssets.

        Purpose: Verify that without --all or --page-ids, the command
                 only rebuilds pages that already have published assets.
        Category: Normal case
        Target: Command.handle() (default mode)
        Technique: Equivalence partitioning
        Test data: Two pages with existing assets
        """
        mock_published_asset.objects.values_list.return_value.distinct.return_value = [
            1,
            2,
        ]

        page1 = mock.Mock(pk=1, title="Page 1")
        page2 = mock.Mock(pk=2, title="Page 2")
        mock_page_cls.objects.filter.return_value.specific.return_value = [page1, page2]

        stdout, _ = self._run_command()

        assert mock_build.call_count == 2
        assert "Rebuilt: 2" in stdout

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    @mock.patch("wagtail_asset_publisher.management.commands.rebuild_assets.Page")
    def test_dry_run_no_actual_build(self, mock_page_cls, mock_build):
        """--dry-run shows what would be rebuilt without calling build_page_assets.

        Purpose: Verify that --dry-run prevents actual build execution
                 while still reporting what would be rebuilt.
        Category: Normal case
        Target: Command.handle(dry_run=True)
        Technique: Equivalence partitioning
        Test data: Two pages in dry-run mode
        """
        pages = [mock.Mock(pk=i, title=f"Page {i}") for i in range(1, 3)]
        mock_page_cls.objects.filter.return_value.specific.return_value = pages

        stdout, _ = self._run_command(page_ids=[1, 2], dry_run=True)

        mock_build.assert_not_called()
        assert "[DRY RUN]" in stdout
        assert "Rebuilt: 2" in stdout

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    @mock.patch("wagtail_asset_publisher.management.commands.rebuild_assets.Page")
    def test_error_handling_continues(self, mock_page_cls, mock_build):
        """Build error for one page doesn't stop processing others.

        Purpose: Verify that an exception during build_page_assets for
                 one page is caught, logged, and processing continues.
        Category: Error case
        Target: Command.handle()
        Technique: Error guessing
        Test data: Three pages where the second raises an exception
        """
        page1 = mock.Mock(pk=1, title="Page 1")
        page2 = mock.Mock(pk=2, title="Page 2 (error)")
        page3 = mock.Mock(pk=3, title="Page 3")
        mock_page_cls.objects.filter.return_value.specific.return_value = [
            page1,
            page2,
            page3,
        ]

        mock_build.side_effect = [None, RuntimeError("Build failed"), None]

        stdout, stderr = self._run_command(page_ids=[1, 2, 3])

        assert mock_build.call_count == 3
        assert "Rebuilt: 2" in stdout
        assert "Errors: 1" in stdout
        assert "ERROR" in stderr

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    @mock.patch("wagtail_asset_publisher.management.commands.rebuild_assets.Page")
    def test_output_messages_correct(self, mock_page_cls, mock_build):
        """Correct stdout messages for rebuilt/error counts.

        Purpose: Verify that the command outputs the correct summary
                 with rebuilt and error counts.
        Category: Normal case
        Target: Command.handle()
        Technique: Statement coverage (C0)
        Test data: Two pages, both successful
        """
        pages = [mock.Mock(pk=i, title=f"Page {i}") for i in range(1, 3)]
        mock_page_cls.objects.filter.return_value.specific.return_value = pages

        stdout, stderr = self._run_command(page_ids=[1, 2])

        assert "Rebuilding assets for 2 page(s)" in stdout
        assert "Rebuilt: 1 -" in stdout or "Rebuilt:" in stdout
        assert "Done. Rebuilt: 2, Errors: 0" in stdout
        assert stderr == ""

    @mock.patch("wagtail_asset_publisher.utils.build_page_assets")
    @mock.patch("wagtail_asset_publisher.management.commands.rebuild_assets.Page")
    def test_empty_page_set(self, mock_page_cls, mock_build):
        """Command handles empty page set gracefully.

        Purpose: Verify that the command completes successfully when
                 no pages match the criteria.
        Category: Edge case
        Target: Command.handle()
        Technique: Boundary value analysis (zero pages)
        Test data: No matching pages
        """
        mock_page_cls.objects.filter.return_value.specific.return_value = []

        stdout, _ = self._run_command(page_ids=[999])

        mock_build.assert_not_called()
        assert "Rebuilding assets for 0 page(s)" in stdout
        assert "Rebuilt: 0, Errors: 0" in stdout


class TestResolvePages:
    def test_page_ids_filters_by_ids_and_live(self):
        """_resolve_pages with page_ids filters by pk__in and live=True.

        Purpose: Verify that _resolve_pages applies both pk and live filters
                 when page_ids are provided.
        Category: Normal case
        Target: Command._resolve_pages(page_ids, rebuild_all)
        Technique: Equivalence partitioning
        Test data: Page IDs [1, 2]
        """
        cmd = Command()

        with mock.patch(
            "wagtail_asset_publisher.management.commands.rebuild_assets.Page"
        ) as mock_page_cls:
            mock_page_cls.objects.filter.return_value.specific.return_value = []

            cmd._resolve_pages([1, 2], False)

        mock_page_cls.objects.filter.assert_called_once_with(pk__in=[1, 2], live=True)

    def test_rebuild_all_filters_live_only(self):
        """_resolve_pages with rebuild_all=True filters only by live=True.

        Purpose: Verify that _resolve_pages with rebuild_all flag fetches
                 all live pages without further filtering.
        Category: Normal case
        Target: Command._resolve_pages(None, True)
        Technique: Equivalence partitioning
        Test data: No page_ids, rebuild_all=True
        """
        cmd = Command()

        with mock.patch(
            "wagtail_asset_publisher.management.commands.rebuild_assets.Page"
        ) as mock_page_cls:
            mock_page_cls.objects.filter.return_value.specific.return_value = []

            cmd._resolve_pages(None, True)

        mock_page_cls.objects.filter.assert_called_once_with(live=True)

    @mock.patch("wagtail_asset_publisher.models.PublishedAsset")
    def test_default_mode_uses_published_asset_ids(self, mock_published_asset):
        """Default _resolve_pages uses PublishedAsset page IDs.

        Purpose: Verify that _resolve_pages without page_ids or rebuild_all
                 queries PublishedAsset for distinct page IDs.
        Category: Normal case
        Target: Command._resolve_pages(None, False)
        Technique: Equivalence partitioning
        Test data: PublishedAsset records for pages 1 and 2
        """
        cmd = Command()
        mock_published_asset.objects.values_list.return_value.distinct.return_value = [
            1,
            2,
        ]

        with mock.patch(
            "wagtail_asset_publisher.management.commands.rebuild_assets.Page"
        ) as mock_page_cls:
            mock_page_cls.objects.filter.return_value.specific.return_value = []

            cmd._resolve_pages(None, False)

        mock_page_cls.objects.filter.assert_called_once_with(pk__in=[1, 2], live=True)
