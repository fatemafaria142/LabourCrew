# LabourCrew

An Evidence-Gated Agentic RAG Framework for Trustworthy Multi-Role Deliberation and Statutory Reasoning over Labour Law Statutes (Bangladesh Labour Act, 2006, as amended).

## Architecture

```
data/raw/*.pdf
    -> scripts/ingest_pdf.py      (Gemini vision OCR, page-cached)
    -> data/processed/*.txt
    -> scripts/ingest_chunks.py   (statute-aware chunker -> OpenAI embeddings -> Milvus)
    -> Milvus Lite (StatuteGraph substrate)
    -> scripts/ask.py             (11-agent LangGraph board -> TGLO)
```

| Layer | Module |
|---|---|
| PDF -> text (OCR) | `statutegraph/pdf_ocr.py` |
| Statute-aware chunker | `statutegraph/chunking.py`, `statutegraph/schema.py` |
| Vector store | `statutegraph/milvus_store.py`, `statutegraph/embeddings.py` |
| Retrieval + multi-hop | `statutegraph/retrieve.py` |
| Config | `labourcrew/config.py` (reads `.env`) |
| Board state (FCL) + EEP message schemas | `labourcrew/state.py`, `labourcrew/schemas.py` |
| System prompts, one `.md` per LLM agent | `labourcrew/prompts/*.md` |
| Tool layer (T1-T11), one module per tool | `labourcrew/tools/*.py` |
| Agent nodes (A1-A11), one module per agent | `labourcrew/agents/*.py` |
| LangGraph wiring (the board itself) | `labourcrew/nodes/graph.py` |

`labourcrew/` layout in full:

```
labourcrew/
├── config.py              # Settings (.env)
├── state.py                # BoardState (the FCL)
├── schemas.py               # EEP message payload models
├── llm.py                   # ChatOpenAI getter
├── prompts/                  # one .md file per LLM-calling agent
│   ├── issue_spotter.md
│   ├── retrieval_planner.md
│   ├── worker_counsel.md
│   ├── employer_counsel.md
│   ├── legal_interpreter.md
│   ├── trust_auditor.md
│   └── opinion_writer.md    # (Supervisor + Citation Checker are deterministic — no prompt file)
├── tools/                    # T1-T11, one module per tool
│   ├── issue_spotter.py      # T1 parse_case
│   ├── retrieval_planner.py  # T2 plan_retrieve
│   ├── statute_retriever.py  # T3 retrieve_statutes
│   ├── link_hopper.py        # T4 hop_links
│   ├── worker_counsel.py     # T5 argue_worker_claim
│   ├── employer_counsel.py   # T6 argue_employer_claim
│   ├── legal_interpreter.py  # T7 interpret_path
│   ├── trust_auditor.py      # T8 audit_trust
│   ├── supervisor.py         # T9 moderate_round
│   ├── opinion_writer.py     # T10 compose_opinion
│   ├── citation_checker.py   # T11 validate_citations
│   └── scorecard.py          # T12 build_scorecard
├── agents/                   # A1-A11, one module per agent node
│   ├── issue_spotter.py
│   ├── retrieval_planner.py
│   ├── statute_retriever.py   # A3 Statute Retriever
│   ├── link_hopper.py         # A4 Link Hopper
│   ├── worker_counsel.py
│   ├── employer_counsel.py
│   ├── legal_interpreter.py
│   ├── trust_auditor.py
│   ├── supervisor.py
│   ├── opinion_writer.py
│   └── citation_checker.py
└── nodes/
    └── graph.py               # StateGraph wiring (build_graph)
```

## Why Gemini for OCR, not the PDF's text layer or GPT-4o(-mini)

The source PDF is typeset in a legacy pre-Unicode Bangla font (SutonnyMJ/ShonarBangla). These fonts store glyphs in visual draw order and hijack ASCII code points for common conjuncts (শ্র, প্র, ...), so direct text extraction (pypdf, PyMuPDF `get_text()`) silently corrupts the statutory text. GPT-4o-mini and GPT-4o vision were both tested on rendered page images and **hallucinated**: invented wording, wrong section numbers, one inserted a random English word mid-sentence. `gemini-3-flash-preview` vision transcription was cross-checked against the source images and reproduced the text (including exact section/subsection numbers) correctly, so it is the OCR path used here. Still: **spot-check OCR output against the source PDF** before treating it as gold data.

## Setup

Preferred (via [`uv`](https://docs.astral.sh/uv/), reads `pyproject.toml`/`uv.lock`):

```bash
uv sync
cp .env.example .env   # then fill in OPENAI_API_KEY and GEMINI_API_KEY
```

Alternative (plain `pip`):

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY and GEMINI_API_KEY
```

Neither path installs this repo as a package — `[tool.uv] package = false` in `pyproject.toml` keeps `uv sync` from trying to build/install a `labourcrew` wheel. `labourcrew`/`statutegraph` are importable because `scripts/*.py` inserts the repo root onto `sys.path` at the top of the file. Always run scripts from the repo root (`python scripts/ask.py ...`, or `uv run python scripts/ask.py ...` if you used `uv sync`).

Requires Python 3.11+. Tested on Python 3.13/3.14, Windows, with Milvus Lite (embedded, no server).

## Running the pipeline

```bash
# 1. OCR the raw PDF (caches per-page text under data/processed/<name>/pages/)
python scripts/ingest_pdf.py data/raw/Bangladesh-Labour-Act-2006-Amended-Chapter2.pdf

# 2. Chunk + embed + upsert into Milvus
python scripts/ingest_chunks.py data/processed/Bangladesh-Labour-Act-2006-Amended-Chapter2.txt --recreate-collection

# 3. Ask a question
python scripts/ask.py "একজন শ্রমিক হিসেবে চাকুরীর শর্ত সংক্রান্ত বিধি সম্পর্কে প্রতিষ্ঠান কী ব্যতিক্রম করতে পারে?"
```

(Prefix each `python ...` above with `uv run` if you set up the environment via `uv sync`.)

`scripts/ask.py` prints the final status (`TGLO` / `DEGRADED` / `UNDECIDED`), the opinion narrative, accepted/rejected/undecided claim IDs, the trustworthiness scorecard, and every agent's status (so a failed/degraded agent is always visible, never silent).
