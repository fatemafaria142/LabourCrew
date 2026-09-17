from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from ablation_study.board_common import run_ragas_over_raw_runs  # noqa: E402

REAL_OUTPUT_DIR = _REPO_ROOT / "output"
OUTPUT_DIR = _REPO_ROOT / "ablation_study" / "main_system" / "output"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", default="2")
    parser.add_argument("--limit", type=int, default=15, help="score the first N questions (default: 15)")
    parser.add_argument("--judge-model", default="gpt-4o-mini")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    raw_path = REAL_OUTPUT_DIR / f"raw_runs_chapter-{args.chapter}.json"
    if not raw_path.exists():
        raise SystemExit(
            f"{raw_path} not found. Run `python scripts/evaluate_system.py --chapter {args.chapter}` first."
        )
    raw_runs = json.loads(raw_path.read_text(encoding="utf-8"))

    run_ragas_over_raw_runs(
        method_name="Main System (StatuteGraph, real)",
        raw_runs=raw_runs,
        out_dir=OUTPUT_DIR,
        chapter=args.chapter,
        judge_model=args.judge_model,
        limit=args.limit,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
