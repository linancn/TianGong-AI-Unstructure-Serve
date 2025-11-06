from __future__ import annotations

import re
from typing import List

from src.models.models import TextElementWithPageNum

_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")


def parse_markdown_chunks(
    content: str, *, chunk_type: bool, page_number: int = 1
) -> List[TextElementWithPageNum]:
    """
    Convert a Markdown document into MinerU-style text chunks.

    Headings (#, ##, …) become title chunks when `chunk_type` is True.
    Other paragraphs and list blocks are grouped by blank lines.
    """
    items: List[TextElementWithPageNum] = []
    buffer: List[str] = []

    def flush_buffer() -> None:
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        buffer.clear()
        if not text:
            return
        items.append(TextElementWithPageNum(text=text, page_number=page_number))

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()
        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            flush_buffer()
            heading_text = heading_match.group(2).strip()
            if heading_text:
                element_kwargs = {"text": heading_text, "page_number": page_number}
                if chunk_type:
                    element_kwargs["type"] = "title"
                items.append(TextElementWithPageNum(**element_kwargs))
            continue

        if not stripped:
            flush_buffer()
            continue

        buffer.append(line)

    flush_buffer()

    # If the document had no headings or blank lines, ensure at least one chunk
    if not items and content.strip():
        items.append(TextElementWithPageNum(text=content.strip(), page_number=page_number))

    return items


__all__ = ["parse_markdown_chunks"]
