from __future__ import annotations

from statutegraph.retrieve import retrieve_and_hop
from statutegraph.schema import EvidencePack

from ablation_study.common import RunContext

ALL_EDGES = ("parent_id", "children_ids", "proviso_ids", "cross_refs")


def graph_retrieve(ctx: RunContext, query: str, k: int = 5, max_hops: int = 2) -> EvidencePack:
    return retrieve_and_hop(
        ctx.client,
        ctx.settings,
        ctx.embedder,
        query=query,
        k=k,
        max_hops=max_hops,
        allowed_edges=ALL_EDGES,
        question=query,
    )
