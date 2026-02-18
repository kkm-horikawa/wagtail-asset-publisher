"""Tailwind CSS JIT builder."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from ..conf import get_setting
from .base import BaseAssetBuilder

logger = logging.getLogger(__name__)

TAILWIND_CLI_TIMEOUT_SECONDS = 30
DEFAULT_TAILWIND_INPUT = '@import "tailwindcss";\n'


class TailwindCSSBuilder(BaseAssetBuilder):
    """Builder that generates CSS using Tailwind CLI JIT compilation.

    Scans the page's rendered HTML for Tailwind utility classes
    and generates only the required CSS. Also includes any extracted
    inline <style> content.

    Requirements:
        - Tailwind CSS CLI (standalone binary or via django-tailwind-cli)
    """

    requires_html_content: bool = True

    def build(
        self,
        html_content: str | None,
        extracted_content: list[str],
        asset_type: str,
    ) -> str:
        if asset_type != "css":
            if not extracted_content:
                return ""
            return "\n\n".join(extracted_content)

        custom_css = "\n\n".join(extracted_content) if extracted_content else ""

        if not html_content and not custom_css:
            return ""

        try:
            return self._run_tailwind(html_content or "", custom_css)
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logger.error("Tailwind CSS build failed: %s", e)
            return custom_css.strip() if custom_css else ""

    def _get_cli_path(self) -> str:
        """Resolve the Tailwind CLI binary path.

        Resolution order:
        1. ``TAILWIND_CLI_PATH`` in ``WAGTAIL_ASSET_PUBLISHER`` settings
        2. ``django-tailwind-cli`` package (if installed and configured)
        3. ``tailwindcss`` on PATH (fallback)
        """
        configured: str | None = get_setting("TAILWIND_CLI_PATH")
        if configured:
            return configured

        try:
            from django_tailwind_cli.config import get_config  # type: ignore[import-not-found]  # noqa: I001

            return str(get_config().cli_path)
        except (ImportError, ValueError):
            pass

        return "tailwindcss"

    def _build_input_css(self, custom_css: str) -> str:
        """Build the Tailwind input CSS combining base and custom styles."""
        base_css_path: str | None = get_setting("TAILWIND_BASE_CSS")
        if base_css_path:
            input_css = Path(base_css_path).read_text(encoding="utf-8")
        else:
            input_css = DEFAULT_TAILWIND_INPUT

        if custom_css:
            input_css += f"\n{custom_css}\n"

        return input_css

    def _build_command(
        self,
        cli_path: str,
        input_file: Path,
        output_file: Path,
        content_file: Path,
    ) -> list[str]:
        """Build the Tailwind CLI command arguments."""
        cmd = [
            cli_path,
            "--input",
            str(input_file),
            "--output",
            str(output_file),
            "--content",
            str(content_file),
            "--minify",
        ]

        config_path: str | None = get_setting("TAILWIND_CONFIG")
        if config_path:
            cmd.extend(["--config", config_path])

        return cmd

    def _run_tailwind(self, html_content: str, custom_css: str) -> str:
        """Run Tailwind CLI to generate CSS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            content_file = tmppath / "content.html"
            content_file.write_text(html_content, encoding="utf-8")

            input_file = tmppath / "input.css"
            input_file.write_text(self._build_input_css(custom_css), encoding="utf-8")

            output_file = tmppath / "output.css"

            cmd = self._build_command(
                self._get_cli_path(), input_file, output_file, content_file
            )

            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=TAILWIND_CLI_TIMEOUT_SECONDS,
            )

            if result.returncode != 0:
                raise subprocess.SubprocessError(
                    f"Tailwind CLI failed: {result.stderr}"
                )

            if output_file.exists():
                return output_file.read_text(encoding="utf-8").strip()

            return ""
