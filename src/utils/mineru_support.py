from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Set

_DEFAULT_EXTENSIONS: Set[str] = {".pdf", ".png", ".jpeg", ".jpg"}


def _normalize_extension(value: str) -> str:
    value = value.strip().lower()
    if not value.startswith("."):
        value = f".{value}"
    return value


def _collect_from_iterable(items: Iterable[str]) -> Set[str]:
    normalized: Set[str] = set()
    for item in items:
        if isinstance(item, str):
            normalized.add(_normalize_extension(item))
    return normalized


def _collect_from_value(value) -> Set[str]:
    if isinstance(value, dict):
        return _collect_from_iterable(value.keys())
    if isinstance(value, (list, tuple, set, frozenset)):
        return _collect_from_iterable(value)
    return set()


@lru_cache()
def mineru_supported_extensions() -> Set[str]:
    """
    Return the set of file extensions accepted by MinerU.

    Falls back to a conservative default when MinerU metadata is unavailable.
    """
    try:
        import mineru.cli.common as mineru_common  # type: ignore
    except Exception:
        return set(_DEFAULT_EXTENSIONS)

    collected: Set[str] = set()

    attr_names = [
        name
        for name in dir(mineru_common)
        if any(keyword in name.lower() for keyword in ("suffix", "ext", "extension"))
    ]

    for name in attr_names:
        try:
            value = getattr(mineru_common, name)
        except Exception:
            continue
        collected |= _collect_from_value(value)

    if not collected:
        for fallback_name in ("READ_FN_MAPPING", "SUFFIX_FN_MAPPING", "suffix_to_read_fn"):
            collected |= _collect_from_value(getattr(mineru_common, fallback_name, None))

    return collected or set(_DEFAULT_EXTENSIONS)


def format_supported_extensions() -> str:
    """Return a comma-separated string of supported MinerU file extensions."""
    return ", ".join(sorted(mineru_supported_extensions()))


__all__ = ["mineru_supported_extensions", "format_supported_extensions"]
