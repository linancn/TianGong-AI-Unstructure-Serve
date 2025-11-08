from types import SimpleNamespace

import pytest

from minio.error import S3Error

from src.services import minio_storage


def test_parse_minio_endpoint_plain():
    endpoint, secure = minio_storage.parse_minio_endpoint("minio.local:9000")
    assert endpoint == "minio.local:9000"
    assert secure is False


def test_parse_minio_endpoint_https():
    endpoint, secure = minio_storage.parse_minio_endpoint("https://minio.local:9000")
    assert endpoint == "minio.local:9000"
    assert secure is True


def test_parse_minio_endpoint_invalid():
    with pytest.raises(ValueError):
        minio_storage.parse_minio_endpoint("")


def test_prepare_object_download_success():
    class FakeResponse:
        def __init__(self, chunks):
            self._chunks = chunks

        def stream(self, chunk_size):
            for chunk in self._chunks:
                yield chunk

        def close(self):
            pass

        def release_conn(self):
            pass

    class FakeClient:
        def stat_object(self, bucket, object_name):
            assert bucket == "bucket"
            assert object_name == "object"
            return SimpleNamespace(size=5, content_type="text/plain", etag="etag123")

        def get_object(self, bucket, object_name):
            assert bucket == "bucket"
            assert object_name == "object"
            return FakeResponse([b"abc", b"def"])

    stream_iter, info = minio_storage.prepare_object_download(FakeClient(), "bucket", "object")
    assert list(stream_iter) == [b"abc", b"def"]
    assert info.object_name == "object"
    assert info.size == 5
    assert info.content_type == "text/plain"
    assert info.etag == "etag123"


def test_prepare_object_download_not_found():
    class FakeClient:
        def stat_object(self, *_args, **_kwargs):
            raise S3Error(
                response=None,
                code="NoSuchKey",
                message="missing",
                resource="object",
                request_id=None,
                host_id=None,
            )

    with pytest.raises(minio_storage.MinioObjectNotFound):
        minio_storage.prepare_object_download(FakeClient(), "bucket", "object")
