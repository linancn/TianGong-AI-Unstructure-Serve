import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.models.models import ResponseWithoutPageNum
from src.services.docx_service import unstructure_docx

router = APIRouter()


@router.post(
    "/docx",
    summary="Extract plain text chunks from DOCX (no page numbers)",
    response_model=ResponseWithoutPageNum,
    response_description="List of text chunks (no page numbers)",
)
async def docx(file: UploadFile = File(...)):
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
            return ResponseWithoutPageNum.from_result(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
