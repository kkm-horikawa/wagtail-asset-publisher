"""Tailwind CSS preview support via CDN script injection.

Injects the Tailwind CSS browser runtime into page previews so editors
can see Tailwind utility classes rendered correctly before publishing.

Only active when the CSS builder is set to TailwindCSSBuilder.
The CDN script is NEVER injected in published pages -- only in previews.
"""

from __future__ import annotations

from .conf import get_setting


def is_tailwind_builder() -> bool:
    """Check if the configured CSS builder is the Tailwind builder."""
    builder_path = get_setting("CSS_BUILDER")
    return "tailwind" in builder_path.lower()


def get_tailwind_cdn_script() -> str:
    """Return the Tailwind CDN play script tag for preview injection."""
    cdn_url = get_setting("TAILWIND_CDN_URL")
    return f'<script src="{cdn_url}"></script>'
