import os
import tempfile
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.models.models import InsertSummary
from src.services.mineru_service import mineru_service
from src.services.weaviate_service import insert_text_chunks

router = APIRouter()


@router.post(
    "/weaviate/ingest",
    response_model=InsertSummary,
    response_description="Summary of inserted chunks parsed by MinerU.",
)
async def ingest_to_weaviate(
    collection_name: str = Form(...),
    file: UploadFile = File(...),
):
    """使用 MinerU 解析上传文档并写入 Weaviate。

    支持: .pdf, .png, .jpeg, .jpg
    source 字段使用原始文件名 (含扩展名)。
    """
    allowed_ext = {".pdf", ".png", ".jpeg", ".jpg"}
    filename = file.filename or "uploaded"
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(allowed_ext)}")

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
                collection_name=collection_name,
                chunks_with_page=chunks_with_pages,
                source=filename,  # 使用完整文件名
            )
            return InsertSummary(**summary)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e))
