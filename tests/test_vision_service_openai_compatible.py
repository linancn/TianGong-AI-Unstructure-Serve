import src.services.vision_service_openai_compatible as openai_compatible
import src.services.vision_service_vllm as vision_vllm


class _DummyMessage:
    def __init__(self, content: str):
        self.content = content


class _DummyChoice:
    def __init__(self, content: str):
        self.message = _DummyMessage(content)


class _DummyResponse:
    def __init__(self, content: str):
        self.choices = [_DummyChoice(content)]


class _DummyCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _DummyResponse("ok")


class _DummyChat:
    def __init__(self, completions: _DummyCompletions):
        self.completions = completions


class _DummyClient:
    def __init__(self, completions: _DummyCompletions):
        self.chat = _DummyChat(completions)


class _DummyPool:
    def __init__(self, client: _DummyClient):
        self._client = client

    def get_client(self):
        return self._client


def test_openai_compatible_passes_extra_body(monkeypatch):
    completions = _DummyCompletions()
    pool = _DummyPool(_DummyClient(completions))
    monkeypatch.setattr(openai_compatible, "encode_image", lambda _path: "YmFzZTY0")
    monkeypatch.setattr(openai_compatible, "build_vision_prompt", lambda context, prompt: "prompt")

    result = openai_compatible.vision_completion_openai_compatible(
        "fake.jpg",
        context="ctx",
        model="Qwen/Qwen3.5-122B-A10B-FP8",
        prompt="p",
        default_model="unused",
        client_pool=pool,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        request_options={"temperature": 1.0, "top_p": 1.0},
    )

    assert result == "ok"
    assert len(completions.calls) == 1
    assert completions.calls[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert completions.calls[0]["temperature"] == 1.0
    assert completions.calls[0]["top_p"] == 1.0


def test_openai_compatible_omits_extra_body_when_empty(monkeypatch):
    completions = _DummyCompletions()
    pool = _DummyPool(_DummyClient(completions))
    monkeypatch.setattr(openai_compatible, "encode_image", lambda _path: "YmFzZTY0")
    monkeypatch.setattr(openai_compatible, "build_vision_prompt", lambda context, prompt: "prompt")

    openai_compatible.vision_completion_openai_compatible(
        "fake.jpg",
        default_model="unused",
        client_pool=pool,
    )

    assert len(completions.calls) == 1
    assert "extra_body" not in completions.calls[0]


class _DummyVllmPool:
    def has_clients(self) -> bool:
        return True


def test_vllm_vision_defaults_to_disable_thinking(monkeypatch):
    captured = {}

    monkeypatch.setattr(vision_vllm, "_CLIENT_POOL", _DummyVllmPool())

    def _fake_openai_compatible(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(vision_vllm, "vision_completion_openai_compatible", _fake_openai_compatible)
    monkeypatch.delenv("VLLM_ENABLE_THINKING", raising=False)

    result = vision_vllm.vision_completion_vllm("fake.jpg")

    assert result == "ok"
    assert captured["request_options"] == {
        "temperature": 1.0,
        "top_p": 1.0,
        "presence_penalty": 2.0,
    }
    assert captured["extra_body"] == {
        "top_k": 40,
        "min_p": 0.0,
        "repetition_penalty": 1.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_vllm_vision_allows_sampling_env_override(monkeypatch):
    captured = {}

    monkeypatch.setattr(vision_vllm, "_CLIENT_POOL", _DummyVllmPool())

    def _fake_openai_compatible(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(vision_vllm, "vision_completion_openai_compatible", _fake_openai_compatible)
    monkeypatch.setenv("VLLM_ENABLE_THINKING", "true")
    monkeypatch.setenv("VLLM_VISION_TEMPERATURE", "0.33")
    monkeypatch.setenv("VLLM_VISION_TOP_P", "0.77")
    monkeypatch.setenv("VLLM_VISION_TOP_K", "64")
    monkeypatch.setenv("VLLM_VISION_MIN_P", "0.09")
    monkeypatch.setenv("VLLM_VISION_PRESENCE_PENALTY", "1.2")
    monkeypatch.setenv("VLLM_VISION_REPETITION_PENALTY", "1.05")

    result = vision_vllm.vision_completion_vllm("fake.jpg")

    assert result == "ok"
    assert captured["request_options"] == {
        "temperature": 0.33,
        "top_p": 0.77,
        "presence_penalty": 1.2,
    }
    assert captured["extra_body"] == {
        "top_k": 64,
        "min_p": 0.09,
        "repetition_penalty": 1.05,
        "chat_template_kwargs": {"enable_thinking": True},
    }
