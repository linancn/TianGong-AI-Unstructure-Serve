import os
import tempfile
from magic_pdf.data.data_reader_writer import FileBasedDataWriter, FileBasedDataReader
from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.config.enums import SupportedPdfParseMethod

from src.models.models import ResponseWithPageNum, TextElementWithPageNum


def image_text(item):
    return "\n".join([*item.get("img_caption", []), *item.get("img_footnote", [])])


def mineru_service(file_path):
    # read bytes
    reader = FileBasedDataReader("")
    pdf_bytes = reader.read(file_path)

    # dataset
    ds = PymuDocDataset(pdf_bytes)

    with tempfile.TemporaryDirectory() as tmp_dir:
        image_writer = FileBasedDataWriter(tmp_dir)
        image_dir = os.path.basename(tmp_dir)
        if ds.classify() == SupportedPdfParseMethod.OCR:
            infer_result = ds.apply(doc_analyze, ocr=True)
            pipe_result = infer_result.pipe_ocr_mode(image_writer)
        else:
            infer_result = ds.apply(doc_analyze, ocr=False)
            pipe_result = infer_result.pipe_txt_mode(image_writer)

        # 传 image_dir_or_bucket_prefix
        content_list_content = pipe_result.get_content_list(image_dir)

        response = ResponseWithPageNum(
            result=[
                TextElementWithPageNum(
                    text=(
                        item["text"] if item["type"] in ("text", "equation") else image_text(item)
                    ),
                    page_number=item["page_idx"] + 1,
                )
                for item in content_list_content
                if (
                    (item["type"] in ("text", "equation") and item.get("text", "").strip())
                    or (
                        item["type"] == "image"
                        and (item.get("img_caption") or item.get("img_footnote"))
                    )
                )
            ]
        )

        return response
