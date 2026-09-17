from __future__ import annotations

import logging

from pymilvus import DataType, MilvusClient

from labourcrew.config import Settings
from statutegraph.embeddings import Embedder
from statutegraph.schema import ChunkLevel, StatuteChunk

logger = logging.getLogger("labourcrew.milvus")

_LIST_FIELDS = ("children_ids", "proviso_ids", "cross_refs", "concept_tags")
_MAX_TEXT_LEN = 8192
_MAX_LIST_LEN = 2048
_MAX_ID_LEN = 256


def get_client(settings: Settings) -> MilvusClient:
    uri = settings.resolved_milvus_uri()
    client = MilvusClient(uri=uri)
    name = settings.statutegraph_milvus_collection
    if client.has_collection(name):
        client.load_collection(name)
        logger.info("connected to Milvus at %s, loaded collection %r", uri, name)
    else:
        logger.info("connected to Milvus at %s, collection %r does not exist yet", uri, name)
    return client


def ensure_collection(
    client: MilvusClient, settings: Settings, embed_dim: int, recreate: bool = False
) -> None:
    name = settings.statutegraph_milvus_collection
    if client.has_collection(name):
        if not recreate:
            return
        logger.info("dropping existing Milvus collection %r (recreate=True)", name)
        client.drop_collection(name)

    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=_MAX_ID_LEN)
    schema.add_field("document", DataType.VARCHAR, max_length=_MAX_TEXT_LEN)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=embed_dim)
    schema.add_field("node_id", DataType.VARCHAR, max_length=_MAX_ID_LEN)
    schema.add_field("level", DataType.VARCHAR, max_length=32)
    schema.add_field("title", DataType.VARCHAR, max_length=1024, nullable=True)
    schema.add_field("parent_id", DataType.VARCHAR, max_length=_MAX_ID_LEN, nullable=True)
    schema.add_field("children_ids", DataType.VARCHAR, max_length=_MAX_LIST_LEN, nullable=True)
    schema.add_field("proviso_ids", DataType.VARCHAR, max_length=_MAX_LIST_LEN, nullable=True)
    schema.add_field("cross_refs", DataType.VARCHAR, max_length=_MAX_LIST_LEN, nullable=True)
    schema.add_field("concept_tags", DataType.VARCHAR, max_length=_MAX_LIST_LEN, nullable=True)
    schema.add_field("version", DataType.VARCHAR, max_length=64)
    schema.add_field("char_len", DataType.INT64)

    index_params = client.prepare_index_params()
    index_params.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")

    client.create_collection(collection_name=name, schema=schema, index_params=index_params)
    logger.info("created Milvus collection %r (embed_dim=%d)", name, embed_dim)


def chunk_to_row(chunk: StatuteChunk, embedding: list[float]) -> dict:
    row = {
        "id": chunk.node_id,
        "document": chunk.verbatim_text,
        "embedding": embedding,
        "node_id": chunk.node_id,
        "level": chunk.level.value,
        "title": chunk.title or None,
        "parent_id": chunk.parent_id,
        "version": chunk.version,
        "char_len": chunk.char_len,
    }
    for field in _LIST_FIELDS:
        values: list[str] = getattr(chunk, field)
        row[field] = ",".join(values) if values else None
    return row


def row_to_chunk(row: dict) -> StatuteChunk:
    kwargs = {
        "node_id": row["node_id"],
        "level": ChunkLevel(row["level"]),
        "title": row.get("title") or "",
        "verbatim_text": row["document"],
        "parent_id": row.get("parent_id") or None,
        "version": row["version"],
        "char_len": row.get("char_len") or 0,
    }
    for field in _LIST_FIELDS:
        raw = row.get(field)
        kwargs[field] = raw.split(",") if raw else []
    return StatuteChunk(**kwargs)


def upsert_chunks(
    client: MilvusClient,
    settings: Settings,
    chunks: list[StatuteChunk],
    embedder: Embedder,
    batch_size: int = 64,
) -> int:
    """Embed and upsert chunks. Returns the number of chunks written."""
    name = settings.statutegraph_milvus_collection
    written = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        embeddings = embedder.embed([c.embed_text() for c in batch])
        rows = [chunk_to_row(c, e) for c, e in zip(batch, embeddings)]
        client.upsert(collection_name=name, data=rows)
        written += len(rows)
        logger.debug("upserted batch %d-%d into %r", i, i + len(rows), name)
    logger.info("upserted %d chunk(s) into Milvus collection %r", written, name)
    return written
