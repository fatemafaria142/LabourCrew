from __future__ import annotations

from statutegraph.milvus_store import row_to_chunk
from statutegraph.retrieve import _OUTPUT_FIELDS, _chunk_to_node
from statutegraph.schema import EvidencePack

from ablation_study.common import RunContext


def hierarchical_retrieve(ctx: RunContext, query: str, k_sections: int = 3, k_children: int = 5) -> EvidencePack:
    collection = ctx.settings.statutegraph_milvus_collection
    query_vec = ctx.embedder.embed([query])[0]

    # Stage 1: coarse, section-level-only dense search.
    coarse_results = ctx.client.search(
        collection,
        data=[query_vec],
        anns_field="embedding",
        limit=k_sections,
        filter='level == "section"',
        output_fields=_OUTPUT_FIELDS,
    )
    section_chunks = [row_to_chunk(hit["entity"]) for hit in coarse_results[0]]

    all_nodes: dict[str, object] = {}
    for chunk in section_chunks:
        all_nodes[chunk.node_id] = _chunk_to_node(chunk, channel="section", score=0.0)

    child_ids = sorted({cid for chunk in section_chunks for cid in chunk.children_ids})

    if child_ids:
        # Stage 2: fine-grained dense search restricted to those sections' children.
        quoted = ", ".join(f'"{cid}"' for cid in child_ids)
        fine_results = ctx.client.search(
            collection,
            data=[query_vec],
            anns_field="embedding",
            limit=min(k_children, len(child_ids)),
            filter=f"id in [{quoted}]",
            output_fields=_OUTPUT_FIELDS,
        )
        for hit in fine_results[0]:
            chunk = row_to_chunk(hit["entity"])
            node = _chunk_to_node(chunk, channel="dense-hierarchical", score=float(hit["distance"]))
            if chunk.node_id in all_nodes:
                all_nodes[chunk.node_id].retrieval_channels.append("dense-hierarchical")
            else:
                all_nodes[chunk.node_id] = node

    return EvidencePack(nodes=list(all_nodes.values()), paths=[], version=ctx.settings.statute_version)
