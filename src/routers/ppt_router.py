import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum
from src.services.ppt_service import unstructure_ppt
from src.utils.response_utils import json_response, pretty_response_flag

router = APIRouter()


@router.post(
    "/ppt",
    summary="Extract text from PowerPoint and return page/slide-numbered chunks",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
)
async def ppt(
    file: UploadFile = File(...),
    pretty: bool = Depends(pretty_response_flag),
):
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
            response_model = ResponseWithPageNum.from_result(result)
            return json_response(response_model, pretty)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
