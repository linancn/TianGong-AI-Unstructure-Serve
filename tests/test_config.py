import importlib
import sys


def _reload_config(monkeypatch, env_overrides=None):
    config_data = {
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

    env_overrides = env_overrides or {}
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
