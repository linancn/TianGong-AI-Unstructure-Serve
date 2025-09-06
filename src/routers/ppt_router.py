import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum
from src.services.ppt_service import unstructure_ppt

router = APIRouter()


@router.post(
    "/ppt",
    summary="Extract text from PowerPoint and return page/slide-numbered chunks",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
)
async def ppt(file: UploadFile = File(...)):
    """
    Extract text from PowerPoint slides and return chunks with page/slide numbers.

    Input: .ppt/.pptx file
    Output: [(text, page_number), ...]
    """
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

        try:
            result = unstructure_ppt(tmp_path)
            return ResponseWithPageNum.from_result(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
