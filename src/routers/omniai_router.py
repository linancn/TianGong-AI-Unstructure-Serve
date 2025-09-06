import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum
from src.services.omniai_service import omniai_service

router = APIRouter()


@router.post(
    "/omniai",
    summary="Parse document with OmniAI and return page-numbered chunks",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
)
async def omniai(file: UploadFile = File(...)):
    """
    Parse an uploaded document using OmniAI and return text chunks with page numbers.
    Input: document types supported by the service (e.g., PDF/PPT)
    Output: [(text, page_number), ...]
    """
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

        try:
            result = await omniai_service(tmp_path)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
