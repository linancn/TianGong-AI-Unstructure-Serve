import os
from typing import List, Optional

from src.config.config import VLLM_API_KEY, VLLM_BASE_URL, VLLM_BASE_URLS
from src.services.vision_service_openai_compatible import (
    OpenAICompatibleClientPool,
    vision_completion_openai_compatible,
)

DEFAULT_VISION_MODEL = "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8"
_FALLBACK_API_KEY = "not-required"


def _resolve_api_key() -> str:
    env_override = os.getenv("VLLM_API_KEY")
    if env_override:
        return env_override
    if VLLM_API_KEY:
        return VLLM_API_KEY
    return ""


def _parse_base_urls(raw_value: Optional[str]) -> List[str]:
    if not raw_value:
        return []
    parts = [item.strip() for item in raw_value.split(",")]
    return [item for item in parts if item]


def _resolve_base_urls() -> List[str]:
    env_override = os.getenv("VLLM_BASE_URLS") or os.getenv("VLLM_BASE_URL")
    urls = _parse_base_urls(env_override)
    if urls:
        return urls
    urls = _parse_base_urls(VLLM_BASE_URLS)
    if urls:
        return urls
    return _parse_base_urls(VLLM_BASE_URL)


def _has_configured_api_key() -> bool:
    env_override = os.getenv("VLLM_API_KEY")
    if env_override and env_override.strip():
        return True
    if VLLM_API_KEY and VLLM_API_KEY.strip():
        return True
    return False


def has_vllm_credentials() -> bool:
    return bool(_resolve_base_urls() or _has_configured_api_key())


_CLIENT_POOL = OpenAICompatibleClientPool(
    api_key=_resolve_api_key(),
    base_urls=_resolve_base_urls(),
    fallback_api_key=_FALLBACK_API_KEY,
)


def vision_completion_vllm(
    image_path: str,
    context: str = "",
    model: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    if not _CLIENT_POOL.has_clients():
        raise RuntimeError(
            "vLLM vision client is not configured. Set VLLM_BASE_URLS / VLLM_BASE_URL"
            " (comma-separated) or VLLM_API_KEY."
        )
    return vision_completion_openai_compatible(
        image_path,
        context=context,
        model=model,
        prompt=prompt,
        default_model=DEFAULT_VISION_MODEL,
        client_pool=_CLIENT_POOL,
    )
