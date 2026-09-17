from __future__ import annotations

import logging

from labourcrew.schemas import RetrievalPlan
from labourcrew.tools.context import BoardContext
from statutegraph.retrieve import expand_links
from statutegraph.schema import EvidencePack, StatuteChunk

logger = logging.getLogger("labourcrew.link_hopper")

_HOP_CEILING_BY_TYPE: dict[str, int] = {
    "direct_factual_retrieval": 1,
    "definitional_classification": 1,
    "procedural_reasoning": 2,
    "conditional_reasoning": 2,
    "comparative_reasoning": 2,
    "multi_hop_reasoning": 3,
    "hypothetical_legal_reasoning": 2,
}
_DEFAULT_HOP_CEILING = 3


def hop_links(
    ctx: BoardContext, plan: RetrievalPlan, pack: EvidencePack, question_type: str | None = None
) -> EvidencePack:
    allowed_edges = tuple(plan.hop_edges) if plan.hop_edges else ("proviso_ids", "cross_refs", "parent_id")
    hop_ceiling = _HOP_CEILING_BY_TYPE.get(question_type, _DEFAULT_HOP_CEILING)
    max_hops = max(1, min(plan.max_hops, 3, hop_ceiling))
    logger.debug(
        "link_hopper: question_type=%s max_hops=%d edges=%s", question_type, max_hops, allowed_edges
    )

    seed_chunks = [
        StatuteChunk(
            node_id=n.node_id,
            level=n.level,
            title=n.title,
            verbatim_text=n.verbatim_text,
            parent_id=n.parent_id,
            version=ctx.settings.statute_version,
        )
        for n in pack.nodes
    ]
    hopped_nodes, traces = expand_links(
        ctx.client, ctx.settings, seed_chunks, max_hops=max_hops, allowed_edges=allowed_edges
    )

    all_nodes = {n.node_id: n for n in pack.nodes}
    for n in hopped_nodes:
        if n.node_id in all_nodes:
            all_nodes[n.node_id].retrieval_channels.append("graph")
        else:
            all_nodes[n.node_id] = n

    logger.info("link_hopper: %d hop path(s), %d total node(s)", len(traces), len(all_nodes))
    return EvidencePack(nodes=list(all_nodes.values()), paths=traces, version=ctx.settings.statute_version)
