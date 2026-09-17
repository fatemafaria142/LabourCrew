from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from labourcrew.config import get_settings
from labourcrew.nodes import build_graph
from labourcrew.observability import configure_logging, track_costs
from labourcrew.state import initial_state
from labourcrew.tools import BoardContext
from statutegraph.embeddings import get_embedder
from statutegraph.milvus_store import get_client

logger = logging.getLogger("labourcrew.ask")

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"


def _hr(title: str) -> None:
    print(f"\n{'=' * 10} {title} {'=' * 10}")


def print_trace(question: str, final_state: dict) -> None:
    _hr("QUESTION")
    print(question)

    seeds = final_state.get("case_seeds") or {}
    _hr("A1 ISSUE SPOTTER — case_seeds")
    print(json.dumps(seeds, ensure_ascii=False, indent=2))

    plan = final_state.get("retrieval_plan") or {}
    _hr("A2 RETRIEVAL PLANNER — retrieval_plan")
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    pack = final_state.get("evidence_pack") or {}
    nodes = pack.get("nodes") or []
    _hr(f"A3+A4 RETRIEVAL — {len(nodes)} retrieved source chunk(s)")
    for n in nodes:
        print(
            f"\n[{n.get('node_id')}] level={n.get('level')} "
            f"score={n.get('provenance_score'):.4f} channels={n.get('retrieval_channels')}"
        )
        if n.get("title"):
            print(f"  title: {n['title']}")
        print(f"  text: {n.get('verbatim_text', '')}")
    if pack.get("paths"):
        print("\nHop paths:")
        for p in pack["paths"]:
            print(f"  [{p.get('path_id')}] {p.get('hops')} — {p.get('reason')}")

    claims = final_state.get("claims") or []
    _hr(f"A5 ADVOCATES — {len(claims)} claim(s)")
    for c in claims:
        print(f"\n[{c.get('claim_id')}] side={c.get('side')} confidence={c.get('confidence'):.2f}")
        print(f"  claim: {c.get('claim')}")
        for step in c.get("reasoning_steps") or []:
            print(f"    - {step}")
        print(f"  evidence: {[e.get('node_id') for e in c.get('evidence') or []]}")
        if c.get("challenge_to"):
            print(f"  challenges: {c['challenge_to']}")

    notes = final_state.get("interpreter_notes") or []
    if notes:
        _hr("A6 LEGAL INTERPRETER — interpreter_notes")
        for note in notes:
            print(f"- {note.get('note')} (refs: {note.get('referenced_claim_ids')})")

    findings = final_state.get("trust_findings") or []
    _hr(f"A7 TRUST AUDITOR — {len(findings)} finding(s)")
    for f in findings:
        print(
            f"\n[{f.get('claim_id')}] trust_status={f.get('trust_status')} "
            f"trust_score={f.get('trust_score'):.4f}"
        )
        if f.get("missing_hops"):
            print(f"  missing_hops: {f['missing_hops']}")
        if f.get("contradiction_flags"):
            print(f"  contradiction_flags: {f['contradiction_flags']}")

    round_state = final_state.get("round_state") or {}
    if round_state:
        _hr("A8 SUPERVISOR — round_state (final round)")
        print(json.dumps(round_state, ensure_ascii=False, indent=2))
    print(f"\nRounds run: {final_state.get('round')} / max {final_state.get('max_rounds')}")

    draft = final_state.get("opinion_draft") or {}
    _hr("A9 OPINION WRITER — opinion_draft")
    print(draft.get("narrative", "(no narrative)"))
    print("\nAccepted claims:", draft.get("accepted_claims"))
    print("Rejected claims:", draft.get("rejected_claims"))
    print("Undecided conflicts:", draft.get("undecided_conflicts"))
    print("Degraded channels:", draft.get("degraded_channels"))

    validation = final_state.get("validation_report") or {}
    _hr("A10 CITATION CHECKER — validation_report")
    print(json.dumps(validation, ensure_ascii=False, indent=2))

    scorecard = final_state.get("scorecard") or {}
    _hr("A11 SCORECARD")
    print(json.dumps(scorecard, ensure_ascii=False, indent=2))

    _hr("AGENT STATUSES")
    print(json.dumps(final_state.get("agent_statuses"), ensure_ascii=False, indent=2))

    _hr(f"FINAL STATUS: {final_state.get('final_status')}")


def save_run(question: str, final_state: dict) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RUNS_DIR / f"{stamp}.json"
    payload = {"question": question, "timestamp": stamp, "final_state": final_state}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="The labour-law question to ask")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--quiet", action="store_true", help="Only print the final summary, not the full trace")
    parser.add_argument("--no-save", action="store_true", help="Don't write a JSON run record to data/runs/")
    parser.add_argument("--log-level", default=None, help="Override LABOURCREW_LOG_LEVEL (e.g. DEBUG)")
    args = parser.parse_args()

    configure_logging(args.log_level)

    settings = get_settings()
    client = get_client(settings)
    try:
        ctx = BoardContext(client=client, settings=settings, embedder=get_embedder(settings))
        graph = build_graph(ctx)
        logger.info("running board: question=%r max_rounds=%d", args.question, args.max_rounds)
        with track_costs() as cost:
            final_state = graph.invoke(
                initial_state(args.question, max_rounds=args.max_rounds),
                config={"recursion_limit": 50},
            )
        cost.log_summary(prefix="ask")

        if args.quiet:
            print("\n=== FINAL STATUS:", final_state.get("final_status"), "===\n")
            draft = final_state.get("opinion_draft") or {}
            print(draft.get("narrative", "(no narrative)"))
        else:
            print_trace(args.question, dict(final_state))

        print(f"\nEstimated cost: ${cost.total_cost_usd():.6f}")

        if not args.no_save:
            state_with_cost = dict(final_state)
            state_with_cost["cost"] = cost.to_dict()
            out_path = save_run(args.question, state_with_cost)
            print(f"\nFull run saved -> {out_path}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
