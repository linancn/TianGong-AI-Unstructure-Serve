import os
from typing import Optional

import toml

config = toml.load(".secrets/secrets.toml")


def _env_override(var_name: str, fallback: Optional[str]) -> Optional[str]:
    """Return a stripped environment override when present, else the fallback."""
    raw = os.getenv(var_name)
    if raw is None:
        return fallback
    stripped = raw.strip()
    return stripped or fallback


def _bool_from_env(var_name: str, default: bool) -> bool:
    """Read boolean flags from the environment while keeping TOML defaults."""
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


FASTAPI_AUTH = _bool_from_env("FASTAPI_AUTH", config["FASTAPI"]["AUTH"])
FASTAPI_BEARER_TOKEN = config["FASTAPI"]["BEARER_TOKEN"]
FASTAPI_MIDDLEWARE_SECRECT_KEY = config["FASTAPI"]["MIDDLEWARE_SECRECT_KEY"]

OPENAI_API_KEY = config["OPENAI"]["API_KEY"]

GENIMI_API_KEY = config["GOOGLE"]["API_KEY"]

VLLM_API_KEY = _env_override("VLLM_API_KEY", config["VLLM"]["API_KEY"])
VLLM_BASE_URL = _env_override("VLLM_BASE_URL", config["VLLM"].get("BASE_URL"))
