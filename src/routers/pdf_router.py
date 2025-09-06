import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum
from src.services.pdf_service import unstructure_pdf

router = APIRouter()


@router.post(
    "/pdf",
    summary="Extract page-numbered text chunks from PDF",
    response_model=ResponseWithPageNum,
    response_description="List of text chunks with page numbers",
)
async def pdf(file: UploadFile = File(...)):
    """
    Extract text from a PDF and return page-numbered chunks.

    Input: .pdf file
    Output: [(text, page_number), ...]
    """
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

        try:
            result = unstructure_pdf(tmp_path)
            return ResponseWithPageNum.from_result(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
