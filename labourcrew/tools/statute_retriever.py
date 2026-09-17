from __future__ import annotations

import logging

from labourcrew.schemas import RetrievalPlan
from labourcrew.tools.context import BoardContext
from statutegraph.retrieve import resolve_explicit_sections, vector_search
from statutegraph.schema import EvidenceNode, EvidencePack

logger = logging.getLogger("labourcrew.statute_retriever")

# Hard per-question-type ceilings on (k, max_queries), enforced in code rather
# than left to the Retrieval Planner LLM's prompt compliance alone — see
# tools/link_hopper.py for the matching hop ceilings.
_CEILING_BY_TYPE: dict[str, tuple[int, int]] = {
    "direct_factual_retrieval": (5, 1),
    "definitional_classification": (5, 1),
    "procedural_reasoning": (8, 2),
    "conditional_reasoning": (8, 2),
    "comparative_reasoning": (8, 4),
    "multi_hop_reasoning": (10, 4),
    "hypothetical_legal_reasoning": (8, 2),
}
_DEFAULT_CEILING = (10, 3)


def retrieve_statutes(
    ctx: BoardContext, plan: RetrievalPlan, question: str = "", question_type: str | None = None
) -> EvidencePack:
    queries = plan.semantic_queries or ([question] if question else [])
    k_ceiling, query_ceiling = _CEILING_BY_TYPE.get(question_type, _DEFAULT_CEILING)
    k = max(3, min(plan.k or 5, 12, k_ceiling))
    queries = queries[:query_ceiling]
    logger.debug(
        "statute_retriever: question_type=%s k=%d queries=%d", question_type, k, len(queries)
    )

    seeds_by_id: dict[str, EvidenceNode] = {}
    for q in queries:
        for node in vector_search(ctx.client, ctx.settings, ctx.embedder, q, k=k):
            existing = seeds_by_id.get(node.node_id)
            if existing is None:
                seeds_by_id[node.node_id] = node
            else:
                existing.provenance_score = max(existing.provenance_score, node.provenance_score)

    for node in resolve_explicit_sections(ctx.client, ctx.settings, question or " ".join(queries)):
        existing = seeds_by_id.get(node.node_id)
        if existing is None:
            seeds_by_id[node.node_id] = node
        elif "exact" not in existing.retrieval_channels:
            existing.retrieval_channels.append("exact")
            existing.provenance_score = max(existing.provenance_score, node.provenance_score)

    logger.info("statute_retriever: %d seed node(s)", len(seeds_by_id))
    return EvidencePack(nodes=list(seeds_by_id.values()), paths=[], version=ctx.settings.statute_version)
