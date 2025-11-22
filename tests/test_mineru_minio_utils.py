from src.routers import mineru_minio_utils as mmu
from src.services.minio_storage import MinioAssetRecord, MinioConfig


def test_upload_pdf_assets_preserves_chunk_type(monkeypatch):
    cfg = MinioConfig(
        endpoint="minio:9000",
        access_key="key",
        secret_key="secret",
        bucket="bucket",
        secure=False,
    )
    fake_client = object()

    recorded: dict = {}

    def fake_clear_prefix(client, bucket, prefix):  # noqa: ARG001
        recorded["prefix"] = prefix

    def fake_upload_pdf_bundle(
        client, *, cfg, prefix, pdf_path, parsed_payload, dpi=150
    ):  # noqa: ARG001
        recorded["parsed_payload"] = parsed_payload
        return MinioAssetRecord(
            bucket=cfg.bucket,
            pdf_object=f"{prefix}/source.pdf",
            json_object=f"{prefix}/parsed.json",
            page_images=[],
            prefix=prefix,
        )

    monkeypatch.setattr(mmu, "clear_prefix", fake_clear_prefix)
    monkeypatch.setattr(mmu, "upload_pdf_bundle", fake_upload_pdf_bundle)

    summary = mmu.upload_pdf_assets(
        ctx=(cfg, fake_client),
        prefix="mineru/sample",
        pdf_path="/tmp/doc.pdf",
        chunks_with_pages=[
            ("Header", 1, "header"),
            ("Body", 1, None),
        ],
    )

    assert recorded["prefix"] == "mineru/sample"
    assert summary.pdf_object.endswith("source.pdf")
    assert recorded["parsed_payload"][0]["type"] == "header"
    assert "type" not in recorded["parsed_payload"][1]
