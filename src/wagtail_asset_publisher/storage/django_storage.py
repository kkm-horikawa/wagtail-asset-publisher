from __future__ import annotations

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .base import BaseAssetStorage


class DjangoStorageBackend(BaseAssetStorage):
    """Storage backend using Django's default file storage.

    Works with any Django storage backend (S3 via django-storages,
    local filesystem, GCS, Azure, etc.)
    """

    def save(self, path: str, content: str) -> str:
        if default_storage.exists(path):
            default_storage.delete(path)

        saved_path = default_storage.save(path, ContentFile(content.encode("utf-8")))
        return default_storage.url(saved_path)

    def delete(self, path: str) -> None:
        if default_storage.exists(path):
            default_storage.delete(path)

    def exists(self, path: str) -> bool:
        return default_storage.exists(path)
