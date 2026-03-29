from __future__ import annotations

import concurrent.futures
from pathlib import Path

from src.routers import mineru_with_images_router as router


def test_mineru_with_images_docx_return_txt_uses_native_docx_payload_txt(
    client, monkeypatch, tmp_path
):
    captured: dict[str, object] = {}

    def fake_convert_to_pdf(input_path: str, extension: str):
        assert extension == ".docx"
        pdf_path = f"{input_path}.pdf"
        Path(pdf_path).write_bytes(b"%PDF-1.4\n")
        return pdf_path, [pdf_path]

    def fake_submit(file_path: str, pipeline: str = "default", **kwargs):
        captured["file_path"] = file_path
        captured["pipeline"] = pipeline
        captured["kwargs"] = kwargs
        future = concurrent.futures.Future()
        future.set_result(
            {
                "result": [
                    {
                        "text": "JSON body chunk",
                        "page_number": 1,
                    }
                ],
                "txt": "native docx txt with image summary",
            }
        )
        return future

    monkeypatch.setattr(router, "maybe_convert_to_pdf", fake_convert_to_pdf)
    monkeypatch.setattr(router, "resolve_backend_from_env", lambda: "vlm-http-client")
    monkeypatch.setattr(router.scheduler, "submit", fake_submit)

    response = client.post(
        "/mineru_with_images",
        files={
            "file": (
                "sample.docx",
                b"fake-docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        params={"return_txt": "true"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "result": [{"text": "JSON body chunk", "page_number": 1}],
        "txt": "native docx txt with image summary",
    }
    assert captured["pipeline"] == "images"
    assert str(captured["file_path"]).endswith(".pdf")
    assert captured["kwargs"]["txt_from_native_docx"] is True
    assert str(captured["kwargs"]["txt_source_path"]).endswith(".docx")
