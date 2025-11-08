import concurrent.futures
import importlib
import importlib.util
import os
import sys
import types

import pytest
from fastapi.testclient import TestClient


def _ensure_stub_modules():
    """Install lightweight stand-ins for optional third-party dependencies."""

    if importlib.util.find_spec("minio") is None and "minio" not in sys.modules:
        minio_module = types.ModuleType("minio")

        class DummyMinio:
            def __init__(self, *args, **kwargs):
                pass

            def bucket_exists(self, *_args, **_kwargs):
                return True

            def make_bucket(self, *_args, **_kwargs):
                return None

            def list_objects(self, *_args, **_kwargs):
                return []

            def remove_object(self, *_args, **_kwargs):
                return None

            def put_object(self, *_args, **_kwargs):
                return None

            def fput_object(self, *_args, **_kwargs):
                return None

            def stat_object(self, *_args, **_kwargs):
                raise RuntimeError("stat_object not supported in stub")

            def get_object(self, *_args, **_kwargs):
                raise RuntimeError("get_object not supported in stub")

        error_module = types.ModuleType("minio.error")

        class DummyS3Error(Exception):
            def __init__(self, code, message="", resource=None):
                super().__init__(message)
                self.code = code
                self.message = message
                self.resource = resource

        error_module.S3Error = DummyS3Error
        minio_module.Minio = DummyMinio
        minio_module.error = error_module

        sys.modules["minio"] = minio_module
        sys.modules["minio.error"] = error_module

    if importlib.util.find_spec("pypdfium2") is None and "pypdfium2" not in sys.modules:
        pdfium_module = types.ModuleType("pypdfium2")

        class DummyPdfDocument:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("pypdfium2 PdfDocument stub invoked during tests.")

        pdfium_module.PdfDocument = DummyPdfDocument
        sys.modules["pypdfium2"] = pdfium_module


_ensure_stub_modules()


@pytest.fixture(scope="session")
def app():
    """Provide a FastAPI app instance with lightweight GPU scheduler stubs."""

    os.environ["FASTAPI_AUTH"] = "false"
    os.environ.setdefault("GPU_IDS", "0")

    original_executor = concurrent.futures.ProcessPoolExecutor
    _ensure_stub_modules()

    class DummyProcessPoolExecutor:
        """Minimal stand-in to avoid spawning real worker processes during tests."""

        def __init__(self, *args, **kwargs):
            pass

        def submit(self, fn, *args, **kwargs):
            future = concurrent.futures.Future()
            future.set_result({"result": []})
            return future

        def shutdown(self, wait: bool = True):
            pass

    concurrent.futures.ProcessPoolExecutor = DummyProcessPoolExecutor
    for module_name in ("src.main", "src.services.gpu_scheduler", "src.config.config"):
        sys.modules.pop(module_name, None)

    try:
        module = importlib.import_module("src.main")
        yield module.app
    finally:
        concurrent.futures.ProcessPoolExecutor = original_executor
        for module_name in ("src.main", "src.services.gpu_scheduler", "src.config.config"):
            sys.modules.pop(module_name, None)


@pytest.fixture(scope="session")
def client(app):
    """Provide a reusable TestClient bound to the FastAPI app."""

    with TestClient(app) as test_client:
        yield test_client
