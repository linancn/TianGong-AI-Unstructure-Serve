from typing import List, Optional, Tuple

from pydantic import BaseModel


class TextElementWithPageNum(BaseModel):
    text: str
    page_number: int


class ResponseWithPageNum(BaseModel):
    result: List[TextElementWithPageNum]

    @classmethod
    def from_result(cls, result: List[Tuple[str, int]]):
        items = [TextElementWithPageNum(text=item[0], page_number=item[1]) for item in result]
        return cls(result=items)


class TextElementWithoutPageNum(BaseModel):
    text: str


class ResponseWithoutPageNum(BaseModel):
    result: List[TextElementWithoutPageNum]

    @classmethod
    def from_result(cls, result: List[Tuple[str, int]]):
        items = [TextElementWithoutPageNum(text=item) for item in result]
        return cls(result=items)


class MinioPageImage(BaseModel):
    page_number: int
    object_name: str


class MinioAssetSummary(BaseModel):
    bucket: str
    prefix: Optional[str] = None
    pdf_object: str
    json_object: str
    page_images: List[MinioPageImage]


class InsertSummary(BaseModel):
    """Response model summarizing a Weaviate insertion."""

    doc_id: str
    inserted_chunks: int
    collection: str
    source: str
    has_page_numbers: bool
    minio_assets: Optional[MinioAssetSummary] = None
