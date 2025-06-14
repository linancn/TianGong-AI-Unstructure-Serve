import os
import tempfile
import re
from src.services.mineru_service_full import parse_doc

from src.models.models import ResponseWithPageNum, TextElementWithPageNum


def clean_text(text):
    """Clean text to remove surrogate characters and other problematic encodings"""
    if not text:
        return ""

    # Remove surrogate characters
    text = re.sub(r"[\ud800-\udfff]", "", text)

    # Encode to utf-8 and decode, replacing errors
    try:
        text = text.encode("utf-8", errors="ignore").decode("utf-8")
    except UnicodeError:
        text = text.encode("ascii", errors="ignore").decode("ascii")

    return text


def image_text(item):
    captions = item.get("img_caption") or []
    footnotes = item.get("img_footnote") or []
    combined_text = "\n".join([*captions, *footnotes])
    return clean_text(combined_text)


def table_text(item):
    text_parts = [
        "\n".join(item.get("table_caption", [])),
        item.get("table_body", ""),
        "\n".join(item.get("table_footnote", [])),
    ]
    combined_text = "\n".join(filter(None, text_parts))
    return clean_text(combined_text)


def mineru_service(file_path):

    with tempfile.TemporaryDirectory() as tmp_dir:
        content_list_content = parse_doc([file_path], tmp_dir)
        response = ResponseWithPageNum(
            result=[
                TextElementWithPageNum(
                    text=(
                        clean_text(item["text"])
                        if item["type"] in ("text", "equation")
                        else table_text(item) if item["type"] == "table" else image_text(item)
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
                    or (
                        item["type"] == "table"
                        and (
                            item.get("table_caption")
                            or item.get("table_body")
                            or item.get("table_footnote")
                        )
                    )
                )
            ]
        )

        return response
