import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.models.models import ResponseWithPageNum
from src.services.mineru_with_images_service import mineru_service

router = APIRouter()


@router.post(
    "/mineru_with_images",
    response_model=ResponseWithPageNum,
    response_description="List of chunks with page numbers.",
)
async def mineru_with_images(file: UploadFile = File(...)):
    """
    This endpoint allows you to extract text from a document with images by MinerU.
    """
    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

        try:
            result = mineru_service(tmp_path)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
