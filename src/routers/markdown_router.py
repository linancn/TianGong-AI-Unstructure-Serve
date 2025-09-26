"""FastAPI router exposing Markdown-to-DOCX conversion endpoints."""

from __future__ import annotations

import io
import tempfile
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from src.services.markdown_service import markdown_to_docx_bytes

router = APIRouter()

_DEFAULT_REFERENCE_DOC = (
    Path(__file__).resolve().parent.parent / "services" / "templates" / "default_reference.docx"
)


@router.post(
    "/markdown/docx",
    summary="Create a DOCX from supplied Markdown",
    response_description="DOCX file download",
)
async def export_markdown_docx_file(
    content: str = Form(..., description="Markdown document content"),
    filename: str = Form(
        ..., description="Filename for download; .docx will be appended automatically"
    ),
    reference_doc: UploadFile | str | None = File(
        None,
        description=("Optional DOCX template upload to style the output document."),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
):
    """Return a DOCX file generated from Markdown, with optional template styling."""

    reference_doc_path: str | None = None
    cleanup_path: Path | None = None

    if isinstance(reference_doc, str):
        if reference_doc.strip():
            raise HTTPException(
                status_code=400,
                detail="reference_doc must be provided as a DOCX file upload",
            )
        reference_doc = None

    if reference_doc is not None:
        if reference_doc.content_type not in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        }:
            await reference_doc.close()
            raise HTTPException(
                status_code=400,
                detail="reference_doc must be a DOCX file upload",
            )

        contents = await reference_doc.read()
        suffix = Path(reference_doc.filename or "").suffix or ".docx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            temp_path = Path(tmp.name)

        reference_doc_path = str(temp_path)
        cleanup_path = temp_path
        await reference_doc.close()
    elif _DEFAULT_REFERENCE_DOC.exists():
        reference_doc_path = str(_DEFAULT_REFERENCE_DOC)
    else:
        reference_doc_path = None

    try:
        filename, data = markdown_to_docx_bytes(content, filename, reference_doc_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if cleanup_path is not None:
            with suppress(FileNotFoundError):
                cleanup_path.unlink()

    stream = io.BytesIO(data)
    stream.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
