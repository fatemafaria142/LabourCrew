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

from ablation_study.common import make_retrieve_fn, run_experiment  # noqa: E402
from retriever import graph_retrieve  # noqa: E402

OUTPUT_DIR = _SRC_DIR.parent / "output"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Graph-RAG ablation.")
    parser.add_argument("--chapter", choices=["2", "3", "4", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    parser.add_argument("--k", type=int, default=5, help="dense-seed search top-k")
    parser.add_argument("--max-hops", type=int, default=2, help="max graph-expansion hop depth")
    args = parser.parse_args()

    chapters = [2, 3, 4] if args.chapter == "all" else [int(args.chapter)]

    def method_fn(ctx, query: str):
        return graph_retrieve(ctx, query, k=args.k, max_hops=args.max_hops)

    run_experiment(
        method_name="Graph-RAG",
        method_slug="graph_rag",
        retrieve_fn=make_retrieve_fn(method_fn),
        chapters=chapters,
        out_dir=OUTPUT_DIR,
        limit=args.limit,
        extra_config={"k": args.k, "max_hops": args.max_hops},
    )


if __name__ == "__main__":
    main()
