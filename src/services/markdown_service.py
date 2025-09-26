"""Helpers for turning Markdown text into downloadable files."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Final

_DEFAULT_MARKDOWN_FILENAME: Final[str] = "document.md"
_DEFAULT_DOCX_FILENAME: Final[str] = "document.docx"
_DEFAULT_PANDOC_FROM: Final[str] = (
    "gfm-hard_line_breaks+emoji"  # GitHub-flavoured markdown with emoji, but without hard breaks that flatten headings
)
_HEADING_LINE_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")


def markdown_bytes(content: str, filename: str | None = None) -> tuple[str, bytes]:
    """Return a safe file name and UTF-8 bytes for the given Markdown content.

    If *filename* is provided the ``.md`` suffix is enforced and only the base
    name is kept so callers cannot escape the download directory.
    """

    if content is None:
        raise ValueError("Markdown content is required")

    safe_name = _safe_filename(filename, _DEFAULT_MARKDOWN_FILENAME, ".md")

    return safe_name, content.encode("utf-8")


def markdown_to_docx_bytes(
    content: str,
    filename: str | None = None,
    reference_doc_path: str | None = None,
) -> tuple[str, bytes]:
    """Return DOCX bytes converted from Markdown using Pandoc.

    Accepts an optional *reference_doc_path* to control styling and falls back
    to the bundled DOCX template when none is supplied.
    """

    if content is None:
        raise ValueError("Markdown content is required")

    safe_name = _safe_filename(filename, _DEFAULT_DOCX_FILENAME, ".docx")
    normalized_content = _normalize_markdown(content)
    reference_doc = _resolve_reference_doc(reference_doc_path)

    pandoc_cmd = [_pandoc_executable(), f"--from={_DEFAULT_PANDOC_FROM}", "--to=docx"]

    if reference_doc:
        pandoc_cmd.extend(["--reference-doc", reference_doc])

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        output_path = tmpdir_path / "output.docx"
        pandoc_cmd.extend(["--output", str(output_path)])

        try:
            subprocess.run(
                pandoc_cmd,
                input=normalized_content,
                text=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:  # Pandoc missing from environment.
            raise RuntimeError(
                "Pandoc executable not found. Install pandoc or set PANDOC_PATH"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Pandoc failed to create DOCX: {error}".format(error=exc.stderr)
            ) from exc

        docx_bytes = output_path.read_bytes()

    return safe_name, docx_bytes


def _safe_filename(filename: str | None, default: str, suffix: str) -> str:
    """Return an os-safe file name with the desired suffix enforced."""

    safe_name = (filename or default).strip() or default
    safe_name = os.path.basename(safe_name)

    if not safe_name.lower().endswith(suffix):
        safe_name = f"{safe_name}{suffix}"

    return safe_name


def _resolve_reference_doc(reference_doc_path: str | None) -> str | None:
    """Prefer explicit reference doc path, fall back to packaged default template."""

    candidate_path = reference_doc_path

    if not candidate_path:
        default_candidate = Path(__file__).resolve().parent / "templates" / "default_reference.docx"
        return str(default_candidate) if default_candidate.exists() else None

    resolved_path = Path(candidate_path).expanduser().resolve()
    if not resolved_path.exists():
        raise ValueError(f"Reference DOCX template not found: {resolved_path}")

    return str(resolved_path)


def _pandoc_executable() -> str:
    """Allow overriding the pandoc executable via environment variable."""

    return os.getenv("PANDOC_PATH", "pandoc")


def _normalize_markdown(content: str) -> str:
    """Tidy headings so Pandoc reliably recognises heading levels."""

    lines = content.splitlines()
    normalised_lines: list[str] = []
    last_was_heading = False

    for raw_line in lines:
        line = raw_line.rstrip()
        heading_match = _HEADING_LINE_PATTERN.match(line)

        if heading_match:
            if normalised_lines and normalised_lines[-1]:
                normalised_lines.append("")
            normalised_lines.append(f"{heading_match.group(1)} {heading_match.group(2).strip()}")
            last_was_heading = True
            continue

        if line:
            if last_was_heading and normalised_lines and normalised_lines[-1]:
                normalised_lines.append("")
            normalised_lines.append(line)
            last_was_heading = False
        else:
            if not normalised_lines or normalised_lines[-1]:
                normalised_lines.append("")
            last_was_heading = False

    return "\n".join(normalised_lines).strip("\n") + "\n"
