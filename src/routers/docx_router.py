import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from src.models.models import ResponseWithoutPageNum
from src.services.docx_service import unstructure_docx
from src.utils.response_utils import json_response, pretty_response_flag

router = APIRouter()


@router.post(
    "/docx",
    summary="Extract plain text chunks from DOCX (no page numbers)",
    response_model=ResponseWithoutPageNum,
    response_description="List of text chunks (no page numbers)",
)
async def docx(
    file: UploadFile = File(...),
    pretty: bool = Depends(pretty_response_flag),
):
    """
    Extract plain-text chunks from an uploaded .docx file.

    Input: .docx file
    Output: list of text chunks (no page numbers)
    """
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

        try:
            result = unstructure_docx(tmp_path)
            response_model = ResponseWithoutPageNum.from_result(result)
            return json_response(response_model, pretty)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
