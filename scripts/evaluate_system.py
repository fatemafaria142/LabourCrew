from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from labourcrew.config import get_settings
from labourcrew.nodes import build_graph
from labourcrew.observability import CostTracker, configure_logging, track_costs
from labourcrew.state import initial_state
from labourcrew.tools import BoardContext
from statutegraph.embeddings import get_embedder
from statutegraph.milvus_store import get_client

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"

CATEGORY_ORDER = [
    "direct_factual_retrieval",
    "definitional_classification",
    "procedural_reasoning",
    "conditional_reasoning",
    "comparative_reasoning",
    "multi_hop_reasoning",
    "hypothetical_legal_reasoning",
]
CATEGORY_LABELS = {
    "direct_factual_retrieval": "Direct Factual Retrieval",
    "definitional_classification": "Definitional and Classification",
    "procedural_reasoning": "Procedural Reasoning",
    "conditional_reasoning": "Conditional Reasoning",
    "comparative_reasoning": "Comparative Reasoning",
    "multi_hop_reasoning": "Multi-hop Reasoning",
    "hypothetical_legal_reasoning": "Hypothetical Legal Reasoning",
}


def _print(msg: str) -> None:
    print(msg, flush=True)


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


def _avg(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _fmt(v, digits: int = 3) -> str:
    return f"{v:.{digits}f}" if isinstance(v, (int, float)) else "N/A"


def write_system_report(runs: list[dict], out_path: Path, chapter: str) -> None:
    lines = [
        f"# System-Level Metrics — LabourActQA Chapter {chapter}\n",
        f"{len(runs)} questions run through the full 11-agent LabourCrew board "
        f"(`labourcrew.nodes.build_graph`), chat model `gpt-4o-mini`.\n",
        "## By category\n",
        "| Category | N | Avg Latency (s) | Avg Rounds | Avg Evidence Coverage | "
        "Avg Path Completeness | Avg Citation Precision | Avg Citation-Based Retrieval Precision | "
        "Citation-Checker Pass Rate | Claim Acceptance Rate | % TGLO | % DEGRADED | % UNDECIDED |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    by_cat: dict[str, list[dict]] = {}
    for r in runs:
        by_cat.setdefault(r["category"], []).append(r)

    def claim_acceptance_rate(rows: list[dict]) -> float | None:
        total_claims = sum(r["n_claims"] for r in rows)
        total_accepted = sum(r["n_accepted_claims"] for r in rows)
        return (total_accepted / total_claims) if total_claims else None

    def status_pct(rows: list[dict], status: str) -> float:
        return 100.0 * sum(1 for r in rows if r["final_status"] == status) / len(rows)

    def citation_pass_rate(rows: list[dict]) -> float | None:
        passed = [r["validation_report"].get("passed") for r in rows if r.get("validation_report")]
        passed = [p for p in passed if p is not None]
        return (sum(1 for p in passed if p) / len(passed)) if passed else None

    for cat in CATEGORY_ORDER:
        crows = by_cat.get(cat, [])
        if not crows:
            continue
        lines.append(
            f"| {CATEGORY_LABELS[cat]} | {len(crows)} | "
            f"{_fmt(_avg([r['latency_seconds'] for r in crows]), 1)} | "
            f"{_fmt(_avg([r['retrieval_rounds'] for r in crows]), 2)} | "
            f"{_fmt(_avg([r['scorecard'].get('evidence_coverage') for r in crows]))} | "
            f"{_fmt(_avg([r['scorecard'].get('path_completeness') for r in crows]))} | "
            f"{_fmt(_avg([r['scorecard'].get('citation_precision') for r in crows]))} | "
            f"{_fmt(_avg([r.get('citation_based_precision') for r in crows]))} | "
            f"{_fmt(citation_pass_rate(crows), 2)} | "
            f"{_fmt(claim_acceptance_rate(crows), 2)} | "
            f"{status_pct(crows, 'TGLO'):.0f}% | {status_pct(crows, 'DEGRADED'):.0f}% | "
            f"{status_pct(crows, 'UNDECIDED'):.0f}% |"
        )
    lines.append(
        f"| **Overall** | {len(runs)} | "
        f"**{_fmt(_avg([r['latency_seconds'] for r in runs]), 1)}** | "
        f"**{_fmt(_avg([r['retrieval_rounds'] for r in runs]), 2)}** | "
        f"**{_fmt(_avg([r['scorecard'].get('evidence_coverage') for r in runs]))}** | "
        f"**{_fmt(_avg([r['scorecard'].get('path_completeness') for r in runs]))}** | "
        f"**{_fmt(_avg([r['scorecard'].get('citation_precision') for r in runs]))}** | "
        f"**{_fmt(_avg([r.get('citation_based_precision') for r in runs]))}** | "
        f"**{_fmt(citation_pass_rate(runs), 2)}** | "
        f"**{_fmt(claim_acceptance_rate(runs), 2)}** | "
        f"**{status_pct(runs, 'TGLO'):.0f}%** | **{status_pct(runs, 'DEGRADED'):.0f}%** | "
        f"**{status_pct(runs, 'UNDECIDED'):.0f}%** |"
    )

    lines += ["\n## Agent reliability (across all runs)\n", "| Agent | OK | Partial | Failed | Success Rate |", "|---|---|---|---|---|"]
    agent_counts: dict[str, dict[str, int]] = {}
    for r in runs:
        for agent, status in (r.get("agent_statuses") or {}).items():
            counts = agent_counts.setdefault(agent, {"ok": 0, "partial": 0, "failed": 0})
            s = status.get("status", "failed")
            counts[s] = counts.get(s, 0) + 1
    for agent in sorted(agent_counts):
        c = agent_counts[agent]
        total = c["ok"] + c["partial"] + c["failed"]
        rate = 100.0 * c["ok"] / total if total else 0.0
        lines.append(f"| {agent} | {c['ok']} | {c['partial']} | {c['failed']} | {rate:.0f}% |")

    lines += [
        "\n## Contradiction residual and degraded channels\n",
        f"- Total contradiction residual (summed across all runs): "
        f"{sum(r['scorecard'].get('contradiction_residual', 0) for r in runs)}",
        f"- Runs with at least one degraded (failed) channel: "
        f"{sum(1 for r in runs if r['degraded_channels'])} / {len(runs)}",
        f"- Runs with at least one undecided conflict: "
        f"{sum(1 for r in runs if r['n_undecided_conflicts'] > 0)} / {len(runs)}",
        "\n## Methodology notes\n",
        "- Evidence Coverage, Path Completeness, Citation Precision, and Contradiction Residual "
        "are the board's own internal Trustworthiness Scorecard outputs (`labourcrew/tools/scorecard.py`), "
        f"aggregated here across all {len(runs)} run(s) rather than computed independently.",
        "- Claim Acceptance Rate = total claims that survived the Trust Gate / total claims "
        "proposed by either advocate, summed across all runs in the row.",
        "- Citation-Checker Pass Rate = fraction of runs where `validation_report.passed` was true "
        "(A11 Citation Checker's final mechanical citation-verification gate).",
        "- Citation-Based Retrieval Precision = |retrieved nodes cited by an accepted claim| / "
        "|retrieved nodes|, per run. A deterministic, non-judge-model alternative to RAGAS's "
        "LLM-judged Context Precision -- measures whether retrieval fetched more than the board "
        f"ended up using, straight from the board's own citation graph (`raw_runs_chapter-{chapter}.json`'s "
        "`claims` + `accepted_claim_ids` + `retrieved_node_ids`). Unlike RAGAS Context Precision, "
        "it isn't penalized for fetching chunks needed for one concept in a comparative/multi-hop "
        "question just because they don't individually match the whole reference answer.",
    ]

    total_cost = CostTracker()
    for r in runs:
        c = r.get("cost")
        if not c:
            continue
        run_tracker = CostTracker(
            llm_usage=c.get("llm_usage", {}),
            embedding_usage=c.get("embedding_usage", {}),
            ocr_usage=c.get("ocr_usage", {}),
        )
        total_cost.merge(run_tracker)

    lines += [
        "\n## Cost\n",
        f"- Estimated total cost across all {len(runs)} run(s): **${total_cost.total_cost_usd():.4f}**",
        f"- Estimated avg cost per run: **${(total_cost.total_cost_usd() / len(runs)) if runs else 0:.6f}**",
    ]
    for model, u in total_cost.llm_usage.items():
        lines.append(
            f"- chat `{model}`: {u['calls']} call(s), {u['input_tokens']} input tokens, "
            f"{u['output_tokens']} output tokens"
        )
    for model, u in total_cost.embedding_usage.items():
        lines.append(f"- embedding `{model}`: {u['calls']} call(s), {u['tokens']} tokens")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def _save_all(raw_runs: list[dict], chapter: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / f"raw_runs_chapter-{chapter}.json").write_text(
        json.dumps(raw_runs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if raw_runs:
        write_system_report(raw_runs, OUTPUT_DIR / f"system_metrics_chapter-{chapter}.md", chapter)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chapter", default="2",
        help="dataset suffix: reads input/chapter-<N>.json, writes output/*_chapter-<N>.{json,md} (default: 2)",
    )
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions (smoke test)")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument(
        "--resume", action="store_true",
        help="skip question ids already present in output/raw_runs_chapter-<N>.json instead of re-running them",
    )
    parser.add_argument("--log-level", default=None, help="Override LABOURCREW_LOG_LEVEL (e.g. DEBUG)")
    args = parser.parse_args()
    chapter = args.chapter

    configure_logging(args.log_level)

    input_path = REPO_ROOT / "input" / f"chapter-{chapter}.json"
    with open(input_path, encoding="utf-8") as f:
        questions = json.load(f)
    if args.limit:
        questions = questions[: args.limit]

    raw_runs: list[dict] = []
    done_ids: set[str] = set()
    if args.resume:
        raw_path = OUTPUT_DIR / f"raw_runs_chapter-{chapter}.json"
        if raw_path.exists():
            raw_runs = json.loads(raw_path.read_text(encoding="utf-8"))
            done_ids = {r["id"] for r in raw_runs}
        _print(f"Resuming: {len(done_ids)} question(s) already completed, skipping them.")

    settings = get_settings()
    client = get_client(settings)
    embedder = get_embedder(settings)
    ctx = BoardContext(client=client, settings=settings, embedder=embedder)

    try:
        for i, q in enumerate(questions, 1):
            qid = q["id"]
            if qid in done_ids:
                continue
            _print(f"[{i}/{len(questions)}] {qid} ({q['category']})...")
            try:
                final_state, elapsed, cost = run_pipeline(ctx, q["question_bn"], args.max_rounds)
            except Exception as exc:  # noqa: BLE001 - one bad question must not kill the batch
                _print(f"    ! pipeline failed: {exc}")
                continue

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

            # Citation-based retrieval precision: of the nodes actually retrieved,
            # what fraction did an *accepted* claim actually cite? A deterministic
            # alternative to RAGAS's LLM-judged Context Precision (which scores each
            # retrieved chunk against a single reference answer -- structurally
            # unfair to comparative/multi-hop questions needing chunks from more
            # than one concept). This instead measures whether retrieval fetched
            # more than the board ended up using, straight from the board's own
            # citation graph, no judge model involved.
            cited_ids = {
                ref.get("node_id")
                for c in claims
                if c.get("claim_id") in accepted_claim_ids
                for ref in (c.get("evidence") or [])
            }
            citation_based_precision = (
                len(cited_ids & set(retrieved_ids)) / len(retrieved_ids) if retrieved_ids else None
            )

            run_record = {
                "id": qid,
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
            raw_runs.append(run_record)
            _print(
                f"    status={run_record['final_status']} n_retrieved={len(retrieved_ids)} "
                f"latency={elapsed:.1f}s rounds={run_record['retrieval_rounds']} "
                f"cost=${cost.total_cost_usd():.5f}"
            )
            # Save after every question -- a killed/interrupted run keeps whatever
            # completed so far instead of losing it (each question is a full board
            # pass through ~8 LLM-calling agents).
            _save_all(raw_runs, chapter)
    finally:
        client.close()

    _save_all(raw_runs, chapter)
    total_cost = CostTracker()
    for r in raw_runs:
        c = r.get("cost")
        if c:
            total_cost.merge(
                CostTracker(
                    llm_usage=c.get("llm_usage", {}),
                    embedding_usage=c.get("embedding_usage", {}),
                    ocr_usage=c.get("ocr_usage", {}),
                )
            )
    _print(f"\nDone. {len(raw_runs)}/{len(questions)} questions completed. Results in {OUTPUT_DIR}")
    _print(f"Estimated total cost across all runs: ${total_cost.total_cost_usd():.4f}")
    _print(
        f"Next: python scripts/evaluate_ragas.py --chapter {chapter}  "
        "(scores RAGAS metrics from this trace, no board re-run)"
    )


if __name__ == "__main__":
    main()
