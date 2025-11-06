import asyncio
import os
import tempfile
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum, TextElementWithPageNum
from src.services.gpu_scheduler import scheduler
from src.utils.file_conversion import (
    CONVERTIBLE_OFFICE_EXTENSIONS,
    format_extension_list,
    maybe_convert_office_to_pdf,
)
from src.utils.mineru_support import (
    format_supported_extensions,
    mineru_supported_extensions,
)
from src.utils.response_utils import json_response, pretty_response_flag

router = APIRouter()

SUPPORTED_EXTENSIONS = mineru_supported_extensions()
SUPPORTED_EXTENSIONS_STR = format_supported_extensions()
CONVERTIBLE_EXTENSIONS_STR = format_extension_list(CONVERTIBLE_OFFICE_EXTENSIONS)
ACCEPTED_EXTENSIONS = SUPPORTED_EXTENSIONS | CONVERTIBLE_OFFICE_EXTENSIONS
ACCEPTED_EXTENSIONS_STR = format_extension_list(ACCEPTED_EXTENSIONS)
PARSE_TIMEOUT = int(os.getenv("MINERU_SCI_TIMEOUT_SECONDS", "110"))


@router.post(
    "/mineru_sci",
    summary="Parse scientific/academic docs with MinerU (sci), return page-numbered chunks",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
    description=f"Supported file types: {ACCEPTED_EXTENSIONS_STR}. "
    f"Office formats ({CONVERTIBLE_EXTENSIONS_STR}) auto-convert to PDF before parsing.",
)
async def mineru(
    file: UploadFile = File(...),
    pretty: bool = Depends(pretty_response_flag),
    chunk_type: bool = False,
):
    f"""
    Use MinerU (sci pipeline) to parse scientific/academic documents and return
    text chunks with page numbers.

    Accepted: {ACCEPTED_EXTENSIONS_STR}
    Office docs ({CONVERTIBLE_EXTENSIONS_STR}) are converted to PDF before parsing.
    Output: [(text, page_number), ...]
    """
    filename = file.filename or ""
    _, file_ext = os.path.splitext(filename)
    file_ext = file_ext.lower()

    if not file_ext:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is missing an extension; MinerU requires a supported file type.",
        )

    # Check if file extension is allowed
    if file_ext not in ACCEPTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed types: {ACCEPTED_EXTENSIONS_STR}",
        )

    # Use a persistent temp file so it survives queueing; we'll clean it up after processing
    tmp = tempfile.NamedTemporaryFile(suffix=file_ext, delete=False)
    try:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    conversion_cleanup: list[str] = []
    processing_path = tmp_path

    if file_ext in CONVERTIBLE_OFFICE_EXTENSIONS:
        try:
            processing_path, conversion_cleanup = maybe_convert_office_to_pdf(tmp_path, file_ext)
        except RuntimeError as exc:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    cleanup_paths = {tmp_path, *conversion_cleanup}

    try:
        # Dispatch to GPU scheduler; this returns a Future
        fut = scheduler.submit(processing_path, pipeline="sci", chunk_type=chunk_type)
        try:
            payload = await asyncio.wait_for(_await_future(fut), timeout=PARSE_TIMEOUT)
        except asyncio.TimeoutError:
            # Best-effort cancel; real hard timeout enforced inside worker wrapper
            fut.cancel()
            raise HTTPException(
                status_code=504, detail=f"Parsing timeout after {PARSE_TIMEOUT}s (sci pipeline)"
            )
        # Map back into Pydantic model
        items = [
            TextElementWithPageNum(
                text=it["text"],
                page_number=int(it["page_number"]),
                type=it.get("type") if chunk_type else None,
            )
            for it in payload.get("result", [])
        ]
        # The sci service has its own filtering logic, which is now inside the worker.
        # We just need to reconstruct the response.
        response_model = ResponseWithPageNum(result=items)
        return json_response(response_model, pretty)
    except TimeoutError as e:  # from hard timeout in worker layer
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for path in cleanup_paths:
            try:
                os.unlink(path)
            except Exception:
                pass


# Small helper to await a concurrent.futures.Future inside async route
async def _await_future(fut):
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fut.result)
