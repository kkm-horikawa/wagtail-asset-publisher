"""Base class for asset builders."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAssetBuilder(ABC):
    """Abstract base class for asset builders.

    Builders receive extracted content and produce a single built output string.
    """

    requires_html_content: bool = False
    """Whether this builder needs the full page HTML (e.g., for Tailwind scanning)."""

    @abstractmethod
    def build(
        self,
        html_content: str | None,
        extracted_content: list[str],
        asset_type: str,
    ) -> str:
        """Build assets from extracted content.

        Args:
            html_content: Full page HTML (only provided if requires_html_content is True).
            extracted_content: List of extracted inline content strings.
            asset_type: "css" or "js".

        Returns:
            Built asset content as a string, or empty string if nothing to build.
        """
        ...
