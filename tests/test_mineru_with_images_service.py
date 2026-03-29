from pathlib import Path

import pytest

from src.services import mineru_with_images_service as service


def test_parse_with_images_raises_when_vision_call_fails(monkeypatch, tmp_path):
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")

    def fake_parse_doc(_paths, output_dir, backend=None):
        image_path = Path(output_dir) / "page-1.jpg"
        image_path.write_bytes(b"fake-image")
        return (
            [
                {
                    "type": "image",
                    "img_path": "page-1.jpg",
                    "page_idx": 0,
                    "img_caption": ["caption"],
                    "img_footnote": [],
                }
            ],
            str(output_dir),
            None,
        )

    def boom(*args, **kwargs):
        raise RuntimeError("vision down")

    monkeypatch.setattr(service, "parse_doc", fake_parse_doc)
    monkeypatch.setattr(service, "vision_completion", boom)

    with pytest.raises(RuntimeError, match="Vision analysis failed for image 1/1 on page 1"):
        service.parse_with_images(str(source_pdf))


def test_parse_with_images_docx_native_txt_inserts_vision_output_in_order(monkeypatch, tmp_path):
    source_pdf = tmp_path / "sample.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    source_docx = tmp_path / "sample.docx"
    source_docx.write_bytes(b"docx")

    captured: dict[str, str] = {}

    def fake_parse_doc(paths, output_dir, backend=None):
        source_path = Path(paths[0])
        if source_path.suffix == ".pdf":
            return (
                [
                    {
                        "type": "text",
                        "text": "PDF JSON body",
                        "page_idx": 0,
                    }
                ],
                str(output_dir),
                None,
            )

        if source_path.suffix == ".docx":
            image_path = Path(output_dir) / "native-image.jpg"
            image_path.write_bytes(b"native-image")
            return (
                [
                    {
                        "type": "text",
                        "text": "Alpha section",
                        "page_idx": 0,
                    },
                    {
                        "type": "image",
                        "img_path": "native-image.jpg",
                        "page_idx": 0,
                        "image_caption": ["string"],
                    },
                    {
                        "type": "text",
                        "text": "Omega section",
                        "page_idx": 0,
                    },
                ],
                str(output_dir),
                None,
            )

        raise AssertionError(f"unexpected parse path: {source_path}")

    def fake_vision(*args, **kwargs):
        captured["context_payload"] = args[1]
        captured["prompt_override"] = args[2]
        return "Visible text only"

    monkeypatch.setattr(service, "parse_doc", fake_parse_doc)
    monkeypatch.setattr(service, "vision_completion", fake_vision)
    monkeypatch.setattr(service, "CONTEXT_WINDOW", 1)

    result_items, txt_text = service.parse_with_images(
        str(source_pdf),
        return_txt=True,
        txt_from_native_docx=True,
        txt_source_path=str(source_docx),
    )

    assert result_items == [{"text": "PDF JSON body", "page_number": 1}]
    assert txt_text == "Alpha section\nVisible text only\nOmega section"
    assert "Alpha section" in captured["context_payload"]
    assert "Omega section" in captured["context_payload"]
    assert "string" not in captured["context_payload"]
    assert "strict OCR and visible-content extraction" in captured["prompt_override"]
