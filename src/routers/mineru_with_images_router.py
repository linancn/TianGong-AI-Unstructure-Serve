import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum, TextElementWithPageNum
from src.services.gpu_scheduler import scheduler

router = APIRouter()

# List of allowed file extensions
ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpeg", ".jpg"]


@router.post(
    "/mineru_with_images",
    summary="Parse with MinerU (image-aware) and return page-numbered chunks",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
)
async def mineru_with_images(file: UploadFile = File(...)):
    """
    Use MinerU with image-aware extraction (figures/tables) and return text chunks with page numbers.

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
        fut = scheduler.submit(tmp_path, pipeline="images")
        payload = await _await_future(fut)
        # Map back into Pydantic model
        items = [
            TextElementWithPageNum(text=it["text"], page_number=int(it["page_number"]))
            for it in payload.get("result", [])
        ]
        return ResponseWithPageNum(result=items)
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
