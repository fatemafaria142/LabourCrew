from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SRC_DIR.parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_SRC_DIR))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from ablation_study.board_common import run_board_over_chapter, run_ragas_over_raw_runs  # noqa: E402
from retriever import graph_retrieve  # noqa: E402

OUTPUT_DIR = _SRC_DIR.parent / "output"

# Fixed policy, matching ablation_study/graph_rag/src/run.py's retrieval-only
# defaults -- ignores the Retrieval Planner's (k, max_hops, allowed_edges) entirely.
_K = 5
_MAX_HOPS = 2


def _adapter(client, settings, embedder, query, k=5, max_hops=2, allowed_edges=None, question=""):
    from ablation_study.common import RunContext

    ctx = RunContext(client=client, settings=settings, embedder=embedder)
    q = question or (query if isinstance(query, str) else " ".join(query))
    return graph_retrieve(ctx, q, k=_K, max_hops=_MAX_HOPS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", default="2")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions (smoke test)")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-ragas", action="store_true", help="run the board only, skip RAGAS scoring")
    parser.add_argument("--score-top-k", type=int, default=5)
    parser.add_argument("--strictness", type=int, default=1)
    parser.add_argument(
        "--judge-model", default="gpt-4o-mini",
        help="RAGAS judge model for this ablation run (default: gpt-4o-mini; the main "
             "system's scripts/evaluate_ragas.py default stays gpt-4o -- see docs/evaluations/RAGAS.md).",
    )
    args = parser.parse_args()

    raw_runs = run_board_over_chapter(
        method_name="Graph-RAG",
        adapter=_adapter,
        chapter=args.chapter,
        out_dir=OUTPUT_DIR,
        limit=args.limit,
        max_rounds=args.max_rounds,
        resume=args.resume,
    )

    if args.skip_ragas or not raw_runs:
        return

    run_ragas_over_raw_runs(
        method_name="Graph-RAG",
        raw_runs=raw_runs,
        out_dir=OUTPUT_DIR,
        chapter=args.chapter,
        judge_model=args.judge_model,
        top_k=args.score_top_k or None,
        strictness=args.strictness,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
