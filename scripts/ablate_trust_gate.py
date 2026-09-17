from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from labourcrew.config import get_settings
from labourcrew.nodes import build_graph
from labourcrew.observability import CostTracker, configure_logging, track_costs
from labourcrew.state import initial_state
from labourcrew.tools import BoardContext
from statutegraph.embeddings import get_embedder
from statutegraph.milvus_store import get_client

MODES = ("categorical", "calibrated")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("questions_file", type=Path)
    parser.add_argument("--tau", type=float, default=None, help="override calibrated tau (else Settings default)")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--out", type=Path, default=Path("ablation_results.jsonl"))
    parser.add_argument("--log-level", default=None, help="Override LABOURCREW_LOG_LEVEL (e.g. DEBUG)")
    args = parser.parse_args()

    configure_logging(args.log_level)

    questions = [q.strip() for q in args.questions_file.read_text(encoding="utf-8").splitlines() if q.strip()]
    if not questions:
        raise SystemExit(f"{args.questions_file}: no questions found")

    settings = get_settings()
    client = get_client(settings)
    total_cost = CostTracker()
    try:
        ctx = BoardContext(client=client, settings=settings, embedder=get_embedder(settings))
        graph = build_graph(ctx)

        with args.out.open("w", encoding="utf-8") as out:
            for question in questions:
                for mode in MODES:
                    tau = args.tau if args.tau is not None else settings.trust_gate_tau
                    state = initial_state(
                        question, max_rounds=args.max_rounds, trust_gate_mode=mode, trust_gate_tau=tau
                    )
                    with track_costs() as cost:
                        final_state = graph.invoke(state, config={"recursion_limit": 50})
                    total_cost.merge(cost)
                    draft = final_state.get("opinion_draft") or {}
                    findings = final_state.get("trust_findings") or []
                    record = {
                        "question": question,
                        "mode": mode,
                        "tau": tau,
                        "final_status": final_state.get("final_status"),
                        "scorecard": final_state.get("scorecard"),
                        "accepted_claims": draft.get("accepted_claims", []),
                        "rejected_claims": draft.get("rejected_claims", []),
                        "claim_trust_scores": {f["claim_id"]: f["trust_score"] for f in findings},
                        "cost": cost.to_dict(),
                    }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    print(
                        f"[{mode:>11}] {question[:60]!r} -> {record['final_status']} "
                        f"(${cost.total_cost_usd():.5f})"
                    )
    finally:
        client.close()

    print(f"\nEstimated total cost across all runs: ${total_cost.total_cost_usd():.4f}")


if __name__ == "__main__":
    main()
