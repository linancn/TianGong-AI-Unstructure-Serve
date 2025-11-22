import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.models.models import MinioAssetSummary, ResponseWithPageNum, TextElementWithPageNum
from src.services.gpu_scheduler import scheduler
from src.services.vision_service import (
    AVAILABLE_MODEL_VALUES,
    AVAILABLE_PROVIDER_VALUES,
    VisionModel,
    VisionProvider,
)
from src.routers.mineru_minio_utils import (
    MinioContext,
    build_minio_prefix,
    initialize_minio_context,
    upload_pdf_assets,
)
from src.utils.file_conversion import (
    CONVERTIBLE_OFFICE_EXTENSIONS,
    MARKDOWN_EXTENSIONS,
    format_extension_list,
    maybe_convert_to_pdf,
)
from src.utils.markdown_parser import parse_markdown_chunks
from src.utils.mineru_support import (
    format_supported_extensions,
    mineru_supported_extensions,
)
from src.utils.response_utils import json_response, pretty_response_flag
from src.utils.text_output import build_plain_text

router = APIRouter()

SUPPORTED_EXTENSIONS = mineru_supported_extensions()
SUPPORTED_EXTENSIONS_STR = format_supported_extensions()
OFFICE_EXTENSIONS_STR = format_extension_list(CONVERTIBLE_OFFICE_EXTENSIONS)
MARKDOWN_EXTENSIONS_STR = format_extension_list(MARKDOWN_EXTENSIONS)
ACCEPTED_EXTENSIONS = SUPPORTED_EXTENSIONS | CONVERTIBLE_OFFICE_EXTENSIONS | MARKDOWN_EXTENSIONS
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
    description=(
        f"Supported file types: {ACCEPTED_EXTENSIONS_STR}.\n"
        f"Office formats ({OFFICE_EXTENSIONS_STR}) auto-convert to PDF before parsing.\n"
        f"Markdown ({MARKDOWN_EXTENSIONS_STR}) is parsed directly via regex-based chunking."
    ),
)
async def mineru_with_images(
    file: UploadFile = File(...),
    provider: Optional[VisionProvider] = Depends(_form_provider),
    model: Optional[VisionModel] = Depends(_form_model),
    prompt: Optional[str] = Form(
        None,
        description="Optional instruction prompt override passed to the vision model.",
    ),
    save_to_minio: bool = Form(
        False,
        description="Store the parsed PDF, JSON payload, and per-page images in MinIO.",
    ),
    minio_address: Optional[str] = Form(
        None, description="MinIO server address, e.g. https://minio.local:9000"
    ),
    minio_access_key: Optional[str] = Form(None, description="MinIO access key"),
    minio_secret_key: Optional[str] = Form(None, description="MinIO secret key"),
    minio_bucket: Optional[str] = Form(None, description="Target MinIO bucket name"),
    minio_prefix: Optional[str] = Form(
        None,
        description="Optional custom prefix for stored assets; defaults to mineru/<filename>.",
    ),
    pretty: bool = Depends(pretty_response_flag),
    chunk_type: bool = False,
    return_txt: bool = False,
):
    f"""
    Use MinerU with image-aware extraction (figures/tables) and return text chunks with page numbers.

    Accepted: {ACCEPTED_EXTENSIONS_STR}
    Office formats ({OFFICE_EXTENSIONS_STR}) auto-convert to PDF before parsing.
    Markdown ({MARKDOWN_EXTENSIONS_STR}) is parsed directly via regex-based chunking.
    Optional: set save_to_minio=true with credentials to upload the PDF, parsed JSON, and page images.
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

    if save_to_minio and file_ext in MARKDOWN_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="MinIO storage is not supported for Markdown uploads.",
        )

    file_bytes = await file.read()

    if file_ext in MARKDOWN_EXTENSIONS:
        text_content = file_bytes.decode("utf-8", errors="ignore")
        items = parse_markdown_chunks(text_content, chunk_type=chunk_type)
        txt_text = build_plain_text(items) if return_txt else None
        response_model = ResponseWithPageNum(result=items, txt=txt_text)
        return json_response(response_model, pretty)

    # Use a persistent temp file so it survives queueing; we'll clean it up after processing
    tmp = tempfile.NamedTemporaryFile(suffix=file_ext, delete=False)
    try:
        tmp.write(file_bytes)
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    conversion_cleanup: list[str] = []
    processing_path = tmp_path

    if file_ext in CONVERTIBLE_OFFICE_EXTENSIONS:
        try:
            processing_path, conversion_cleanup = maybe_convert_to_pdf(tmp_path, file_ext)
        except RuntimeError as exc:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    cleanup_paths = {tmp_path, *conversion_cleanup}

    try:
        minio_context: MinioContext = None
        minio_prefix_value: Optional[str] = None
        if save_to_minio:
            if not processing_path.lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail="MinIO storage requires a PDF input after preprocessing.",
                )
            minio_context = initialize_minio_context(
                save_to_minio,
                minio_address,
                minio_access_key,
                minio_secret_key,
                minio_bucket,
            )
            minio_prefix_value = build_minio_prefix(filename, minio_prefix)

        # Dispatch to GPU scheduler; this returns a Future
        fut = scheduler.submit(
            processing_path,
            pipeline="images",
            chunk_type=chunk_type,
            vision_prompt=prompt,
            vision_provider=provider,
            vision_model=model,
            return_txt=return_txt,
        )
        payload = await _await_future(fut)
        result_payload = payload.get("result")
        if not isinstance(result_payload, list):
            raise HTTPException(
                status_code=500,
                detail="Invalid scheduler response payload for MinerU with images.",
            )

        ordered_chunks: list[dict] = []
        for it in result_payload:
            try:
                text = it["text"]
                page_number = int(it["page_number"])
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Malformed item returned by MinerU scheduler: {exc}",
                )
            item_type = it.get("type")
            if not chunk_type and item_type in {"header", "footer", "page_number"}:
                continue
            if chunk_type and item_type == "page_number":
                continue
            ordered_chunks.append(
                {
                    "text": text,
                    "page_number": page_number,
                    "type": item_type,
                }
            )
        if chunk_type:
            ordered_chunks.sort(key=lambda ch: (0 if ch["type"] == "header" else 1))
        items = [
            TextElementWithPageNum(
                text=chunk["text"],
                page_number=chunk["page_number"],
                type=chunk["type"] if chunk_type else None,
            )
            for chunk in ordered_chunks
        ]
        txt_text = payload.get("txt")
        if return_txt:
            txt_text = build_plain_text(items)
        chunks_with_pages = [
            (item.text, item.page_number) for item in items if item.text and item.text.strip()
        ]
        minio_assets_summary: Optional[MinioAssetSummary] = None
        if minio_context:
            assert minio_prefix_value is not None  # for mypy
            minio_assets_summary = upload_pdf_assets(
                minio_context,
                minio_prefix_value,
                processing_path,
                chunks_with_pages,
            )
        response_model = ResponseWithPageNum(
            result=items,
            txt=txt_text if return_txt else None,
            minio_assets=minio_assets_summary,
        )
        return json_response(response_model, pretty)
    except HTTPException:
        raise
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
