"""Tests for storage backends."""

from unittest import mock

import pytest

from wagtail_asset_publisher.storage.django_storage import DjangoStorageBackend
from wagtail_asset_publisher.storage.local import LocalFileStorage


class TestDjangoStorageBackendSave:
    def test_save_new_file(self):
        """Save a new file and return its URL.

        Purpose: Verify that DjangoStorageBackend.save() saves a new file
            and returns its URL.
        Category: Normal case
        Target: DjangoStorageBackend.save(path, content)
        Technique: Equivalence partitioning
        Test data: CSS content saved to a non-existent path
        """
        backend = DjangoStorageBackend()
        path = "page-assets/css/42-abcd1234.css"
        content = "body { color: red; }"

        with mock.patch(
            "wagtail_asset_publisher.storage.django_storage.default_storage"
        ) as mock_storage:
            mock_storage.exists.return_value = False
            mock_storage.save.return_value = path
            mock_storage.url.return_value = f"/media/{path}"

            result = backend.save(path, content)

        assert result == f"/media/{path}"
        mock_storage.save.assert_called_once()
        mock_storage.delete.assert_not_called()

    def test_save_overwrites_existing_file(self):
        """Delete existing file before saving.

        Purpose: Verify that DjangoStorageBackend.save() deletes the existing
            file before saving a new one.
        Category: Normal case
        Target: DjangoStorageBackend.save(path, content)
        Technique: Condition coverage
        Test data: CSS content saved to an existing path
        """
        backend = DjangoStorageBackend()
        path = "page-assets/css/42-abcd1234.css"

        with mock.patch(
            "wagtail_asset_publisher.storage.django_storage.default_storage"
        ) as mock_storage:
            mock_storage.exists.return_value = True
            mock_storage.save.return_value = path
            mock_storage.url.return_value = f"/media/{path}"

            backend.save(path, "body{}")

        mock_storage.delete.assert_called_once_with(path)
        mock_storage.save.assert_called_once()


class TestDjangoStorageBackendDelete:
    def test_delete_existing_file(self):
        """Delete an existing file.

        Purpose: Verify that DjangoStorageBackend.delete() successfully
            deletes an existing file.
        Category: Normal case
        Target: DjangoStorageBackend.delete(path)
        Technique: Equivalence partitioning
        Test data: Existing path
        """
        backend = DjangoStorageBackend()
        path = "page-assets/css/42-abcd1234.css"

        with mock.patch(
            "wagtail_asset_publisher.storage.django_storage.default_storage"
        ) as mock_storage:
            mock_storage.exists.return_value = True

            backend.delete(path)

        mock_storage.delete.assert_called_once_with(path)

    def test_delete_nonexistent_file_does_nothing(self):
        """Deleting a non-existent file does nothing.

        Purpose: Verify that DjangoStorageBackend.delete() does not call
            delete for a non-existent file.
        Category: Edge case
        Target: DjangoStorageBackend.delete(path)
        Technique: Condition coverage
        Test data: Non-existent path
        """
        backend = DjangoStorageBackend()
        path = "page-assets/css/nonexistent.css"

        with mock.patch(
            "wagtail_asset_publisher.storage.django_storage.default_storage"
        ) as mock_storage:
            mock_storage.exists.return_value = False

            backend.delete(path)

        mock_storage.delete.assert_not_called()


class TestDjangoStorageBackendExists:
    def test_exists_returns_true_for_existing_file(self):
        """Return True for an existing file.

        Purpose: Verify that DjangoStorageBackend.exists() returns True
            for an existing path.
        Category: Normal case
        Target: DjangoStorageBackend.exists(path)
        Technique: Equivalence partitioning
        Test data: Existing path
        """
        backend = DjangoStorageBackend()

        with mock.patch(
            "wagtail_asset_publisher.storage.django_storage.default_storage"
        ) as mock_storage:
            mock_storage.exists.return_value = True

            result = backend.exists("page-assets/css/42.css")

        assert result is True

    def test_exists_returns_false_for_nonexistent_file(self):
        """Return False for a non-existent file.

        Purpose: Verify that DjangoStorageBackend.exists() returns False
            for a non-existent path.
        Category: Normal case
        Target: DjangoStorageBackend.exists(path)
        Technique: Equivalence partitioning
        Test data: Non-existent path
        """
        backend = DjangoStorageBackend()

        with mock.patch(
            "wagtail_asset_publisher.storage.django_storage.default_storage"
        ) as mock_storage:
            mock_storage.exists.return_value = False

            result = backend.exists("page-assets/css/nonexistent.css")

        assert result is False


class TestLocalFileStorageSave:
    def test_save_creates_file_and_returns_url(self, tmp_path):
        """Write file and return STATIC_URL-based URL.

        Purpose: Verify that LocalFileStorage.save() writes a file under
            STATIC_ROOT and returns a STATIC_URL-based URL.
        Category: Normal case
        Target: LocalFileStorage.save(path, content)
        Technique: Equivalence partitioning
        Test data: CSS content saved to a temporary directory
        """
        backend = LocalFileStorage()
        path = "page-assets/css/42-abcd1234.css"
        content = "body { color: red; }"

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)
            mock_settings.STATIC_URL = "/static/"

            result = backend.save(path, content)

        assert result == "/static/page-assets/css/42-abcd1234.css"
        saved_file = tmp_path / "page-assets" / "css" / "42-abcd1234.css"
        assert saved_file.exists()
        assert saved_file.read_text(encoding="utf-8") == content

    def test_save_creates_parent_directories(self, tmp_path):
        """Automatically create parent directories when they do not exist.

        Purpose: Verify that LocalFileStorage.save() automatically creates
            parent directories and writes the file.
        Category: Normal case
        Target: LocalFileStorage.save(path, content)
        Technique: Error guessing
        Test data: Deeply nested path
        """
        backend = LocalFileStorage()
        path = "deep/nested/path/file.css"

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)
            mock_settings.STATIC_URL = "/static/"

            backend.save(path, "content")

        assert (tmp_path / "deep" / "nested" / "path" / "file.css").exists()


class TestLocalFileStorageDelete:
    def test_delete_existing_file(self, tmp_path):
        """Delete an existing file.

        Purpose: Verify that LocalFileStorage.delete() successfully
            deletes an existing file.
        Category: Normal case
        Target: LocalFileStorage.delete(path)
        Technique: Equivalence partitioning
        Test data: File created in a temporary directory
        """
        backend = LocalFileStorage()
        path = "page-assets/css/42.css"
        full_path = tmp_path / "page-assets" / "css" / "42.css"
        full_path.parent.mkdir(parents=True)
        full_path.write_text("body{}", encoding="utf-8")

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)

            backend.delete(path)

        assert not full_path.exists()

    def test_delete_nonexistent_file_does_nothing(self, tmp_path):
        """Deleting a non-existent file does nothing (no exception).

        Purpose: Verify that LocalFileStorage.delete() does not raise
            an exception for a non-existent file.
        Category: Edge case
        Target: LocalFileStorage.delete(path)
        Technique: Error guessing
        Test data: Non-existent path
        """
        backend = LocalFileStorage()

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)

            backend.delete("nonexistent/file.css")


class TestLocalFileStorageExists:
    def test_exists_returns_true(self, tmp_path):
        """Return True for an existing file.

        Purpose: Verify that LocalFileStorage.exists() returns True
            for an existing path.
        Category: Normal case
        Target: LocalFileStorage.exists(path)
        Technique: Equivalence partitioning
        Test data: File created in a temporary directory
        """
        backend = LocalFileStorage()
        path = "page-assets/css/42.css"
        full_path = tmp_path / "page-assets" / "css" / "42.css"
        full_path.parent.mkdir(parents=True)
        full_path.write_text("body{}", encoding="utf-8")

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)

            result = backend.exists(path)

        assert result is True

    def test_exists_returns_false(self, tmp_path):
        """Return False for a non-existent file.

        Purpose: Verify that LocalFileStorage.exists() returns False
            for a non-existent path.
        Category: Normal case
        Target: LocalFileStorage.exists(path)
        Technique: Equivalence partitioning
        Test data: Non-existent path
        """
        backend = LocalFileStorage()

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_ROOT = str(tmp_path)

            result = backend.exists("nonexistent.css")

        assert result is False


class TestLocalFileStorageStaticRootValidation:
    def test_raises_value_error_without_static_root(self):
        """Raise ValueError when STATIC_ROOT is not configured.

        Purpose: Verify that LocalFileStorage._get_full_path() raises
            ValueError when STATIC_ROOT is not set.
        Category: Error case
        Target: LocalFileStorage._get_full_path(path)
        Technique: Error guessing
        Test data: STATIC_ROOT=None
        """
        backend = LocalFileStorage()

        with (
            mock.patch(
                "wagtail_asset_publisher.storage.local.settings"
            ) as mock_settings,
            pytest.raises(ValueError, match="STATIC_ROOT must be configured"),
        ):
            mock_settings.STATIC_ROOT = None
            backend._get_full_path("test.css")

    def test_get_url_with_trailing_slash(self):
        """Ensure STATIC_URL trailing slash does not cause duplicate slashes.

        Purpose: Verify that _get_url() normalizes the trailing slash in
            STATIC_URL and generates a correct URL.
        Category: Edge case
        Target: LocalFileStorage._get_url(path)
        Technique: Boundary value analysis
        Test data: STATIC_URL with trailing slash
        """
        backend = LocalFileStorage()

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_URL = "/static/"

            result = backend._get_url("page-assets/css/42.css")

        assert result == "/static/page-assets/css/42.css"

    def test_get_url_without_trailing_slash(self):
        """Return correct URL even when STATIC_URL has no trailing slash.

        Purpose: Verify that _get_url() generates a correct URL even when
            STATIC_URL does not end with a trailing slash.
        Category: Edge case
        Target: LocalFileStorage._get_url(path)
        Technique: Boundary value analysis
        Test data: STATIC_URL without trailing slash
        """
        backend = LocalFileStorage()

        with mock.patch(
            "wagtail_asset_publisher.storage.local.settings"
        ) as mock_settings:
            mock_settings.STATIC_URL = "/static"

            result = backend._get_url("page-assets/css/42.css")

        assert result == "/static/page-assets/css/42.css"
