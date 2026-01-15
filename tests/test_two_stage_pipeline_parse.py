from pathlib import Path

import pytest

from src.services import mineru_service_full as msf
from src.services import two_stage_pipeline


def test_parse_doc_raises_when_do_parse_returns_none(monkeypatch, tmp_path):
    fake_pdf = tmp_path / "sample.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(msf, "read_fn", lambda path: b"fake-pdf-bytes")
    monkeypatch.setattr(msf, "do_parse", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="do_parse returned None"):
        msf.parse_doc([fake_pdf], tmp_path)


def _build_payload(tmp_path: Path, filename: str = "doc.pdf") -> dict:
    source = tmp_path / filename
    source.write_bytes(b"%PDF-1.4\n")
    workspace = tmp_path / "workspace"
    return {
        "source_path": str(source),
        "backend": "vlm-http-client",
        "chunk_type": False,
        "return_txt": False,
        "workspace": str(workspace),
        "cleanup_source": False,
        "extra_cleanup": [],
    }


def test_parse_task_surfaces_missing_parse_doc_result(monkeypatch, tmp_path):
    monkeypatch.setattr(two_stage_pipeline, "parse_doc", lambda *args, **kwargs: None)

    payload = _build_payload(tmp_path)
    with pytest.raises(RuntimeError, match="returned no content"):
        two_stage_pipeline.parse_task.run(payload)


def test_parse_task_wraps_parse_doc_exception(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(two_stage_pipeline, "parse_doc", boom)

    payload = _build_payload(tmp_path, filename="doc2.pdf")
    with pytest.raises(RuntimeError, match="parse_doc raised"):
        two_stage_pipeline.parse_task.run(payload)


def test_vision_task_passes_provider_model_and_normalized_prompt(monkeypatch):
    captured = {}

    def fake_completion(image_path, context, prompt=None, provider=None, model=None):
        captured.update(
            {
                "image_path": image_path,
                "context": context,
                "prompt": prompt,
                "provider": provider,
                "model": model,
            }
        )
        return "vision"

    monkeypatch.setattr(two_stage_pipeline, "vision_completion", fake_completion)

    job = {
        "seq": 1,
        "img_path": "/tmp/fake.jpg",
        "context_payload": "ctx",
        "base_text": "base",
    }

    result = two_stage_pipeline.vision_task.run(
        job, provider="vllm", model="demo-model", prompt="  hello  "
    )

    assert result == {"seq": 1, "vision_text": "vision"}
    assert captured["provider"] == "vllm"
    assert captured["model"] == "demo-model"
    assert captured["prompt"] == "hello"
