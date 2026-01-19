from pathlib import Path

import pytest

from src.routers import two_stage_router
from src.services.vision_service import VisionModel, VisionProvider


def test_two_stage_rejects_missing_extension(client):
    resp = client.post(
        "/two_stage/task",
        files={"file": ("noext", b"content", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "extension" in resp.json()["detail"].lower()


def test_two_stage_enqueues_and_returns_task_id(client, monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"

    def fake_ensure_workspace() -> Path:
        workspace_root.mkdir(parents=True, exist_ok=True)
        return workspace_root

    monkeypatch.setattr(two_stage_router, "_ensure_workspace", fake_ensure_workspace)
    monkeypatch.setattr(two_stage_router, "resolve_backend_from_env", lambda: "vlm-http-client")

    captured = {}

    class DummyAsyncResult:
        def __init__(self) -> None:
            self.id = "fake-task-id"
            self.state = "PENDING"

    def fake_submit_two_stage_job(
        processing_path: str,
        *,
        backend=None,
        chunk_type=False,
        return_txt=False,
        provider=None,
        model=None,
        prompt=None,
        workspace=None,
        cleanup_source=False,
        extra_cleanup=None,
        parse_queue=None,
        vision_queue=None,
        dispatch_queue=None,
        merge_queue=None,
    ):
        captured.update(
            {
                "processing_path": processing_path,
                "backend": backend,
                "chunk_type": chunk_type,
                "return_txt": return_txt,
                "provider": provider,
                "model": model,
                "prompt": prompt,
                "workspace": workspace,
                "cleanup_source": cleanup_source,
                "extra_cleanup": extra_cleanup,
                "parse_queue": parse_queue,
                "vision_queue": vision_queue,
                "dispatch_queue": dispatch_queue,
                "merge_queue": merge_queue,
            }
        )
        return DummyAsyncResult()

    monkeypatch.setattr(two_stage_router, "submit_two_stage_job", fake_submit_two_stage_job)
    monkeypatch.setattr(
        two_stage_router,
        "resolve_two_stage_queues",
        lambda priority: {
            "parse": "queue_parse_urgent",
            "vision": "queue_vision_urgent",
            "dispatch": "queue_dispatch_urgent",
            "merge": "queue_merge_urgent",
        },
    )

    resp = client.post(
        "/two_stage/task",
        data={
            "chunk_type": "true",
            "return_txt": "true",
            "priority": "urgent",
            "provider": VisionProvider.OPENAI.value,
            "model": VisionModel.OPENAI_GPT_5_MINI.value,
            "prompt": "describe",
        },
        files={"file": ("sample.pdf", b"%PDF-1.4 content", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"task_id": "fake-task-id", "state": "PENDING"}

    assert captured["workspace"] == str(workspace_root)
    assert captured["processing_path"].endswith("sample.pdf")
    assert captured["chunk_type"] is True
    assert captured["return_txt"] is True
    assert captured["provider"] == VisionProvider.OPENAI
    assert captured["model"] == VisionModel.OPENAI_GPT_5_MINI
    assert captured["prompt"] == "describe"
    assert captured["parse_queue"] == "queue_parse_urgent"
    assert captured["vision_queue"] == "queue_vision_urgent"
    assert captured["dispatch_queue"] == "queue_dispatch_urgent"
    assert captured["merge_queue"] == "queue_merge_urgent"
