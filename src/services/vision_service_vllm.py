import os
from typing import Any, Dict, List, Optional

from loguru import logger

from src.config.config import VLLM_API_KEY, VLLM_BASE_URL, VLLM_BASE_URLS
from src.services.vision_service_openai_compatible import (
    OpenAICompatibleClientPool,
    vision_completion_openai_compatible,
)

DEFAULT_VISION_MODEL = "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8"
_FALLBACK_API_KEY = "not-required"
_ENABLE_THINKING_ENV = "VLLM_ENABLE_THINKING"
_TEMPERATURE_ENV = "VLLM_VISION_TEMPERATURE"
_TOP_P_ENV = "VLLM_VISION_TOP_P"
_TOP_K_ENV = "VLLM_VISION_TOP_K"
_MIN_P_ENV = "VLLM_VISION_MIN_P"
_PRESENCE_PENALTY_ENV = "VLLM_VISION_PRESENCE_PENALTY"
_REPETITION_PENALTY_ENV = "VLLM_VISION_REPETITION_PENALTY"

_DEFAULT_TEMPERATURE = 1.0
_DEFAULT_TOP_P = 1.0
_DEFAULT_TOP_K = 40
_DEFAULT_MIN_P = 0.0
_DEFAULT_PRESENCE_PENALTY = 2.0
_DEFAULT_REPETITION_PENALTY = 1.0


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


def _env_enable_thinking() -> bool:
    raw_value = os.getenv(_ENABLE_THINKING_ENV)
    if raw_value is None:
        return False
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(var_name: str, default: float) -> float:
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default
    try:
        return float(raw_value.strip())
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s=%s, falling back to default %s.",
            var_name,
            raw_value,
            default,
        )
        return default


def _env_positive_int(var_name: str, default: int) -> int:
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value.strip())
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s=%s, falling back to default %s.",
            var_name,
            raw_value,
            default,
        )
        return default
    if parsed <= 0:
        logger.warning(
            "Invalid %s=%s, falling back to default %s.",
            var_name,
            raw_value,
            default,
        )
        return default
    return parsed


def _build_request_options() -> Dict[str, float]:
    return {
        "temperature": _env_float(_TEMPERATURE_ENV, _DEFAULT_TEMPERATURE),
        "top_p": _env_float(_TOP_P_ENV, _DEFAULT_TOP_P),
        "presence_penalty": _env_float(_PRESENCE_PENALTY_ENV, _DEFAULT_PRESENCE_PENALTY),
    }


def _build_extra_body() -> Dict[str, Any]:
    return {
        "top_k": _env_positive_int(_TOP_K_ENV, _DEFAULT_TOP_K),
        "min_p": _env_float(_MIN_P_ENV, _DEFAULT_MIN_P),
        "repetition_penalty": _env_float(_REPETITION_PENALTY_ENV, _DEFAULT_REPETITION_PENALTY),
        "chat_template_kwargs": {"enable_thinking": _env_enable_thinking()},
    }


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
        extra_body=_build_extra_body(),
        request_options=_build_request_options(),
    )
