from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Generator, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import pypdfium2 as pdfium
from minio import Minio
from minio.error import S3Error


@dataclass
class MinioConfig:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool = False


class MinioStorageError(RuntimeError):
    """Raised when MinIO operations fail."""


class MinioObjectNotFound(MinioStorageError):
    """Raised when a requested MinIO object does not exist."""


@dataclass
class MinioAssetRecord:
    bucket: str
    pdf_object: str
    json_object: str
    page_images: List[Tuple[int, str]] = field(default_factory=list)
    prefix: Optional[str] = None


@dataclass
class MinioObjectInfo:
    object_name: str
    size: Optional[int] = None
    content_type: Optional[str] = None
    etag: Optional[str] = None


def parse_minio_endpoint(raw: str) -> Tuple[str, bool]:
    """Return (endpoint, secure) parsed from the user-supplied address."""
    if not raw:
        raise ValueError("MinIO address is required.")

    raw = raw.strip()
    if "://" not in raw:
        return raw, False

    parsed = urlparse(raw)
    endpoint = parsed.netloc or parsed.path
    if not endpoint:
        raise ValueError(f"Invalid MinIO address: {raw}")
    secure = parsed.scheme.lower() == "https"
    return endpoint, secure


def create_client(cfg: MinioConfig) -> Minio:
    return Minio(
        cfg.endpoint,
        access_key=cfg.access_key,
        secret_key=cfg.secret_key,
        secure=cfg.secure,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
    except S3Error as exc:  # pragma: no cover - network path
        # Ignore race where the bucket is created between exists() and make_bucket()
        if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise MinioStorageError(str(exc)) from exc


def clear_prefix(client: Minio, bucket: str, prefix: str) -> None:
    normalized = prefix.strip("/")
    if not normalized:
        raise MinioStorageError("Prefix must not be empty when clearing existing objects.")

    try:
        objects = client.list_objects(bucket, prefix=f"{normalized}/", recursive=True)
        for obj in objects:
            client.remove_object(bucket, obj.object_name)
    except S3Error as exc:  # pragma: no cover - network interactions
        raise MinioStorageError(f"Failed to clear prefix '{prefix}': {exc}") from exc


def upload_bytes(
    client: Minio,
    bucket: str,
    object_name: str,
    data: bytes,
    *,
    content_type: Optional[str] = None,
) -> None:
    stream = io.BytesIO(data)
    size = len(data)
    client.put_object(
        bucket,
        object_name,
        data=stream,
        length=size,
        content_type=content_type,
    )


def upload_file(
    client: Minio,
    bucket: str,
    object_name: str,
    file_path: str,
    *,
    content_type: Optional[str] = None,
) -> None:
    client.fput_object(bucket, object_name, file_path, content_type=content_type)


def iter_pdf_page_jpegs(pdf_path: str, dpi: int = 150) -> Generator[Tuple[int, bytes], None, None]:
    """Yield (1-based page number, JPEG bytes) for each page in the PDF."""
    scale = dpi / 72.0
    doc = pdfium.PdfDocument(pdf_path)
    try:
        total_pages = len(doc)
        for page_index in range(total_pages):
            page = doc[page_index]
            try:
                bitmap = page.render(scale=scale)
                try:
                    pil_image = bitmap.to_pil()
                finally:
                    bitmap.close()
                if pil_image.mode != "RGB":
                    pil_image = pil_image.convert("RGB")
                with io.BytesIO() as buffer:
                    pil_image.save(buffer, format="JPEG", dpi=(dpi, dpi), quality=90)
                    yield page_index + 1, buffer.getvalue()
                pil_image.close()
            finally:
                page.close()
    finally:
        doc.close()


def build_parsed_payload_json(payload: Sequence[dict]) -> bytes:
    return json.dumps(list(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def upload_pdf_bundle(
    client: Minio,
    *,
    cfg: MinioConfig,
    prefix: str,
    pdf_path: str,
    parsed_payload: Sequence[dict],
    dpi: int = 150,
) -> MinioAssetRecord:
    normalized_prefix = prefix.strip("/")
    object_prefix = f"{normalized_prefix}/" if normalized_prefix else ""

    pdf_object = f"{object_prefix}source.pdf"
    upload_file(
        client,
        cfg.bucket,
        pdf_object,
        pdf_path,
        content_type="application/pdf",
    )

    json_object = f"{object_prefix}parsed.json"
    parsed_bytes = build_parsed_payload_json(parsed_payload)
    upload_bytes(
        client,
        cfg.bucket,
        json_object,
        parsed_bytes,
        content_type="application/json",
    )

    page_objects: List[Tuple[int, str]] = []
    for page_number, image_bytes in iter_pdf_page_jpegs(pdf_path, dpi=dpi):
        object_name = f"{object_prefix}pages/page_{page_number:04d}.jpg"
        upload_bytes(
            client,
            cfg.bucket,
            object_name,
            image_bytes,
            content_type="image/jpeg",
        )
        page_objects.append((page_number, object_name))

    return MinioAssetRecord(
        bucket=cfg.bucket,
        pdf_object=pdf_object,
        json_object=json_object,
        page_images=page_objects,
        prefix=normalized_prefix or None,
    )


def prepare_object_download(
    client: Minio,
    bucket: str,
    object_name: str,
    *,
    chunk_size: int = 32 * 1024,
) -> Tuple[Iterable[bytes], MinioObjectInfo]:
    try:
        stat = client.stat_object(bucket, object_name)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject"}:
            raise MinioObjectNotFound(f"Object '{object_name}' does not exist.") from exc
        if exc.code == "NoSuchBucket":
            raise MinioStorageError(f"Bucket '{bucket}' does not exist.") from exc
        raise MinioStorageError(f"Failed to stat MinIO object '{object_name}': {exc}") from exc

    try:
        response = client.get_object(bucket, object_name)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject"}:
            raise MinioObjectNotFound(f"Object '{object_name}' does not exist.") from exc
        raise MinioStorageError(f"Failed to fetch MinIO object '{object_name}': {exc}") from exc

    def stream() -> Generator[bytes, None, None]:
        try:
            for chunk in response.stream(chunk_size):
                if chunk:
                    yield chunk
        finally:
            response.close()
            response.release_conn()

    info = MinioObjectInfo(
        object_name=object_name,
        size=getattr(stat, "size", None),
        content_type=(stat.content_type or None),
        etag=getattr(stat, "etag", None),
    )
    return stream(), info
