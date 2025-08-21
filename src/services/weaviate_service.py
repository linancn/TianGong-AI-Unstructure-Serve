import os
import uuid
import logging
from dotenv import load_dotenv

import weaviate
from typing import List, Tuple, Sequence, Union, Optional
from weaviate.classes.config import Configure, DataType, Property, Tokenization

# from weaviate.classes.init import Auth
from src.services.tools.text_to_weaviate import merge_pickle_list, fix_utf8, num_tokens_from_string


load_dotenv()

HTTP_HOST = os.environ["WEAVIATE_HTTP_HOST"]
HTTP_PORT = os.environ["WEAVIATE_HTTP_PORT"]
GRPC_HOST = os.environ["WEAVIATE_GRPC_HOST"]
GRPC_PORT = os.environ["WEAVIATE_GRPC_PORT"]
# WEAVIATE_API_KEY = os.environ.get("WEAVIATE_API_KEY")


def get_client():
    """Create and return a fresh Weaviate client connection."""
    return weaviate.connect_to_custom(
        http_host=HTTP_HOST,
        http_port=HTTP_PORT,
        http_secure=False,
        grpc_host=GRPC_HOST,
        grpc_port=GRPC_PORT,
        grpc_secure=False,
        # auth_credentials=Auth.api_key(WEAVIATE_API_KEY) if WEAVIATE_API_KEY else None,
    )


def create_collection_if_not_exists(
    collection_name: str,
    properties: Optional[List[Property]] = None,
    vector_config=None,
    ensure_properties: bool = True,
    client: Optional["weaviate.WeaviateClient"] = None,
):
    """Idempotently create (or retrieve) a Weaviate collection.

    Design goals:
    - Backwards compatible with previous simple call (only name).
    - Allow callers to specify custom ``properties`` or ``vector_config``.
    - Race-safe: if two processes create concurrently, we recover gracefully.
    - Allow client re-use (callers doing many operations can pass an existing client).

    Args:
        collection_name: Target collection name.
        properties: Optional list of Property objects; if omitted, a default schema is used.
        vector_config: Optional vector configuration list; defaults to a single NamedVectors transformer over ``content``.
        client: Optional existing connected client; if not provided a new one is created and closed here.

    Returns:
        The collection handle (ready for data operations).
    """

    def _default_properties():
        return [
            Property(
                name="content",
                data_type=DataType.TEXT,
                vectorize_property_name=True,
                tokenization=Tokenization.GSE,
            ),
            Property(
                name="source",
                data_type=DataType.TEXT,
                tokenization=Tokenization.GSE,
            ),
            Property(
                name="doc_chunk_id",
                data_type=DataType.TEXT,
            ),
            Property(
                name="tags",
                data_type=DataType.TEXT_ARRAY,
                tokenization=Tokenization.FIELD,
            ),
            Property(
                name="page_number",
                data_type=DataType.INT,
            ),
        ]

    def _default_vector_config():
        """Return a default *vector_config* list compatible with newer client API.

        IMPORTANT:
            In Weaviate client >= 4.14 the preferred argument is ``vector_config``
            (unifying vectorizer + vector index config). The helper
            ``Configure.Vectors.text2vec_transformers`` returns the correct
            ``_VectorConfigCreate`` object for this parameter. Previously this
            code used ``Configure.NamedVectors.text2vec_transformers`` and passed
            those objects to ``vector_config`` which is a type mismatch
            (NamedVectors belong to the older / deprecated ``vectorizer_config``).

            If you need a named multi‑vector setup you can supply a list of
            multiple ``Configure.Vectors.*`` results each with a distinct
            ``name=...``.
        """
        return [
            Configure.Vectors.text2vec_transformers(
                name="content",  # vector name
                source_properties=["content"],  # which property(ies) to vectorize
            )
        ]

    owned_client = False
    if client is None:
        client = get_client()
        owned_client = True

    if properties is None:
        properties = _default_properties()
    if vector_config is None:
        vector_config = _default_vector_config()

    try:
        if not client.collections.exists(collection_name):
            try:
                collection = client.collections.create(
                    name=collection_name,
                    properties=properties,
                    # vector_config expects objects from Configure.Vectors.* helpers
                    vector_config=vector_config,
                )
                logging.info("Created collection '%s'", collection_name)
            except Exception as e:  # noqa: BLE001
                # Handle race: if another process created it just before us.
                if "already exist" in str(e).lower():
                    collection = client.collections.get(collection_name)
                    logging.info(
                        "Collection '%s' appeared during creation race; using existing.",
                        collection_name,
                    )
                else:
                    raise
        else:
            collection = client.collections.get(collection_name)
            logging.debug("Collection '%s' already exists.", collection_name)

        return collection
    finally:
        if owned_client:
            client.close()


def insert_text_chunks(
    collection_name: str,
    chunks_with_page: Union[Sequence[Tuple[str, int]], Sequence[str]],
    source: str,
    max_tokens: int = 4000,
    batch_size: int = 64,
    doc_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
):
    """Insert a single already-processed document (split into chunks) into Weaviate.

    This is the "no pickle" pathway: you directly provide a list of text items
    (optionally with page numbers). Large items are further token-split to
    respect ``max_tokens``.

    Args:
        collection_name: Target collection (must already have required schema: content, source, doc_chunk_id, tags, page_number).
        chunks_with_page: Sequence of (text, page_number) tuples OR plain strings.
        source: Source identifier (original filename).
        max_tokens: Max tokens per stored chunk.
        batch_size: Insert batch size.
        doc_id: Optional stable document id; if omitted uuid4.
        tags: Optional list of tag strings applied to every chunk (assumes schema already has tags).

    Returns:
        dict summary (doc_id, inserted_chunks, collection, source, has_page_numbers).
    """
    if not chunks_with_page:
        raise ValueError("chunks_with_page is empty")

    has_page_numbers = bool(chunks_with_page and isinstance(chunks_with_page[0], tuple))  # type: ignore[index]

    # When page numbers are provided we skip merge_pickle_list to preserve mapping.
    normalized_with_page: List[Tuple[str, Optional[int]]] = []
    if has_page_numbers:
        for item in chunks_with_page:  # type: ignore[assignment]
            try:
                text, pg = item  # type: ignore[misc]
            except Exception:  # pragma: no cover
                text, pg = str(item), None
            normalized_with_page.append((str(text), int(pg) if pg is not None else None))
    else:
        # no page numbers -> treat as simple texts, apply merge/clean pipeline
        normalized = [str(t) for t in chunks_with_page]  # type: ignore[arg-type]
        merged = merge_pickle_list(normalized)
        merged = fix_utf8(merged)
        normalized_with_page = [(m, None) for m in merged]

    if not doc_id:
        doc_id = str(uuid.uuid4())

    # Build chunk dicts with token-aware splitting
    final_chunks: List[dict] = []
    running_index = 0
    for text, page in normalized_with_page:
        if num_tokens_from_string(text) > max_tokens:
            for sub_text in split_text_by_tokens(text, max_tokens=max_tokens):
                obj = {
                    "doc_chunk_id": f"{doc_id}_{running_index}",
                    "content": sub_text,
                    "source": source,
                }
                if tags:
                    obj["tags"] = tags
                if page is not None:
                    obj["page_number"] = page
                final_chunks.append(obj)
                running_index += 1
        else:
            obj = {
                "doc_chunk_id": f"{doc_id}_{running_index}",
                "content": text,
                "source": source,
            }
            if tags:
                obj["tags"] = tags
            if page is not None:
                obj["page_number"] = page
            final_chunks.append(obj)
            running_index += 1

    if not final_chunks:
        raise ValueError("No final chunks to insert (after processing)")

    client = get_client()
    try:
        if not client.collections.exists(collection_name):
            logging.info(
                f"Collection '{collection_name}' does not exist; creating via create_collection_if_not_exists()."
            )
            # Create collection using helper (separate short-lived client)
            create_collection_if_not_exists(collection_name)
        # Retrieve (now guaranteed to exist) from current client
        collection = client.collections.get(collection_name)

        for i in range(0, len(final_chunks), batch_size):
            batch = final_chunks[i : i + batch_size]
            try:
                collection.data.insert_many(batch)
            except Exception as e:  # noqa: BLE001
                logging.error(f"Batch insert error doc_id={doc_id} batch={i//batch_size + 1}: {e}")
                raise
        summary = {
            "doc_id": doc_id,
            "inserted_chunks": len(final_chunks),
            "collection": collection_name,
            "source": source,
            "has_page_numbers": has_page_numbers,
        }
        logging.info(f"Inserted document summary: {summary}")
        return summary
    finally:
        client.close()


def split_text_by_tokens(text, max_tokens=4000):
    if num_tokens_from_string(text) <= max_tokens:
        return [text]

    chunks = []
    words = text.split()
    current_chunk = []
    current_tokens = 0

    for word in words:
        word_tokens = num_tokens_from_string(word + " ")
        if current_tokens + word_tokens > max_tokens and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_tokens = word_tokens
        else:
            current_chunk.append(word)
            current_tokens += word_tokens

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def split_chunks_with_token_limit(doc_id, text_list, source, max_tokens=4000):
    all_chunks = []
    chunk_index = 0

    for chunk_text in text_list:
        if num_tokens_from_string(chunk_text) > max_tokens:
            sub_chunks = split_text_by_tokens(chunk_text, max_tokens)
            for sub_chunk in sub_chunks:
                doc_chunk_id = f"{doc_id}_{chunk_index}"
                all_chunks.append(
                    {
                        "doc_chunk_id": doc_chunk_id,
                        "content": sub_chunk,
                        "source": source,
                    }
                )
                chunk_index += 1
        else:
            doc_chunk_id = f"{doc_id}_{chunk_index}"
            all_chunks.append(
                {
                    "doc_chunk_id": doc_chunk_id,
                    "content": chunk_text,
                    "source": source,
                }
            )
            chunk_index += 1

    return all_chunks
