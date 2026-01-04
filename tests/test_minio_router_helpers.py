from src.routers.minio_router import build_storage_collection_name


def test_build_storage_collection_name_normalizes_values():
    result = build_storage_collection_name(base="kb-name", user_id="user-123")
    assert result == "KB_USER_123_KB_NAME"


def test_build_storage_collection_name_defaults_base_when_empty():
    result = build_storage_collection_name(base="", user_id="user")
    assert result == "KB_USER_KB"
