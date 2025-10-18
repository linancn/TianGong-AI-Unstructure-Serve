import json
import mimetypes
import os
import re
import tempfile
from typing import List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from src.models.models import (
    InsertSummary,
    MinioAssetSummary,
    MinioPageImage,
    ResponseWithPageNum,
    TextElementWithPageNum,
)
from src.services.gpu_scheduler import scheduler
from src.services.minio_storage import (
    MinioConfig,
    MinioStorageError,
    MinioObjectNotFound,
    clear_prefix,
    upload_pdf_bundle,
    create_client,
    ensure_bucket,
    parse_minio_endpoint,
    prepare_object_download,
)
from src.services.docx_service import unstructure_docx
from src.services.vision_service import (
    AVAILABLE_MODEL_VALUES,
    AVAILABLE_PROVIDER_VALUES,
    VisionModel,
    VisionProvider,
)
from src.services.weaviate_service import insert_text_chunks
from src.utils.response_utils import json_response, pretty_response_flag

router = APIRouter()

# Weaviate collection/class 命名规则正则
_WEAVIATE_CLASS_RE = re.compile(r"^[A-Z][_0-9A-Za-z]*$")


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


def build_weaviate_collection_name(base: str, user_id: str) -> str:
    """
    生成合法的 Weaviate collection 名：
    - 以大写字母开头
    - 仅包含 字母/数字/下划线
    - 将 user_id 中的非法字符去除或替换
    """
    if not base:
        base = "KB"
    # 只保留字母数字下划线并整体转为大写
    base_clean = re.sub(r"[^0-9A-Za-z_]", "_", base).upper() or "KB"

    # 处理 user_id：去掉连字符等，仅保留可用字符，并整体转为大写
    uid_clean = re.sub(r"[^0-9A-Za-z_]", "_", user_id).upper()

    # 拼接：推荐下划线作为分隔
    name = f"KB_{uid_clean}_{base_clean}"

    # 可选：限制长度，避免名字过长（按需调整）
    if len(name) > 200:
        name = name[:200]

    if not _WEAVIATE_CLASS_RE.match(name):
        raise ValueError(f"Illegal collection name after sanitation: {name}")
    return name


# Small helper to await a concurrent.futures.Future inside async route
async def _await_future(fut):
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fut.result)


MinioContext = Optional[Tuple[MinioConfig, object]]


def _initialize_minio_context(
    save_to_minio: bool,
    address: Optional[str],
    access_key: Optional[str],
    secret_key: Optional[str],
    bucket: Optional[str],
) -> MinioContext:
    if not save_to_minio:
        return None

    required = {
        "minio_address": address,
        "minio_access_key": access_key,
        "minio_secret_key": secret_key,
        "minio_bucket": bucket,
    }
    missing = [key for key, value in required.items() if not value or not value.strip()]
    if missing:
        joined = ", ".join(missing)
        raise HTTPException(status_code=400, detail=f"Missing MinIO field(s): {joined}")

    assert address is not None  # for type checker
    assert access_key is not None
    assert secret_key is not None
    assert bucket is not None

    try:
        endpoint, secure = parse_minio_endpoint(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cfg = MinioConfig(
        endpoint=endpoint,
        access_key=access_key.strip(),
        secret_key=secret_key.strip(),
        bucket=bucket.strip(),
        secure=secure,
    )

    try:
        client = create_client(cfg)
        ensure_bucket(client, cfg.bucket)
    except MinioStorageError as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to prepare MinIO bucket: {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Failed to initialize MinIO client: {exc}"
        ) from exc

    return (cfg, client)


def _build_minio_prefix(collection: str, filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    base_clean = re.sub(r"[^0-9A-Za-z_-]+", "_", base).strip("_") or "document"
    return f"{collection}/{base_clean}"


def _upload_pdf_assets(
    ctx: MinioContext,
    collection: str,
    filename: str,
    pdf_path: str,
    chunks_with_pages: Sequence[Tuple[str, int]],
) -> MinioAssetSummary:
    if ctx is None:
        raise RuntimeError("MinIO context is required to upload assets.")
    cfg, client = ctx
    prefix = _build_minio_prefix(collection, filename)
    try:
        clear_prefix(client, cfg.bucket, prefix)
    except MinioStorageError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to clear existing MinIO objects: {exc}"
        ) from exc
    payload_for_json = [
        {"text": text, "page_number": page_number} for text, page_number in chunks_with_pages
    ]
    try:
        record = upload_pdf_bundle(
            client,
            cfg=cfg,
            prefix=prefix,
            pdf_path=pdf_path,
            parsed_payload=payload_for_json,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to upload assets to MinIO: {exc}"
        ) from exc

    return MinioAssetSummary(
        bucket=record.bucket,
        prefix=record.prefix,
        pdf_object=record.pdf_object,
        json_object=record.json_object,
        page_images=[
            MinioPageImage(page_number=page, object_name=obj_name)
            for page, obj_name in record.page_images
        ],
    )


@router.post(
    "/weaviate/ingest",
    summary="Ingest parsed chunks into Weaviate (PDF via MinerU, DOCX via DOCX parser)",
    response_model=InsertSummary,
    response_description="Summary of inserted chunks",
)
async def ingest_to_weaviate(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
    tags: Optional[str] = Form(
        None, description="Optional tags as JSON array or comma-separated string"
    ),
    save_to_minio: bool = Form(
        False, description="Store the PDF and parsed artifacts in MinIO alongside Weaviate."
    ),
    minio_address: Optional[str] = Form(
        None, description="MinIO server address, e.g. https://minio.local:9000"
    ),
    minio_access_key: Optional[str] = Form(None, description="MinIO access key"),
    minio_secret_key: Optional[str] = Form(None, description="MinIO secret key"),
    minio_bucket: Optional[str] = Form(None, description="Target MinIO bucket name"),
    pretty: bool = Depends(pretty_response_flag),
):
    """
    Parse the uploaded document and insert chunks into Weaviate.

    - Supported types: .pdf (MinerU), .docx (DOCX parser service)
    - Collection name: sanitize and combine collection_name and user_id to a legal Weaviate class name
    - tags: JSON array or comma-separated string
    - source: original filename (with extension)
    - Returns: number of inserted items and summary
    """
    allowed_ext = {".pdf", ".docx"}
    filename = file.filename or "uploaded"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(allowed_ext))}",
        )

    # 规范化并校验 collection 名称
    try:
        safe_collection = build_weaviate_collection_name(collection_name, user_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # Parse optional tags input (accept JSON array or comma-separated string)
    parsed_tags: Optional[List[str]] = None
    if tags:
        try:
            if tags.strip().startswith("["):
                loaded = json.loads(tags)
                if isinstance(loaded, list):
                    parsed_tags = [str(t) for t in loaded if str(t).strip()]
            else:
                parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid tags format; supply JSON array or comma-separated list",
            )

    minio_context: MinioContext = None
    if save_to_minio:
        if ext != ".pdf":
            raise HTTPException(
                status_code=400,
                detail="MinIO storage is only supported for PDF uploads.",
            )
        minio_context = _initialize_minio_context(
            save_to_minio,
            minio_address,
            minio_access_key,
            minio_secret_key,
            minio_bucket,
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    try:
        minio_assets_summary: Optional[MinioAssetSummary] = None
        if ext == ".pdf":
            # PDF：使用 MinerU，得到 (text, page) 列表
            fut = scheduler.submit(tmp_path, pipeline="default")
            payload = await _await_future(fut)
            items = [
                TextElementWithPageNum(text=it["text"], page_number=int(it["page_number"]))
                for it in payload.get("result", [])
            ]
            mineru_resp = ResponseWithPageNum(result=items)

            chunks_with_pages = [
                (item.text, item.page_number) for item in mineru_resp.result if item.text.strip()
            ]
            summary = insert_text_chunks(
                collection_name=safe_collection,
                chunks_with_page=chunks_with_pages,
                source=filename,
                tags=parsed_tags,
            )
            if minio_context:
                minio_assets_summary = _upload_pdf_assets(
                    minio_context,
                    safe_collection,
                    filename,
                    tmp_path,
                    chunks_with_pages,
                )
        else:
            # DOCX：使用 DOCX 解析服务，得到不带页码的文本列表
            chunks: List[str] = unstructure_docx(tmp_path)
            summary = insert_text_chunks(
                collection_name=safe_collection,
                chunks_with_page=chunks,
                source=filename,
                tags=parsed_tags,
            )
        if minio_assets_summary:
            summary["minio_assets"] = minio_assets_summary.model_dump(mode="python")
        response_model = InsertSummary(**summary)
        return json_response(response_model, pretty)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post(
    "/weaviate/ingest_with_images",
    summary="Ingest parsed chunks into Weaviate (MinerU with images)",
    response_model=InsertSummary,
    response_description="Summary of inserted chunks",
)
async def ingest_to_weaviate_with_images(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
    provider: Optional[VisionProvider] = Depends(_form_provider),
    model: Optional[VisionModel] = Depends(_form_model),
    tags: Optional[str] = Form(
        None, description="Optional tags as JSON array or comma-separated string"
    ),
    save_to_minio: bool = Form(
        False, description="Store the PDF and parsed artifacts in MinIO alongside Weaviate."
    ),
    minio_address: Optional[str] = Form(
        None, description="MinIO server address, e.g. https://minio.local:9000"
    ),
    minio_access_key: Optional[str] = Form(None, description="MinIO access key"),
    minio_secret_key: Optional[str] = Form(None, description="MinIO secret key"),
    minio_bucket: Optional[str] = Form(None, description="Target MinIO bucket name"),
    pretty: bool = Depends(pretty_response_flag),
):
    """
    Use MinerU-with-images to parse an uploaded PDF and insert chunks into Weaviate
    with image-aware extraction (figures/tables).

    - Supported types: .pdf
    - provider/model: optionally override the MinerU vision backend
    - Collection name: sanitize and combine collection_name and user_id to a legal Weaviate class name
    - tags: JSON array or comma-separated string
    - source: original filename (with extension)
    - Returns: number of inserted items and summary
    """
    allowed_ext = {".pdf"}
    filename = file.filename or "uploaded"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(allowed_ext))}",
        )

    # 规范化并校验 collection 名称
    try:
        safe_collection = build_weaviate_collection_name(collection_name, user_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    # Parse optional tags input (accept JSON array or comma-separated string)
    parsed_tags: Optional[List[str]] = None
    if tags:
        try:
            if tags.strip().startswith("["):
                loaded = json.loads(tags)
                if isinstance(loaded, list):
                    parsed_tags = [str(t) for t in loaded if str(t).strip()]
            else:
                parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid tags format; supply JSON array or comma-separated list",
            )

    minio_context: MinioContext = None
    if save_to_minio:
        minio_context = _initialize_minio_context(
            save_to_minio,
            minio_address,
            minio_access_key,
            minio_secret_key,
            minio_bucket,
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    try:
        minio_assets_summary: Optional[MinioAssetSummary] = None
        fut = scheduler.submit(
            tmp_path,
            pipeline="images",
            vision_provider=provider,
            vision_model=model,
        )
        payload = await _await_future(fut)
        items = [
            TextElementWithPageNum(text=it["text"], page_number=int(it["page_number"]))
            for it in payload.get("result", [])
        ]
        mineru_resp = ResponseWithPageNum(result=items)

        chunks_with_pages = [
            (item.text, item.page_number) for item in mineru_resp.result if item.text.strip()
        ]
        summary = insert_text_chunks(
            collection_name=safe_collection,
            chunks_with_page=chunks_with_pages,
            source=filename,  # 使用完整文件名
            tags=parsed_tags,
        )
        if minio_context:
            minio_assets_summary = _upload_pdf_assets(
                minio_context,
                safe_collection,
                filename,
                tmp_path,
                chunks_with_pages,
            )
        if minio_assets_summary:
            summary["minio_assets"] = minio_assets_summary.model_dump(mode="python")
        response_model = InsertSummary(**summary)
        return json_response(response_model, pretty)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.post(
    "/minio/download",
    summary="Download a stored file from MinIO",
    response_description="Binary stream of the requested object",
)
async def download_minio_file(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    minio_address: str = Form(
        ..., description="MinIO server address, e.g. https://minio.local:9000"
    ),
    minio_access_key: str = Form(..., description="MinIO access key"),
    minio_secret_key: str = Form(..., description="MinIO secret key"),
    minio_bucket: str = Form(..., description="Target MinIO bucket name"),
    object_path: str = Form(
        ..., description="Path of the object to download (relative to the collection)"
    ),
):
    try:
        safe_collection = build_weaviate_collection_name(collection_name, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_path = object_path.strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail="object_path must not be empty.")
    normalized_path = normalized_path.lstrip("/")
    if normalized_path.startswith(f"{safe_collection}/"):
        object_name = normalized_path
    else:
        object_name = f"{safe_collection}/{normalized_path}"

    minio_context = _initialize_minio_context(
        True,
        minio_address,
        minio_access_key,
        minio_secret_key,
        minio_bucket,
    )
    if minio_context is None:
        raise HTTPException(status_code=500, detail="Failed to initialize MinIO context.")

    cfg, client = minio_context
    try:
        stream, info = prepare_object_download(client, cfg.bucket, object_name)
    except MinioObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MinioStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to download MinIO object: {exc}"
        ) from exc

    filename = os.path.basename(info.object_name) or "download.bin"
    media_type = (
        info.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if info.size is not None:
        headers["Content-Length"] = str(info.size)
    if info.etag:
        headers["ETag"] = info.etag

    return StreamingResponse(stream, media_type=media_type, headers=headers)


# 已移除 /weaviate/ingest_docx 入口，统一由 /weaviate/ingest 处理 .pdf 与 .docx
