"""Raw asset builder that concatenates extracted content as-is."""

from __future__ import annotations

from .base import BaseAssetBuilder


class RawAssetBuilder(BaseAssetBuilder):
    """Simple builder that concatenates extracted inline content.

    CSS: joins all extracted <style> contents with newlines.
    JS: joins all extracted <script> contents with newlines.
    """

    def build(
        self,
        html_content: str | None,
        extracted_content: list[str],
        asset_type: str,
    ) -> str:
        if not extracted_content:
            return ""
        return "\n\n".join(extracted_content)
