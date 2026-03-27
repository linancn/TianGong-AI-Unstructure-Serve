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
