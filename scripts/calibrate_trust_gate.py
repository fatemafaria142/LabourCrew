from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from labourcrew.calibration import calibrate_tau
from labourcrew.observability import configure_logging


def load_jsonl(path: Path) -> tuple[list[float], list[bool]]:
    scores: list[float] = []
    faithful: list[bool] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "trust_score" not in row or "faithful" not in row:
                raise ValueError(f"{path}:{lineno}: row missing 'trust_score' or 'faithful' field")
            scores.append(float(row["trust_score"]))
            faithful.append(bool(row["faithful"]))
    return scores, faithful


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("calibration_file", type=Path)
    parser.add_argument("--alpha", type=float, default=0.10, help="target false-accept rate bound")
    parser.add_argument("--log-level", default=None, help="Override LABOURCREW_LOG_LEVEL (e.g. DEBUG)")
    args = parser.parse_args()

    configure_logging(args.log_level)

    scores, faithful = load_jsonl(args.calibration_file)
    if not scores:
        raise SystemExit(f"{args.calibration_file}: no calibration rows found")

    result = calibrate_tau(scores, faithful, alpha=args.alpha)

    print(f"calibration file      : {args.calibration_file}")
    print(f"n calibration claims   : {result.n}")
    print(f"alpha (target risk)    : {result.alpha}")
    print(f"tau (threshold)        : {result.tau}")
    print(f"empirical risk R_hat(tau): {result.empirical_risk:.4f}")
    print(f"CRC bound               : {result.risk_bound:.4f}  (must be <= alpha)")
    print(f"claims accepted at tau  : {result.n_accepted} / {result.n}")

    if result.tau_grid_exhausted:
        print(
            "\nWARNING: no tau in the score range controls risk at this alpha with "
            "this calibration set -- the gate defaults to reject-all (tau=inf). "
            "Collect more calibration data or relax alpha."
        )
        return

    print(f"\nSet in .env: TRUST_GATE_TAU={result.tau}")
    print(f"Set in .env: TRUST_GATE_ALPHA={args.alpha}")


if __name__ == "__main__":
    main()
