from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable

from labourcrew.config import get_settings
from labourcrew.nodes import build_graph
from labourcrew.observability import CostTracker, configure_logging, track_costs
from labourcrew.state import initial_state
from labourcrew.tools import BoardContext
from statutegraph.embeddings import get_embedder
from statutegraph.milvus_store import get_client
from statutegraph.schema import EvidencePack

import labourcrew.tools as tools_module

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_ROOT / "input"
SCRIPTS_DIR = REPO_ROOT / "scripts"

AdapterFn = Callable[..., EvidencePack]


@lru_cache(maxsize=1)
def _evaluate_system_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    import evaluate_system  # noqa: PLC0415

    return evaluate_system


@lru_cache(maxsize=1)
def _evaluate_ragas_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    import evaluate_ragas  # noqa: PLC0415

    return evaluate_ragas


def install_retriever_patch(adapter: AdapterFn) -> Callable[[], None]:
    """Monkeypatch retrieve_statutes (T3) to run `adapter` end-to-end (same
    call signature retrieve_and_hop used: client, settings, embedder, query,
    k, max_hops, allowed_edges, question) -> EvidencePack, and hop_links (T4)
    to a passthrough since the adapter's pack is already fully hopped.
    Returns a restore() callback."""
    original_retrieve_statutes = tools_module.retrieve_statutes
    original_hop_links = tools_module.hop_links

    def patched_retrieve_statutes(ctx, plan, question="", question_type=None):
        allowed_edges = tuple(plan.hop_edges) if plan.hop_edges else ("proviso_ids", "cross_refs", "parent_id")
        return adapter(
            ctx.client,
            ctx.settings,
            ctx.embedder,
            query=plan.semantic_queries or ([question] if question else []),
            k=plan.k or 5,
            max_hops=plan.max_hops,
            allowed_edges=allowed_edges,
            question=question,
        )

    def passthrough_hop_links(ctx, plan, pack, question_type=None):
        return pack

    tools_module.retrieve_statutes = patched_retrieve_statutes
    tools_module.hop_links = passthrough_hop_links

    def restore() -> None:
        tools_module.retrieve_statutes = original_retrieve_statutes
        tools_module.hop_links = original_hop_links

    return restore


def run_pipeline(ctx: BoardContext, question_text: str, max_rounds: int) -> tuple[dict, float, CostTracker]:
    graph = build_graph(ctx)
    t0 = time.perf_counter()
    with track_costs() as cost:
        final_state = graph.invoke(
            initial_state(question_text, max_rounds=max_rounds),
            config={"recursion_limit": 50},
        )
    elapsed = time.perf_counter() - t0
    return dict(final_state), elapsed, cost


def build_run_record(q: dict, final_state: dict, elapsed: float, cost: CostTracker) -> dict:
    """Same record shape as scripts/evaluate_system.py's raw_runs rows, so
    scripts/evaluate_ragas.py's scoring functions can read it unchanged."""
    pack = final_state.get("evidence_pack") or {}
    nodes = pack.get("nodes") or []
    retrieved_ids = [n["node_id"] for n in nodes]
    contexts = [n["verbatim_text"] for n in nodes]
    draft = final_state.get("opinion_draft") or {}
    answer = draft.get("narrative", "") or ""
    scorecard = final_state.get("scorecard") or {}
    validation = final_state.get("validation_report") or {}
    claims = final_state.get("claims") or []
    accepted_claim_ids = draft.get("accepted_claims") or []
    cited_ids = {
        ref.get("node_id")
        for c in claims
        if c.get("claim_id") in accepted_claim_ids
        for ref in (c.get("evidence") or [])
    }
    citation_based_precision = (
        len(cited_ids & set(retrieved_ids)) / len(retrieved_ids) if retrieved_ids else None
    )
    return {
        "id": q["id"],
        "category": q["category"],
        "difficulty": q["difficulty"],
        "question_bn": q["question_bn"],
        "question_en": q["question_en"],
        "gold_answer_bn": q["gold_answer_bn"],
        "gold_answer_en": q["gold_answer_en"],
        "generated_answer": answer,
        "final_status": final_state.get("final_status"),
        "retrieved_node_ids": retrieved_ids,
        "retrieved_contexts": contexts,
        "n_retrieved": len(retrieved_ids),
        "latency_seconds": elapsed,
        "retrieval_rounds": final_state.get("round"),
        "scorecard": scorecard,
        "validation_report": validation,
        "agent_statuses": final_state.get("agent_statuses"),
        "n_claims": len(claims),
        "n_accepted_claims": len(accepted_claim_ids),
        "n_rejected_claims": len(draft.get("rejected_claims") or []),
        "n_undecided_conflicts": len(draft.get("undecided_conflicts") or []),
        "degraded_channels": draft.get("degraded_channels") or [],
        "claims": claims,
        "accepted_claim_ids": accepted_claim_ids,
        "citation_based_precision": citation_based_precision,
        "cost": cost.to_dict(),
    }


def run_board_over_chapter(
    method_name: str,
    adapter: AdapterFn,
    chapter: str,
    out_dir: Path,
    limit: int | None = None,
    max_rounds: int = 2,
    resume: bool = False,
) -> list[dict]:
    """Run the full board (retrieval swapped to `adapter`) over
    input/chapter-<chapter>.json. Writes raw_runs_chapter-<chapter>.json and
    system_metrics_chapter-<chapter>.md to out_dir after every question.
    Returns the accumulated raw_runs list."""
    configure_logging(None)
    restore = install_retriever_patch(adapter)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"raw_runs_chapter-{chapter}.json"

    try:
        questions = json.loads((INPUT_DIR / f"chapter-{chapter}.json").read_text(encoding="utf-8"))
        if limit:
            questions = questions[:limit]

        raw_runs: list[dict] = []
        done_ids: set[str] = set()
        if resume and raw_path.exists():
            raw_runs = json.loads(raw_path.read_text(encoding="utf-8"))
            done_ids = {r["id"] for r in raw_runs}
            print(f"[{method_name}] resuming: {len(done_ids)} question(s) already completed", flush=True)

        settings = get_settings()
        client = get_client(settings)
        embedder = get_embedder(settings)
        ctx = BoardContext(client=client, settings=settings, embedder=embedder)

        print(f"[{method_name}] running full board over {len(questions)} question(s), chapter {chapter}", flush=True)
        try:
            for i, q in enumerate(questions, 1):
                if q["id"] in done_ids:
                    continue
                print(f"  [{i}/{len(questions)}] {q['id']} ({q['category']})...", flush=True)
                try:
                    final_state, elapsed, cost = run_pipeline(ctx, q["question_bn"], max_rounds)
                except Exception as exc:  # noqa: BLE001 - one bad question must not kill the batch
                    print(f"    ! pipeline failed: {exc}", flush=True)
                    continue
                record = build_run_record(q, final_state, elapsed, cost)
                raw_runs.append(record)
                print(
                    f"    status={record['final_status']} n_retrieved={record['n_retrieved']} "
                    f"latency={elapsed:.1f}s cost=${cost.total_cost_usd():.5f}",
                    flush=True,
                )
                raw_path.write_text(json.dumps(raw_runs, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            client.close()
    finally:
        restore()

    if raw_runs:
        evaluate_system = _evaluate_system_module()
        evaluate_system.write_system_report(raw_runs, out_dir / f"system_metrics_chapter-{chapter}.md", chapter)

    print(f"[{method_name}] wrote {raw_path}", flush=True)
    return raw_runs


def run_ragas_over_raw_runs(
    method_name: str,
    raw_runs: list[dict],
    out_dir: Path,
    chapter: str,
    judge_model: str | None = None,
    top_k: int | None = 5,
    strictness: int = 1,
    skip: frozenset[str] = frozenset(),
    limit: int | None = None,
    resume: bool = False,
) -> None:
    """Score `raw_runs` with RAGAS (same metrics/config shape as
    scripts/evaluate_ragas.py), writing ragas_scores_chapter-<chapter>.json
    and ragas_metrics_chapter-<chapter>.md to out_dir."""
    from dotenv import load_dotenv

    load_dotenv()
    # Must import evaluate_ragas (which stubs the missing
    # langchain_community.chat_models.vertexai submodule -- see that script's
    # top-of-file comment) BEFORE anything imports ragas.llms/ragas.evaluation
    # itself, or the real (broken) import runs first and this fails with
    # ModuleNotFoundError.
    evaluate_ragas = _evaluate_ragas_module()

    from openai import AsyncOpenAI
    from ragas.embeddings import HuggingFaceEmbeddings
    from ragas.llms import llm_factory

    judge_model = judge_model or evaluate_ragas.RAGAS_JUDGE_MODEL

    rows = raw_runs[:limit] if limit else raw_runs

    out_dir.mkdir(parents=True, exist_ok=True)
    scores_path = out_dir / f"ragas_scores_chapter-{chapter}.json"
    report_path = out_dir / f"ragas_metrics_chapter-{chapter}.md"

    ragas_rows: list[dict] = []
    done_ids: set[str] = set()
    if resume and scores_path.exists():
        ragas_rows = json.loads(scores_path.read_text(encoding="utf-8"))
        done_ids = {r["id"] for r in ragas_rows}
        print(f"[{method_name}] resuming RAGAS: {len(done_ids)} question(s) already scored", flush=True)

    oai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    ragas_llm = evaluate_ragas.JudgeLLM(llm_factory(judge_model, client=oai_client, max_tokens=4096))
    ragas_emb = HuggingFaceEmbeddings(model=evaluate_ragas.RAGAS_EMBED_MODEL)
    cfg = {"judge_model": judge_model, "top_k": top_k, "strictness": strictness, "skip": sorted(skip)}

    print(f"[{method_name}] scoring {len(rows)} question(s) with RAGAS (judge={judge_model})", flush=True)
    for i, run in enumerate(rows, 1):
        if run["id"] in done_ids:
            continue
        print(f"  [{i}/{len(rows)}] {run['id']} ({run['category']})...", flush=True)
        ragas_llm.reset()
        scores = asyncio.run(
            evaluate_ragas.score_ragas(
                ragas_llm,
                ragas_emb,
                question_bn=run["question_bn"],
                answer=run.get("generated_answer") or "(কোনো উত্তর তৈরি হয়নি)",
                contexts=run.get("retrieved_contexts") or [],
                reference=run["gold_answer_bn"],
                top_k=top_k,
                strictness=strictness,
                skip=skip,
            )
        )
        ragas_rows.append(
            {
                "id": run["id"],
                "category": run["category"],
                "difficulty": run["difficulty"],
                **scores,
                "citation_based_precision": run.get("citation_based_precision"),
            }
        )
        print(
            f"    faithfulness={scores.get('faithfulness')} "
            f"answer_correctness={scores.get('answer_correctness')} "
            f"answer_relevancy={scores.get('answer_relevancy')}",
            flush=True,
        )
        scores_path.write_text(json.dumps(ragas_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    if ragas_rows:
        evaluate_ragas.write_ragas_report(ragas_rows, report_path, chapter, cfg)

    print(f"[{method_name}] wrote {scores_path}", flush=True)
    print(f"[{method_name}] wrote {report_path}", flush=True)
