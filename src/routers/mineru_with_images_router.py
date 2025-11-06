import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum, TextElementWithPageNum
from src.services.gpu_scheduler import scheduler
from src.services.vision_service import (
    AVAILABLE_MODEL_VALUES,
    AVAILABLE_PROVIDER_VALUES,
    VisionModel,
    VisionProvider,
)
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


def _form_provider(
    provider: Optional[str] = Form(
        None,
        description="Vision model provider to use.",
        json_schema_extra={"enum": AVAILABLE_PROVIDER_VALUES},
    )
) -> Optional[VisionProvider]:
    if provider is None or provider.strip() == "":
        return None
    try:
        return VisionProvider(provider.strip())
    except ValueError:
        allowed = ", ".join(p.value for p in VisionProvider)
        raise HTTPException(
            status_code=422, detail=f"Invalid provider '{provider}'. Allowed: {allowed}."
        )


def _form_model(
    model: Optional[str] = Form(
        None,
        description="Vision model identifier to use.",
        json_schema_extra={"enum": AVAILABLE_MODEL_VALUES},
    )
) -> Optional[VisionModel]:
    if model is None or model.strip() == "":
        return None
    try:
        return VisionModel(model.strip())
    except ValueError:
        allowed = ", ".join(m.value for m in VisionModel)
        raise HTTPException(status_code=422, detail=f"Invalid model '{model}'. Allowed: {allowed}.")


@router.post(
    "/mineru_with_images",
    summary="Parse with MinerU (image-aware) and return page-numbered chunks",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
    description=f"Supported file types: {ACCEPTED_EXTENSIONS_STR}. "
    f"Office formats ({CONVERTIBLE_EXTENSIONS_STR}) auto-convert to PDF before parsing.",
)
async def mineru_with_images(
    file: UploadFile = File(...),
    provider: Optional[VisionProvider] = Depends(_form_provider),
    model: Optional[VisionModel] = Depends(_form_model),
    prompt: Optional[str] = Form(
        None,
        description="Optional instruction prompt override passed to the vision model.",
    ),
    pretty: bool = Depends(pretty_response_flag),
    chunk_type: bool = False,
):
    f"""
    Use MinerU with image-aware extraction (figures/tables) and return text chunks with page numbers.

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
        fut = scheduler.submit(
            processing_path,
            pipeline="images",
            chunk_type=chunk_type,
            vision_prompt=prompt,
            vision_provider=provider,
            vision_model=model,
        )
        payload = await _await_future(fut)
        result_payload = payload.get("result")
        if not isinstance(result_payload, list):
            raise HTTPException(
                status_code=500,
                detail="Invalid scheduler response payload for MinerU with images.",
            )

        items = []
        for it in result_payload:
            try:
                text = it["text"]
                page_number = int(it["page_number"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Malformed item returned by MinerU scheduler: {exc}",
                )
            items.append(
                TextElementWithPageNum(
                    text=text,
                    page_number=page_number,
                    type=it.get("type") if chunk_type else None,
                )
            )
        response_model = ResponseWithPageNum(result=items)
        return json_response(response_model, pretty)
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
