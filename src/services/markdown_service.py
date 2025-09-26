"""Helpers for turning Markdown text into downloadable files."""

from __future__ import annotations

import os

_DEFAULT_FILENAME = "document.md"


def markdown_bytes(content: str, filename: str | None = None) -> tuple[str, bytes]:
    """Return a safe file name and UTF-8 bytes for the given Markdown content.

    If *filename* is provided the ``.md`` suffix is enforced and only the base
    name is kept so callers cannot escape the download directory.
    """

    if content is None:
        raise ValueError("Markdown content is required")

    safe_name = (filename or _DEFAULT_FILENAME).strip() or _DEFAULT_FILENAME
    safe_name = os.path.basename(safe_name)

    if not safe_name.lower().endswith(".md"):
        safe_name = f"{safe_name}.md"

    return safe_name, content.encode("utf-8")
