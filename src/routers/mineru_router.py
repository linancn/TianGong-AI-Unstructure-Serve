import tempfile
import os
from fastapi import APIRouter, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum
from src.services.mineru_service import mineru_service

router = APIRouter()

# List of allowed file extensions
ALLOWED_EXTENSIONS = [".pdf", ".png", ".jpeg", ".jpg"]


@router.post(
    "/mineru",
    response_model=ResponseWithPageNum,
    response_description="List of chunks with page numbers.",
)
async def mineru(file: UploadFile = File(...)):
    """
    This endpoint allows you to extract text from a document by MinerU.
    Only PDF, PNG, JPEG, and JPG files are accepted.
    """
    # Get file extension
    _, file_ext = os.path.splitext(file.filename)
    file_ext = file_ext.lower()

    # Check if file extension is allowed
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    with tempfile.NamedTemporaryFile(suffix=file_ext, delete=True) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

        try:
            result = mineru_service(tmp_path)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
