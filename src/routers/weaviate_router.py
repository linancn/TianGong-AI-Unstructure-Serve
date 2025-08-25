import os
import re
import tempfile
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from typing import List, Optional
import json

from src.models.models import InsertSummary
from src.services.mineru_service import mineru_service
from src.services.mineru_with_images_service import (
    mineru_service as mineru_with_images_service,
)
from src.services.weaviate_service import insert_text_chunks

router = APIRouter()

# Weaviate collection/class 命名规则正则
_WEAVIATE_CLASS_RE = re.compile(r"^[A-Z][_0-9A-Za-z]*$")


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


@router.post(
    "/weaviate/ingest",
    response_model=InsertSummary,
    response_description="Summary of inserted chunks parsed by MinerU.",
)
async def ingest_to_weaviate(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
    tags: Optional[str] = Form(
        None, description="Optional tags as JSON array or comma-separated string"
    ),
):
    """
    使用 MinerU 解析上传文档并写入 Weaviate。

    支持: .pdf
    source 字段使用原始文件名 (含扩展名)。
    """
    allowed_ext = {".pdf"}
    filename = file.filename or "uploaded"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(allowed_ext)}"
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

    with tempfile.NamedTemporaryFile(delete=True, suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name

        try:
            mineru_resp = mineru_service(tmp_path)  # ResponseWithPageNum
            chunks_with_pages = [
                (item.text, item.page_number) for item in mineru_resp.result if item.text.strip()
            ]
            summary = insert_text_chunks(
                collection_name=safe_collection,
                chunks_with_page=chunks_with_pages,
                source=filename,  # 使用完整文件名
                tags=parsed_tags,
            )
            return InsertSummary(**summary)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/weaviate/ingest-with-images",
    response_model=InsertSummary,
    response_description="Summary of inserted chunks parsed by MinerU-with-images.",
)
async def ingest_to_weaviate_with_images(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
    tags: Optional[str] = Form(
        None, description="Optional tags as JSON array or comma-separated string"
    ),
):
    """
    使用 MinerU-with-images 解析上传文档并写入 Weaviate。

    支持: .pdf
    source 字段使用原始文件名 (含扩展名)。
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

    with tempfile.NamedTemporaryFile(delete=True, suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp.flush()
        tmp_path = tmp.name

        try:
            mineru_resp = mineru_with_images_service(tmp_path)  # ResponseWithPageNum
            chunks_with_pages = [
                (item.text, item.page_number) for item in mineru_resp.result if item.text.strip()
            ]
            summary = insert_text_chunks(
                collection_name=safe_collection,
                chunks_with_page=chunks_with_pages,
                source=filename,  # 使用完整文件名
                tags=parsed_tags,
            )
            return InsertSummary(**summary)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))
