"""FastAPI router for turning Markdown strings into downloadable files."""

from __future__ import annotations

import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.services.markdown_service import markdown_bytes

router = APIRouter()


class MarkdownPayload(BaseModel):
    """Request body for Markdown export."""

    content: str = Field(..., description="Markdown document content")
    filename: str = Field(
        ..., description="Filename for download; .md will be appended automatically"
    )


@router.post(
    "/markdown",
    summary="Create a Markdown file from supplied text",
    response_description="Markdown file download",
)
async def export_markdown_file(payload: MarkdownPayload):
    """Return a Markdown file generated from the provided content string."""

    try:
        filename, data = markdown_bytes(payload.content, payload.filename)
    except ValueError as exc:  # Defensive: service returns ValueError on invalid input
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stream = io.BytesIO(data)
    stream.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        stream,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )
