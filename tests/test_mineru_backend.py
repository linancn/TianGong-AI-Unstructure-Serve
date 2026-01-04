import pytest

from src.utils.mineru_backend import (
    BACKEND_FALLBACKS,
    SUPPORTED_MINERU_BACKENDS,
    normalize_backend,
    resolve_backend,
    resolve_backend_from_env,
)


def test_normalize_backend_accepts_supported_values():
    for value in SUPPORTED_MINERU_BACKENDS:
        assert normalize_backend(value) == value
        # Ensure case-insensitive handling
        assert normalize_backend(value.upper()) == value
    assert normalize_backend("  vlm-http-client  ") == "vlm-http-client"


def test_normalize_backend_none_or_empty():
    assert normalize_backend(None) is None
    assert normalize_backend("") is None
    assert normalize_backend("   ") is None


def test_normalize_backend_rejects_invalid():
    with pytest.raises(ValueError) as excinfo:
        normalize_backend("not-real-backend")
    assert "Unsupported MinerU backend" in str(excinfo.value)


def test_resolve_backend_maps_hybrid_to_vlm():
    for hybrid, target in BACKEND_FALLBACKS.items():
        normalized = normalize_backend(hybrid)
        assert resolve_backend(normalized) == target


def test_resolve_backend_passthrough():
    assert resolve_backend("vlm-http-client") == "vlm-http-client"
    assert resolve_backend(None) is None


def test_resolve_backend_from_env(monkeypatch):
    monkeypatch.setenv("MINERU_DEFAULT_BACKEND", "hybrid-http-client")
    assert resolve_backend_from_env() == "vlm-http-client"

    monkeypatch.setenv("MINERU_DEFAULT_BACKEND", "vlm-transformers")
    assert resolve_backend_from_env() == "vlm-transformers"

    monkeypatch.delenv("MINERU_DEFAULT_BACKEND", raising=False)
    assert resolve_backend_from_env() is None

    monkeypatch.setenv("MINERU_DEFAULT_BACKEND", "bogus-backend")
    with pytest.raises(ValueError):
        resolve_backend_from_env()
