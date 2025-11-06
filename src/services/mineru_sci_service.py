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


def list_text(item):
    list_items = item.get("list_items") or []
    if list_items:
        combined_text = "\n".join(list_items)
    else:
        combined_text = item.get("text", "")
    return clean_text(combined_text)


filter_patterns = [
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*acknowledgements?\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*acknowledgments?\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*author\s+contributions?\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*bibliography\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*conflict\s+of\s+interest\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*credit\s+authorship\s+contribution\s+statement\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*data\s+availability\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*declaration\s+of\s+competing\s+interest\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*declaration\s+of\s+interests?\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*declarations?\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*literature\s+cited\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*online\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*r\s+e\s+f\s+e\s+r\s+e\s+n\s+c\s+e\s+s\s*[:\.]?\s*$",
    r"^\s*([ivxlcdm]+\.?|\d+\.?|\w+\.?)?\s*references?\s*[:\.]?\s*$",
]


def is_filtered_section(text):
    """Check if the text matches any of the filter patterns"""
    if not text:
        return False

    text_normalized = text.strip().lower()
    return any(re.match(pattern, text_normalized, re.IGNORECASE) for pattern in filter_patterns)


def filter_references(content_list):
    """Remove References section and everything until next text_level element"""
    filtered_content = []
    skip_until_next_level = False

    for item in content_list:
        # Check if this is a filtered section heading
        if item.get("text_level") is not None and is_filtered_section(item.get("text", "")):
            skip_until_next_level = True
            continue

        # If we're skipping and encounter another text_level element, stop skipping
        if skip_until_next_level and item.get("text_level") is not None:
            skip_until_next_level = False

        # Add item if we're not skipping
        if not skip_until_next_level:
            filtered_content.append(item)

    return filtered_content


def mineru_service(file_path):

    with tempfile.TemporaryDirectory() as tmp_dir:
        content_list_content, _ = parse_doc([file_path], tmp_dir)
        content_list_content = filter_references(content_list_content)

        response = ResponseWithPageNum(
            result=[
                TextElementWithPageNum(
                    text=(
                        clean_text(item["text"])
                        if item["type"] in ("text", "equation")
                        else (
                            list_text(item)
                            if item["type"] == "list"
                            else table_text(item) if item["type"] == "table" else image_text(item)
                        )
                    ),
                    page_number=item["page_idx"] + 1,
                )
                for item in content_list_content
                if (
                    (item["type"] in ("text", "equation") and item.get("text", "").strip())
                    or (
                        item["type"] == "list"
                        and (
                            any(text.strip() for text in item.get("list_items", []))
                            or item.get("text", "").strip()
                        )
                    )
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
