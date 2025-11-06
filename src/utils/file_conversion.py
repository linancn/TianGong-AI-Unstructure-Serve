from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Set, Tuple

# Common Office-style formats that LibreOffice can convert to PDF.
CONVERTIBLE_OFFICE_EXTENSIONS: Set[str] = {
    ".doc",
    ".docx",
    ".docm",
    ".dot",
    ".dotx",
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".pot",
    ".potx",
    ".odp",
    ".odt",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlt",
    ".xltx",
}

MARKDOWN_EXTENSIONS: Set[str] = {
    ".md",
    ".markdown",
}

_LIBREOFFICE_BINARIES: Tuple[str, ...] = ("libreoffice", "soffice")


def _normalize_extension(ext: str) -> str:
    ext = (ext or "").strip().lower()
    if not ext:
        return ""
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext


def format_extension_list(extensions: Iterable[str]) -> str:
    """Return a comma-separated, sorted string of extensions."""
    normalized = {_normalize_extension(ext) for ext in extensions if ext}
    return ", ".join(sorted(normalized))


def _find_libreoffice_executable() -> str | None:
    for candidate in _LIBREOFFICE_BINARIES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def convert_office_document_to_pdf(input_path: str) -> Tuple[str, List[str]]:
    """
    Convert an Office document to PDF using LibreOffice.

    Returns a tuple of (converted_pdf_path, extra_cleanup_paths).
    """
    libreoffice = _find_libreoffice_executable()
    if not libreoffice:
        raise RuntimeError(
            "LibreOffice executable not found in PATH. Install LibreOffice or expose 'soffice' "
            "to enable automatic Office-to-PDF conversion."
        )

    src = Path(input_path)
    if not src.exists():
        raise RuntimeError(f"Source file for conversion not found: {input_path}")

    tmp_output_dir = Path(tempfile.mkdtemp(prefix="mineru-office-", suffix="-pdf"))
    target_name = f"{src.stem}.pdf"
    cmd = [
        libreoffice,
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--convert-to",
        "pdf",
        "--outdir",
        str(tmp_output_dir),
        str(src),
    ]

    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        shutil.rmtree(tmp_output_dir, ignore_errors=True)
        raise RuntimeError(
            "LibreOffice failed to convert Office document to PDF. "
            f"Exit code: {completed.returncode}. "
            f"Output: {completed.stderr or completed.stdout}"
        )

    converted_pdf = tmp_output_dir / target_name
    if not converted_pdf.exists():
        shutil.rmtree(tmp_output_dir, ignore_errors=True)
        raise RuntimeError("LibreOffice conversion did not produce the expected PDF output file.")

    fd, final_path = tempfile.mkstemp(prefix="mineru-office-", suffix=".pdf")
    os.close(fd)
    shutil.move(converted_pdf, final_path)
    shutil.rmtree(tmp_output_dir, ignore_errors=True)

    return final_path, [final_path]


def maybe_convert_office_to_pdf(input_path: str, extension: str) -> Tuple[str, List[str]]:
    """
    Convert the given file to PDF if it is an Office document.

    Returns (path_to_use, extra_cleanup_paths list).
    """
    normalized_ext = _normalize_extension(extension)
    if normalized_ext not in CONVERTIBLE_OFFICE_EXTENSIONS:
        return input_path, []
    return convert_office_document_to_pdf(input_path)


def maybe_convert_to_pdf(input_path: str, extension: str) -> Tuple[str, List[str]]:
    """
    Convert supported Office documents to PDF, leaving other formats untouched.

    Returns (path_to_use, extra_cleanup_paths list).
    """
    normalized_ext = _normalize_extension(extension)
    if normalized_ext in CONVERTIBLE_OFFICE_EXTENSIONS:
        return convert_office_document_to_pdf(input_path)
    return input_path, []


__all__ = [
    "CONVERTIBLE_OFFICE_EXTENSIONS",
    "MARKDOWN_EXTENSIONS",
    "convert_office_document_to_pdf",
    "format_extension_list",
    "maybe_convert_office_to_pdf",
    "maybe_convert_to_pdf",
]
