import importlib
import sys
from typing import Optional, Dict, Any


def _reload_config(
    monkeypatch,
    env_overrides: Optional[Dict[str, Optional[str]]] = None,
    config_override: Optional[Dict[str, Any]] = None,
):
    config_data = config_override or {
        "FASTAPI": {
            "AUTH": True,
            "BEARER_TOKEN": "token",
            "MIDDLEWARE_SECRECT_KEY": "middleware",
        },
        "OPENAI": {"API_KEY": "openai-key"},
        "GOOGLE": {"API_KEY": "google-key"},
        "VLLM": {"API_KEY": "vllm-key", "BASE_URL": "http://default"},
    }

    monkeypatch.setattr("toml.load", lambda _: config_data)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_, **__: None)

    env_overrides = env_overrides or {}
    # Clear environment to avoid leaking real .env values into tests.
    for key in (
        "FASTAPI_AUTH",
        "FASTAPI_BEARER_TOKEN",
        "FASTAPI_MIDDLEWARE_SECRECT_KEY",
        "OPENAI_API_KEY",
        "GENIMI_API_KEY",
        "VLLM_API_KEY",
        "VLLM_BASE_URL",
        "VLLM_BASE_URLS",
    ):
        if key not in env_overrides:
            monkeypatch.delenv(key, raising=False)

    for key, value in env_overrides.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    sys.modules.pop("src.config.config", None)
    return importlib.import_module("src.config.config")


def test_fastapi_auth_env_override(monkeypatch):
    module = _reload_config(monkeypatch, {"FASTAPI_AUTH": "false"})
    assert module.FASTAPI_AUTH is False
    assert module.FASTAPI_BEARER_TOKEN == "token"


def test_vllm_env_override_trims(monkeypatch):
    module = _reload_config(
        monkeypatch,
        {
            "FASTAPI_AUTH": None,
            "VLLM_API_KEY": "  override-key  ",
            "VLLM_BASE_URL": "  ",
        },
    )
    assert module.VLLM_API_KEY == "override-key"
    # When env provides blank string, fallback to TOML value
    assert module.VLLM_BASE_URL == "http://default"


def test_vllm_base_urls_from_toml(monkeypatch):
    config_override = {
        "FASTAPI": {
            "AUTH": True,
            "BEARER_TOKEN": "token",
            "MIDDLEWARE_SECRECT_KEY": "middleware",
        },
        "OPENAI": {"API_KEY": "openai-key"},
        "GOOGLE": {"API_KEY": "google-key"},
        "VLLM": {
            "API_KEY": "",
            "BASE_URLS": "http://one/v1/, http://two/v1/",
        },
    }
    module = _reload_config(monkeypatch, env_overrides={}, config_override=config_override)
    assert module.VLLM_BASE_URL == "http://one/v1/, http://two/v1/"
    assert module.VLLM_BASE_URLS == "http://one/v1/, http://two/v1/"
