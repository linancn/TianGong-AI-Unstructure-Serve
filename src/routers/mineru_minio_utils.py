import os
import re
import unicodedata
from typing import Optional, Sequence, Tuple

from fastapi import HTTPException

from src.models.models import MinioAssetSummary, MinioPageImage
from src.services.minio_storage import (
    MinioConfig,
    MinioStorageError,
    clear_prefix,
    create_client,
    ensure_bucket,
    parse_minio_endpoint,
    upload_bytes,
    upload_pdf_bundle,
)

MINIO_PREFIX_ROOT = "mineru"
MinioContext = Optional[Tuple[MinioConfig, object]]
_ALLOWED_PREFIX_SPECIAL_CHARS = {
    "/",
    "_",
    "-",
    "—",
    "–",
    "·",
    "，",
    "。",
    "、",
    "（",
    "）",
    "【",
    "】",
    "《",
    "》",
}


def initialize_minio_context(
    save_to_minio: bool,
    address: Optional[str],
    access_key: Optional[str],
    secret_key: Optional[str],
    bucket: Optional[str],
) -> MinioContext:
    if not save_to_minio:
        return None

    required = {
        "minio_address": address,
        "minio_access_key": access_key,
        "minio_secret_key": secret_key,
        "minio_bucket": bucket,
    }
    missing = [key for key, value in required.items() if not value or not value.strip()]
    if missing:
        joined = ", ".join(missing)
        raise HTTPException(status_code=400, detail=f"Missing MinIO field(s): {joined}")

    assert address is not None  # for mypy
    assert access_key is not None
    assert secret_key is not None
    assert bucket is not None

    try:
        endpoint, secure = parse_minio_endpoint(address)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cfg = MinioConfig(
        endpoint=endpoint,
        access_key=access_key.strip(),
        secret_key=secret_key.strip(),
        bucket=bucket.strip(),
        secure=secure,
    )

    try:
        client = create_client(cfg)
        ensure_bucket(client, cfg.bucket)
    except MinioStorageError as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to prepare MinIO bucket: {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Failed to initialize MinIO client: {exc}"
        ) from exc

    return cfg, client


def _normalize_prefix_component(raw: str) -> str:
    if not raw:
        return ""

    result: list[str] = []

    for ch in raw:
        if ch in _ALLOWED_PREFIX_SPECIAL_CHARS:
            result.append(ch)
            continue

        if ch.isspace():
            replacement = "_"
        else:
            category = unicodedata.category(ch)
            if category and category[0] in {"L", "N"}:
                result.append(ch)
                continue
            replacement = "_"

        if replacement == "_" and result and result[-1] == "_":
            continue
        result.append(replacement)

    cleaned = "".join(result)
    cleaned = re.sub(r"/{2,}", "/", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("/_")


def build_minio_prefix(filename: str, custom_prefix: Optional[str]) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    base_clean = _normalize_prefix_component(base) or "document"

    if custom_prefix:
        custom_clean = _normalize_prefix_component(custom_prefix)
        if custom_clean:
            return f"{custom_clean}/{base_clean}"

    return f"{MINIO_PREFIX_ROOT}/{base_clean}"


def upload_pdf_assets(
    ctx: MinioContext,
    prefix: str,
    pdf_path: str,
    chunks_with_pages: Sequence[Tuple[str, int, Optional[str]]],
) -> MinioAssetSummary:
    if ctx is None:
        raise RuntimeError("MinIO context is required to upload assets.")
    cfg, client = ctx

    try:
        clear_prefix(client, cfg.bucket, prefix)
    except MinioStorageError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to clear existing MinIO objects: {exc}"
        ) from exc

    payload_for_json = []
    for text, page_number, element_type in chunks_with_pages:
        payload_entry = {"text": text, "page_number": page_number}
        if element_type:
            payload_entry["type"] = element_type
        payload_for_json.append(payload_entry)
    try:
        record = upload_pdf_bundle(
            client,
            cfg=cfg,
            prefix=prefix,
            pdf_path=pdf_path,
            parsed_payload=payload_for_json,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to upload assets to MinIO: {exc}"
        ) from exc

    return MinioAssetSummary(
        bucket=record.bucket,
        prefix=record.prefix,
        pdf_object=record.pdf_object,
        json_object=record.json_object,
        page_images=[
            MinioPageImage(page_number=page, object_name=obj_name)
            for page, obj_name in record.page_images
        ],
    )


def upload_meta_text(ctx: MinioContext, prefix: str, meta_text: str) -> str:
    if ctx is None:
        raise RuntimeError("MinIO context is required to upload meta.txt.")

    cfg, client = ctx
    normalized_prefix = prefix.strip("/")
    object_prefix = f"{normalized_prefix}/" if normalized_prefix else ""
    object_name = f"{object_prefix}meta.txt"
    data = meta_text.encode("utf-8")

    try:
        upload_bytes(
            client,
            cfg.bucket,
            object_name,
            data,
            content_type="text/plain; charset=utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to upload MinIO meta.txt: {exc}"
        ) from exc

    return object_name


__all__ = [
    "MINIO_PREFIX_ROOT",
    "MinioContext",
    "initialize_minio_context",
    "build_minio_prefix",
    "upload_pdf_assets",
    "upload_meta_text",
]
