import json
import os
import re
import tempfile
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.models.models import InsertSummary, ResponseWithPageNum, TextElementWithPageNum
from src.services.gpu_scheduler import scheduler
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

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    try:
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
        else:
            # DOCX：使用 DOCX 解析服务，得到不带页码的文本列表
            chunks: List[str] = unstructure_docx(tmp_path)
            summary = insert_text_chunks(
                collection_name=safe_collection,
                chunks_with_page=chunks,
                source=filename,
                tags=parsed_tags,
            )
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

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    try:
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


# 已移除 /weaviate/ingest_docx 入口，统一由 /weaviate/ingest 处理 .pdf 与 .docx
