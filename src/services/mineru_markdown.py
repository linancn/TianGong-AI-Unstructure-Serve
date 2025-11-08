import re
from typing import Iterable, List, Optional


def _clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    sanitized = re.sub(r"[\ud800-\udfff]", "", text)
    try:
        return sanitized.encode("utf-8", errors="ignore").decode("utf-8")
    except UnicodeError:
        return sanitized.encode("ascii", errors="ignore").decode("ascii")


def _normalize_heading_level(item: dict) -> Optional[int]:
    level = item.get("text_level")
    if level is None and item.get("is_title"):
        level = 0
    try:
        if level is None:
            return None
        return max(0, int(level))
    except (TypeError, ValueError):
        return None


def _heading_line(text: str, level: int) -> str:
    heading_level = max(1, min(level + 1, 6))
    return f"{'#' * heading_level} {text.strip()}"


def _list_block(item: dict) -> Optional[str]:
    list_items = item.get("list_items") or []
    cleaned_items = [_clean_text(entry).strip() for entry in list_items]
    cleaned_items = [entry for entry in cleaned_items if entry]
    if cleaned_items:
        return "\n".join(f"- {entry}" for entry in cleaned_items)

    fallback = _clean_text(item.get("text", "")).strip()
    return fallback or None


def _table_block(item: dict) -> Optional[str]:
    parts: List[str] = []
    captions = item.get("table_caption") or []
    for caption in captions:
        text = _clean_text(caption).strip()
        if text:
            parts.append(text)

    body = _clean_text(item.get("table_body", "")).strip()
    if body:
        parts.append(body)

    footnotes = item.get("table_footnote") or []
    for footnote in footnotes:
        text = _clean_text(footnote).strip()
        if text:
            parts.append(text)

    if parts:
        return "\n\n".join(parts)
    return None


def _image_block(item: dict) -> Optional[str]:
    parts: List[str] = []
    captions = item.get("img_caption") or []
    for caption in captions:
        text = _clean_text(caption).strip()
        if text:
            parts.append(text)

    footnotes = item.get("img_footnote") or []
    for footnote in footnotes:
        text = _clean_text(footnote).strip()
        if text:
            parts.append(text)

    combined = "\n\n".join(parts).strip()
    return combined or None


def _item_to_blocks(item: dict) -> List[str]:
    blocks: List[str] = []
    itype = item.get("type")

    if itype in {"text", "equation"}:
        text = _clean_text(item.get("text", "")).strip()
        if text:
            level = _normalize_heading_level(item)
            if level is not None:
                blocks.append(_heading_line(text, level))
            else:
                blocks.append(text)
    elif itype == "list":
        block = _list_block(item)
        if block:
            level = _normalize_heading_level(item)
            if level is not None:
                heading_text = _clean_text(item.get("text", "")).strip()
                if heading_text:
                    blocks.append(_heading_line(heading_text, level))
                blocks.append(block)
            else:
                blocks.append(block)
    elif itype == "table":
        block = _table_block(item)
        if block:
            blocks.append(block)
    elif itype == "image":
        block = _image_block(item)
        if block:
            blocks.append(block)
    else:
        text = _clean_text(item.get("text", "")).strip()
        if text:
            blocks.append(text)

    return blocks


def build_clean_markdown(content: Iterable[dict]) -> str:
    """Convert MinerU content list into a clean markdown string."""
    blocks: List[str] = []
    for item in content:
        blocks.extend(_item_to_blocks(item))

    filtered_blocks = [block.strip() for block in blocks if block and block.strip()]
    return "\n\n".join(filtered_blocks)
