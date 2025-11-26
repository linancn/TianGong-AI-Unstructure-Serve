from src.routers.weaviate_router import _build_minio_prefix


def test_weaviate_minio_prefix_preserves_unicode_and_replaces_spaces():
    prefix = _build_minio_prefix("KB_LCA", "Carbon footprint 分析.pdf")
    assert prefix == "KB_LCA/Carbon_footprint_分析"


def test_weaviate_minio_prefix_falls_back_to_document():
    assert _build_minio_prefix("KB_LCA", "   .pdf") == "KB_LCA/document"
