import os
from typing import Optional

# Supported MinerU backends exposed by the service. Hybrid modes are allowed as inputs
# but are internally mapped to vlm variants because the pinned MinerU 2.7.0 wheel does
# not actually ship hybrid implementations.
SUPPORTED_MINERU_BACKENDS = {
    "pipeline",
    "vlm-transformers",
    "vlm-vllm-engine",
    "vlm-lmdeploy-engine",
    "vlm-http-client",
    "vlm-mlx-engine",
    "hybrid-auto-engine",
    "hybrid-http-client",
}

# Fallback mapping for hybrid entries so that callers can pass hybrid-* while we remain
# on a wheel that lacks hybrid support.
BACKEND_FALLBACKS = {
    "hybrid-http-client": "vlm-http-client",
    "hybrid-auto-engine": "vlm-vllm-engine",
}


def normalize_backend(backend: Optional[str]) -> Optional[str]:
    """Normalize and validate a MinerU backend string.

    Returns the normalized backend (lowercased) or None when empty.
    Raises ValueError for unsupported values.
    """
    if backend is None:
        return None

    candidate = backend.strip()
    if not candidate:
        return None

    candidate = candidate.lower()
    if candidate not in SUPPORTED_MINERU_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_MINERU_BACKENDS))
        raise ValueError(f"Unsupported MinerU backend '{backend}'. Supported values: {supported}")

    return candidate


def resolve_backend(normalized_backend: Optional[str]) -> Optional[str]:
    """Return the actual backend to pass to MinerU (maps hybrid-* to vlm-* fallbacks)."""
    if normalized_backend is None:
        return None
    return BACKEND_FALLBACKS.get(normalized_backend, normalized_backend)


def resolve_backend_from_env() -> Optional[str]:
    """Load MINERU_DEFAULT_BACKEND from env, normalize, and map to runtime backend."""
    raw = os.getenv("MINERU_DEFAULT_BACKEND")
    normalized = normalize_backend(raw)
    return resolve_backend(normalized)
