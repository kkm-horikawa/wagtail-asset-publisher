from __future__ import annotations

from pathlib import Path

from django.conf import settings

from .base import BaseAssetStorage


class LocalFileStorage(BaseAssetStorage):
    """Local filesystem storage for development.

    Saves assets under STATIC_ROOT and returns STATIC_URL-based URLs.
    Useful for local development without S3/cloud storage.
    """

    def _get_full_path(self, path: str) -> Path:
        static_root: str | None = getattr(settings, "STATIC_ROOT", None)
        if not static_root:
            raise ValueError("STATIC_ROOT must be configured for LocalFileStorage")
        full_path = (Path(static_root) / path).resolve()
        root_resolved = Path(static_root).resolve()
        if not full_path.is_relative_to(root_resolved):
            raise ValueError(
                f"Path traversal detected: {path!r} resolves outside STATIC_ROOT"
            )
        return full_path

    def _get_url(self, path: str) -> str:
        static_url: str = getattr(settings, "STATIC_URL", "/static/")
        return f"{static_url.rstrip('/')}/{path}"

    def save(self, path: str, content: str) -> str:
        full_path = self._get_full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return self._get_url(path)

    def delete(self, path: str) -> None:
        full_path = self._get_full_path(path)
        if full_path.exists():
            full_path.unlink()

    def exists(self, path: str) -> bool:
        return self._get_full_path(path).exists()
