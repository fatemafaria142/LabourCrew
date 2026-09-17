# Ablation Study: Retrieval Strategy Comparison

Three retrieval-strategy baselines evaluated against the same LabourCrew question set (`input/chapter-*.json`) and the same underlying statute corpus (`data/`), for comparison against the full StatuteGraph retriever used in the main pipeline (see `paper/result-table.md`, Table 1).

## Experiments

| Folder | Method | Description |
|---|---|---|
| `hierarchical_rag/` | Hierarchical RAG | Multi-level retrieval — coarse chapter/section-level retrieval narrowed to fine-grained chunks. |
| `graph_rag/` | Graph-RAG | Graph-structured retrieval over statute cross-references and provisions (no LLM-driven planning/hopping). |
| `hyde_rag/` | HyDE RAG | Hypothetical Document Embeddings — generate a hypothetical answer, embed it, and retrieve by similarity to that hypothetical. |

## Layout

Each experiment folder follows the same structure:

```
<experiment>/
├── src/             # retriever implementation + run script
└── output/          # run results, metrics (gitignored)
```

## Method details

### Hierarchical RAG (`hierarchical_rag/`)

Retrieve in two stages: first select the most relevant coarse unit(s) (chapter or section), then retrieve fine-grained chunks within those units only. Compare against the full StatuteGraph retriever's flat + graph-hop approach (`statutegraph/retrieve.py`).

- `src/` — hierarchical retriever implementation (coarse-to-fine retrieval over `data/processed/`).
- `output/` — per-run metrics and retrieved-evidence logs for the 500-question set.

### Graph-RAG (`graph_rag/`)

Retrieve via graph traversal over statute cross-references, provisos, and hierarchical parent/child links, without the LLM-driven Retrieval Planner or Link Hopper agents used in the main pipeline. Compare against the full StatuteGraph retriever (`statutegraph/retrieve.py`, `labourcrew/tools/retrieval.py`) to isolate the effect of agentic planning vs. graph structure alone.

- `src/` — graph-traversal retriever implementation (fixed-policy hop expansion over `statutegraph/schema.py`'s node graph).
- `output/` — per-run metrics and retrieved-evidence logs for the 500-question set.

### HyDE RAG (`hyde_rag/`)

Hypothetical Document Embeddings: generate a hypothetical answer to the question with an LLM, embed that hypothetical answer, and retrieve statute chunks by similarity to the hypothetical embedding rather than to the question embedding directly. Compare against the dense-only and dense+BM25 baselines already in `paper/result-table.md` Table 1.

- `src/` — HyDE retriever implementation (hypothetical-answer generation + dense retrieval over `data/milvus_statutegraph.db`).
- `output/` — per-run metrics and retrieved-evidence logs for the 500-question set.

## Status

Scaffolding only — retrieval logic not yet implemented.
