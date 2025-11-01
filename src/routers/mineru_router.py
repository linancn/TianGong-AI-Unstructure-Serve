import tempfile
import os
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum, TextElementWithPageNum
from src.services.gpu_scheduler import scheduler
from src.utils.response_utils import json_response, pretty_response_flag

router = APIRouter()

# List of allowed file extensions
ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpeg", ".jpg"]


@router.post(
    "/mineru",
    summary="Parse document with MinerU and return page-numbered chunks",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
)
async def mineru(
    file: UploadFile = File(...),
    pretty: bool = Depends(pretty_response_flag),
    chunk_type: bool = False,
):
    """
    Use MinerU to parse a document and return text chunks with page numbers.

    Accepted: .pdf, .png, .jpeg, .jpg
    Output: [(text, page_number), ...]
    """
    # Get file extension
    _, file_ext = os.path.splitext(file.filename)
    file_ext = file_ext.lower()

    # Check if file extension is allowed
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Use a persistent temp file so it survives queueing; we'll clean it up after processing
    tmp = tempfile.NamedTemporaryFile(suffix=file_ext, delete=False)
    try:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    try:
        # Dispatch to GPU scheduler; this returns a Future
        fut = scheduler.submit(tmp_path, chunk_type=chunk_type)
        payload = await _await_future(fut)
        # Map back into Pydantic model
        items = [
            TextElementWithPageNum(
                text=it["text"],
                page_number=int(it["page_number"]),
                type=it.get("type") if chunk_type else None,
            )
            for it in payload.get("result", [])
        ]
        response_model = ResponseWithPageNum(result=items)
        return json_response(response_model, pretty)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# Small helper to await a concurrent.futures.Future inside async route
async def _await_future(fut):
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fut.result)
