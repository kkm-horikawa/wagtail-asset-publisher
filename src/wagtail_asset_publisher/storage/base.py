from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAssetStorage(ABC):
    """Abstract base class for asset storage backends.

    Storage backends are responsible for persisting generated CSS/JS files
    and returning URLs for accessing them.
    """

    @abstractmethod
    def save(self, path: str, content: str) -> str:
        """Save asset content to storage.

        Args:
            path: The storage path (e.g., "page-assets/css/123-a1b2c3d4.css")
            content: The asset content to save

        Returns:
            The full URL to access the saved asset
        """
        ...

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete an asset from storage.

        Args:
            path: The storage path to delete
        """
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if an asset exists in storage.

        Args:
            path: The storage path to check

        Returns:
            True if the asset exists
        """
        ...
