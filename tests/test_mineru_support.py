import sys
import types

import pytest

from src.utils import mineru_support


@pytest.fixture(autouse=True)
def clear_mineru_cache():
    mineru_support.mineru_supported_extensions.cache_clear()
    yield
    mineru_support.mineru_supported_extensions.cache_clear()


def test_mineru_supported_extensions_fallback(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "mineru.cli.common":
            raise ImportError("forced for test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    expected = {".pdf", ".png", ".jpeg", ".jpg"}
    assert mineru_support.mineru_supported_extensions() == expected


def test_mineru_supported_extensions_collects_from_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "mineru", raising=False)
    monkeypatch.delitem(sys.modules, "mineru.cli", raising=False)
    monkeypatch.delitem(sys.modules, "mineru.cli.common", raising=False)

    mineru_pkg = types.ModuleType("mineru")
    mineru_pkg.__path__ = []
    mineru_cli_pkg = types.ModuleType("mineru.cli")
    mineru_cli_pkg.__path__ = []
    mineru_common = types.ModuleType("mineru.cli.common")
    mineru_common.FILE_SUFFIXES = {".pdf", ".docx"}
    mineru_common.extra_extensions = ["png", ".jpg"]

    monkeypatch.setitem(sys.modules, "mineru", mineru_pkg)
    monkeypatch.setitem(sys.modules, "mineru.cli", mineru_cli_pkg)
    monkeypatch.setitem(sys.modules, "mineru.cli.common", mineru_common)

    extensions = mineru_support.mineru_supported_extensions()
    assert extensions == {".docx", ".jpg", ".pdf", ".png"}
    assert mineru_support.format_supported_extensions() == ".docx, .jpg, .pdf, .png"
