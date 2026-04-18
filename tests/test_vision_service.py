import src.services.vision_service as vision


def test_vision_completion_invalid_model_falls_back_to_env_model(monkeypatch):
    provider = next(iter(vision.VisionProvider))
    env_model = "env-model"
    captured: dict[str, object] = {}

    def fake_call(image_path: str, context: str, model: str | None, prompt: str | None) -> str:
        captured["image_path"] = image_path
        captured["context"] = context
        captured["model"] = model
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setenv("VISION_PROVIDER", provider.value)
    monkeypatch.setenv("VISION_MODEL", env_model)
    monkeypatch.setitem(
        vision.PROVIDER_SPECS,
        provider.value,
        vision.ProviderSpec(
            key=provider.value,
            models=[env_model],
            default_model=env_model,
            call=fake_call,
            has_credentials=lambda: True,
        ),
    )
    monkeypatch.setattr(vision, "DEFAULT_MODELS", {provider: env_model})
    monkeypatch.setattr(vision, "MODEL_PROVIDER_LOOKUP", {env_model: provider})

    result = vision.vision_completion(
        "fake.jpg",
        context="ctx",
        prompt="prompt",
        provider=provider.value,
        model="missing-model",
    )

    assert result == "ok"
    assert captured == {
        "image_path": "fake.jpg",
        "context": "ctx",
        "model": env_model,
        "prompt": "prompt",
    }
