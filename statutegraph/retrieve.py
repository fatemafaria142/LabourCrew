from __future__ import annotations

from pymilvus import MilvusClient

from labourcrew.config import Settings
from statutegraph.bangla_numerals import extract_referenced_section_nums
from statutegraph.embeddings import Embedder
from statutegraph.milvus_store import row_to_chunk
from statutegraph.schema import EvidenceNode, EvidencePack, HopTrace, StatuteChunk

DEFAULT_ALLOWED_EDGES = ("proviso_ids", "cross_refs", "parent_id")
_OUTPUT_FIELDS = [
    "node_id",
    "document",
    "level",
    "title",
    "parent_id",
    "children_ids",
    "proviso_ids",
    "cross_refs",
    "version",
    "char_len",
]


def _chunk_to_node(chunk: StatuteChunk, channel: str, score: float) -> EvidenceNode:
    return EvidenceNode(
        node_id=chunk.node_id,
        verbatim_text=chunk.verbatim_text,
        retrieval_channels=[channel],
        provenance_score=score,
        level=chunk.level,
        parent_id=chunk.parent_id,
        title=chunk.title,
    )


def _fetch_chunks_by_ids(client: MilvusClient, collection: str, ids: list[str]) -> dict[str, StatuteChunk]:
    if not ids:
        return {}
    quoted = ", ".join(f'"{i}"' for i in ids)
    rows = client.query(collection, filter=f"id in [{quoted}]", output_fields=_OUTPUT_FIELDS)
    return {row["node_id"]: row_to_chunk(row) for row in rows}


def vector_search(
    client: MilvusClient,
    settings: Settings,
    embedder: Embedder,
    query: str,
    k: int = 5,
) -> list[EvidenceNode]:
    query_vec = embedder.embed([query])[0]
    results = client.search(
        settings.statutegraph_milvus_collection,
        data=[query_vec],
        anns_field="embedding",
        limit=k,
        output_fields=_OUTPUT_FIELDS,
    )
    nodes = []
    for hit in results[0]:
        chunk = row_to_chunk(hit["entity"])
        nodes.append(_chunk_to_node(chunk, channel="dense", score=float(hit["distance"])))
    return nodes


def resolve_explicit_sections(
    client: MilvusClient, settings: Settings, question: str
) -> list[EvidenceNode]:
    """Exact-match node lookup for section numbers named directly in the question.

    Dense/semantic search can rank the wrong chunk highest for a "what does
    section 20 say" style question (Direct Factual Retrieval). This bypasses
    embedding ambiguity entirely: parse "ধারা ২০" / "section 20" out of the
    raw question text and fetch that section's chunk by exact node_id suffix
    match (node_id is "...S{num}", e.g. "BLA.Ch0.S20").
    """
    section_nums = extract_referenced_section_nums(question)
    if not section_nums:
        return []
    wanted_suffixes = {f"S{n}" for n in section_nums}
    collection = settings.statutegraph_milvus_collection
    rows = client.query(collection, filter='level == "section"', output_fields=_OUTPUT_FIELDS)
    nodes = []
    for row in rows:
        suffix = row["node_id"].rsplit(".", 1)[-1]
        if suffix in wanted_suffixes:
            chunk = row_to_chunk(row)
            nodes.append(_chunk_to_node(chunk, channel="exact", score=1.0))
    return nodes


def _outgoing_links(chunk: StatuteChunk, allowed_edges: tuple[str, ...]) -> list[tuple[str, str]]:
    """(edge_type, target_id) pairs for one chunk, restricted to allowed_edges."""
    links: list[tuple[str, str]] = []
    if "parent_id" in allowed_edges and chunk.parent_id:
        links.append(("parent_id", chunk.parent_id))
    if "proviso_ids" in allowed_edges:
        links.extend(("proviso_ids", pid) for pid in chunk.proviso_ids)
    if "cross_refs" in allowed_edges:
        links.extend(("cross_refs", cid) for cid in chunk.cross_refs)
    if "children_ids" in allowed_edges:
        links.extend(("children_ids", cid) for cid in chunk.children_ids)
    return links


def expand_links(
    client: MilvusClient,
    settings: Settings,
    seed_chunks: list[StatuteChunk],
    max_hops: int = 2,
    allowed_edges: tuple[str, ...] = DEFAULT_ALLOWED_EDGES,
) -> tuple[list[EvidenceNode], list[HopTrace]]:
    """Expand a seed frontier outward along metadata links, up to max_hops."""
    collection = settings.statutegraph_milvus_collection
    visited: dict[str, StatuteChunk] = {c.node_id: c for c in seed_chunks}
    frontier = list(seed_chunks)
    hopped_nodes: list[EvidenceNode] = []
    traces: list[HopTrace] = []
    path_counter = 0

    for hop_depth in range(1, max_hops + 1):
        candidate_links: list[tuple[str, str, str]] = []  # (edge_type, source_id, target_id)
        for chunk in frontier:
            for edge_type, target_id in _outgoing_links(chunk, allowed_edges):
                if target_id not in visited:
                    candidate_links.append((edge_type, chunk.node_id, target_id))

        new_ids = list({target for _, _, target in candidate_links})
        if not new_ids:
            break

        fetched = _fetch_chunks_by_ids(client, collection, new_ids)
        next_frontier = []
        for edge_type, source_id, target_id in candidate_links:
            if target_id not in fetched:
                continue  # dangling reference — target not in the index
            if target_id in visited:
                continue
            target_chunk = fetched[target_id]
            visited[target_id] = target_chunk
            node = _chunk_to_node(target_chunk, channel="graph", score=0.0)
            hopped_nodes.append(node)
            next_frontier.append(target_chunk)

            path_counter += 1
            traces.append(
                HopTrace(
                    path_id=f"p{path_counter}",
                    hops=[source_id, edge_type, target_id],
                    reason=f"hop {hop_depth}: {edge_type} of {source_id}",
                )
            )
        frontier = next_frontier

    return hopped_nodes, traces


def retrieve_and_hop(
    client: MilvusClient,
    settings: Settings,
    embedder: Embedder,
    query: str | list[str],
    k: int = 5,
    max_hops: int = 2,
    allowed_edges: tuple[str, ...] = DEFAULT_ALLOWED_EDGES,
    question: str = "",
) -> EvidencePack:
    """query: one semantic query, or a list run as separate dense searches and
    merged (not joined into one string) — a single joined string loses recall
    on multi-concept questions, e.g. comparative reasoning over two provisions.
    question: the raw user question, if different from `query`, used only to
    resolve explicit "section N" references to an exact node_id match.
    """
    queries = [query] if isinstance(query, str) else list(query)
    queries = [q for q in queries if q and q.strip()]

    seeds_by_id: dict[str, EvidenceNode] = {}
    for q in queries:
        for node in vector_search(client, settings, embedder, q, k=k):
            existing = seeds_by_id.get(node.node_id)
            if existing is None:
                seeds_by_id[node.node_id] = node
            else:
                existing.provenance_score = max(existing.provenance_score, node.provenance_score)

    for node in resolve_explicit_sections(client, settings, question or " ".join(queries)):
        existing = seeds_by_id.get(node.node_id)
        if existing is None:
            seeds_by_id[node.node_id] = node
        elif "exact" not in existing.retrieval_channels:
            existing.retrieval_channels.append("exact")
            existing.provenance_score = max(existing.provenance_score, node.provenance_score)

    seed_nodes = list(seeds_by_id.values())
    seed_chunks = [
        StatuteChunk(
            node_id=n.node_id,
            level=n.level,
            title=n.title,
            verbatim_text=n.verbatim_text,
            parent_id=n.parent_id,
            version=settings.statute_version,
        )
        for n in seed_nodes
    ]
    hopped_nodes, traces = expand_links(
        client, settings, seed_chunks, max_hops=max_hops, allowed_edges=allowed_edges
    )

    all_nodes: dict[str, EvidenceNode] = {n.node_id: n for n in seed_nodes}
    for n in hopped_nodes:
        if n.node_id in all_nodes:
            all_nodes[n.node_id].retrieval_channels.append("graph")
        else:
            all_nodes[n.node_id] = n

    return EvidencePack(nodes=list(all_nodes.values()), paths=traces, version=settings.statute_version)
