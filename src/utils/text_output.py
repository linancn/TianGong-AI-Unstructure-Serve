from __future__ import annotations

from typing import Iterable, Mapping, Optional


def _extract_text_and_type(item) -> tuple[str, Optional[str]]:
    """Extract text and type metadata from either mapping or object-like chunk."""
    if isinstance(item, Mapping):
        raw_text = item.get("text")
        item_type = item.get("type")
    else:
        raw_text = getattr(item, "text", None)
        item_type = getattr(item, "type", None)

    text = (raw_text or "").strip()
    if not text:
        return "", None

    if isinstance(item_type, str) and item_type.strip():
        return text, item_type.strip()
    return text, None


def build_plain_text(chunks: Iterable[object]) -> str:
    """Compose a plain-text export from parsed MinerU chunks.

    Titles receive a double newline suffix, regular text gets a single newline.
    """
    parts: list[str] = []
    for chunk in chunks:
        text, chunk_type = _extract_text_and_type(chunk)
        if not text:
            continue

        if chunk_type == "title":
            parts.append(f"{text}\n\n")
        else:
            parts.append(f"{text}\n")

    return "".join(parts).rstrip("\n")


__all__ = ["build_plain_text"]
