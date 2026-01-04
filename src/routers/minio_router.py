import base64
import binascii
import mimetypes
import os
import re
from typing import Optional, Tuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from src.services.minio_storage import (
    MinioConfig,
    MinioObjectNotFound,
    MinioStorageError,
    create_client,
    ensure_bucket,
    parse_minio_endpoint,
    prepare_object_download,
    upload_bytes,
)

router = APIRouter()

_COLLECTION_NAME_RE = re.compile(r"^[A-Z][_0-9A-Za-z]*$")


def build_storage_collection_name(base: str, user_id: str) -> str:
    """
    Build a sanitized collection namespace for MinIO operations.

    The output:
    - starts with an uppercase letter
    - uses only letters/numbers/underscores
    - prefixes user and collection with KB_ for consistency with previous storage paths
    """
    if not base:
        base = "KB"
    base_clean = re.sub(r"[^0-9A-Za-z_]", "_", base).upper() or "KB"

    uid_clean = re.sub(r"[^0-9A-Za-z_]", "_", user_id).upper()

    name = f"KB_{uid_clean}_{base_clean}"

    if len(name) > 200:
        name = name[:200]

    if not _COLLECTION_NAME_RE.match(name):
        raise ValueError(f"Illegal collection name after sanitation: {name}")
    return name


def _create_minio_context(
    address: str,
    access_key: str,
    secret_key: str,
    bucket: str,
) -> Tuple[MinioConfig, object]:
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


def _build_object_name(collection: str, object_path: str) -> str:
    normalized_path = object_path.strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail="object_path must not be empty.")

    normalized_path = normalized_path.lstrip("/")
    if normalized_path.startswith(f"{collection}/"):
        return normalized_path
    return f"{collection}/{normalized_path}"


@router.post(
    "/minio/download",
    summary="Download a stored file from MinIO",
    response_description="Binary stream of the requested object",
)
async def download_minio_file(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    minio_address: str = Form(
        ..., description="MinIO server address, e.g. https://minio.local:9000"
    ),
    minio_access_key: str = Form(..., description="MinIO access key"),
    minio_secret_key: str = Form(..., description="MinIO secret key"),
    minio_bucket: str = Form(..., description="Target MinIO bucket name"),
    object_path: str = Form(
        ..., description="Path of the object to download (relative to the collection)"
    ),
):
    try:
        safe_collection = build_storage_collection_name(collection_name, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cfg, client = _create_minio_context(
        minio_address,
        minio_access_key,
        minio_secret_key,
        minio_bucket,
    )

    object_name = _build_object_name(safe_collection, object_path)

    try:
        stream, info = prepare_object_download(client, cfg.bucket, object_name)
    except MinioObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MinioStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to download MinIO object: {exc}"
        ) from exc

    filename = os.path.basename(info.object_name) or "download.bin"
    media_type = (
        info.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    if info.size is not None:
        headers["Content-Length"] = str(info.size)
    if info.etag:
        headers["ETag"] = info.etag

    return StreamingResponse(stream, media_type=media_type, headers=headers)


def _upload_data_to_minio(
    *,
    collection_name: str,
    user_id: str,
    minio_address: str,
    minio_access_key: str,
    minio_secret_key: str,
    minio_bucket: str,
    object_path: str,
    data: bytes,
    content_type: Optional[str],
    filename_hint: Optional[str],
):
    if not data:
        raise HTTPException(status_code=400, detail="File content must not be empty.")

    try:
        safe_collection = build_storage_collection_name(collection_name, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cfg, client = _create_minio_context(
        minio_address,
        minio_access_key,
        minio_secret_key,
        minio_bucket,
    )

    object_name = _build_object_name(safe_collection, object_path)

    resolved_content_type = (
        content_type
        or mimetypes.guess_type(filename_hint or object_name)[0]
        or "application/octet-stream"
    )

    try:
        upload_bytes(
            client,
            cfg.bucket,
            object_name,
            data,
            content_type=resolved_content_type,
        )
    except MinioStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Failed to upload MinIO object: {exc}"
        ) from exc

    return {
        "bucket": cfg.bucket,
        "object_name": object_name,
        "size": len(data),
        "content_type": resolved_content_type,
    }


@router.post(
    "/minio/upload",
    summary="Upload an object to MinIO",
    response_description="Metadata about the stored object",
)
async def upload_minio_file(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    minio_address: str = Form(
        ..., description="MinIO server address, e.g. https://minio.local:9000"
    ),
    minio_access_key: str = Form(..., description="MinIO access key"),
    minio_secret_key: str = Form(..., description="MinIO secret key"),
    minio_bucket: str = Form(..., description="Target MinIO bucket name"),
    object_path: str = Form(
        ..., description="Path where the object will be stored (relative to the collection)"
    ),
    file: UploadFile = File(..., description="Binary file to upload"),
):
    data = await file.read()
    if data is None:
        raise HTTPException(status_code=400, detail="Failed to read uploaded file.")

    return _upload_data_to_minio(
        collection_name=collection_name,
        user_id=user_id,
        minio_address=minio_address,
        minio_access_key=minio_access_key,
        minio_secret_key=minio_secret_key,
        minio_bucket=minio_bucket,
        object_path=object_path,
        data=data,
        content_type=file.content_type,
        filename_hint=file.filename,
    )


@router.post(
    "/minio/upload/base64",
    summary="Upload an object to MinIO via Base64 payload",
    response_description="Metadata about the stored object",
)
async def upload_minio_file_base64(
    collection_name: str = Form(...),
    user_id: str = Form(...),
    minio_address: str = Form(
        ..., description="MinIO server address, e.g. https://minio.local:9000"
    ),
    minio_access_key: str = Form(..., description="MinIO access key"),
    minio_secret_key: str = Form(..., description="MinIO secret key"),
    minio_bucket: str = Form(..., description="Target MinIO bucket name"),
    object_path: str = Form(
        ..., description="Path where the object will be stored (relative to the collection)"
    ),
    file_base64: str = Form(..., description="Base64-encoded file content"),
    content_type_override: Optional[str] = Form(
        None, description="Explicit content type for the uploaded file"
    ),
):
    try:
        data = base64.b64decode(file_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64-encoded file content.") from exc

    return _upload_data_to_minio(
        collection_name=collection_name,
        user_id=user_id,
        minio_address=minio_address,
        minio_access_key=minio_access_key,
        minio_secret_key=minio_secret_key,
        minio_bucket=minio_bucket,
        object_path=object_path,
        data=data,
        content_type=content_type_override,
        filename_hint=None,
    )
