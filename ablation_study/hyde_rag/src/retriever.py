from __future__ import annotations

import logging

from statutegraph.milvus_store import row_to_chunk
from statutegraph.retrieve import _OUTPUT_FIELDS, _chunk_to_node
from statutegraph.schema import EvidencePack

from ablation_study.common import RunContext
from labourcrew.llm import get_chat_model

logger = logging.getLogger("ablation_study.hyde_rag")

_HYDE_PROMPT = (
    "You are a labour-law expert answering questions about the Bangladesh "
    "Labour Act, 2006 (as amended). Write a short, confident, Bangla answer "
    "to the question below, phrased the way the relevant statutory provision "
    "itself would be worded (cite a plausible section number if natural). Do "
    "not hedge or say you are unsure -- write the most specific, statute-like "
    "answer you can, even if you are not certain it is correct; it will only "
    "be used to find real statute text similar to it, never shown to a user "
    "or treated as a citation.\n\n"
    "প্রশ্ন: {question}\n\n"
    "কাল্পনিক উত্তর:"
)


def generate_hypothetical(ctx: RunContext, question: str) -> str:
    llm = get_chat_model(ctx.settings, temperature=0.3)
    resp = llm.invoke(_HYDE_PROMPT.format(question=question))
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return text.strip()


def hyde_retrieve(ctx: RunContext, query: str, k: int = 5) -> EvidencePack:
    hypothetical = generate_hypothetical(ctx, query)
    logger.debug("HyDE hypothetical for %r: %r", query[:60], hypothetical[:200])

    query_vec = ctx.embedder.embed([hypothetical])[0]
    collection = ctx.settings.statutegraph_milvus_collection
    results = ctx.client.search(
        collection,
        data=[query_vec],
        anns_field="embedding",
        limit=k,
        output_fields=_OUTPUT_FIELDS,
    )
    nodes = [
        _chunk_to_node(row_to_chunk(hit["entity"]), channel="hyde", score=float(hit["distance"]))
        for hit in results[0]
    ]
    return EvidencePack(nodes=nodes, paths=[], version=ctx.settings.statute_version)
