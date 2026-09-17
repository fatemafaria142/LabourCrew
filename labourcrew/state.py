from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def _merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    merged = dict(a)
    merged.update(b)
    return merged


class BoardState(TypedDict, total=False):
    question: str

    case_seeds: dict | None
    retrieval_plan: dict | None
    evidence_pack: dict | None

    claims: Annotated[list[dict], operator.add]
    interpreter_notes: list[dict]
    trust_findings: list[dict]

    round: int
    max_rounds: int
    round_state: dict | None

    opinion_draft: dict | None
    validation_report: dict | None
    scorecard: dict | None

    agent_statuses: Annotated[dict[str, dict], _merge_dicts]

    final_status: str  # "TGLO" | "DEGRADED" | "UNDECIDED"

    # Trust Gate mode/threshold for this run.
    # None means "fall back to Settings" -- set explicitly so a single
    # process can run categorical vs. calibrated ablations side by side
    # (scripts/ablate_trust_gate.py) without mutating global Settings.
    trust_gate_mode: str | None
    trust_gate_tau: float | None


def initial_state(
    question: str,
    max_rounds: int = 3,
    trust_gate_mode: str | None = None,
    trust_gate_tau: float | None = None,
) -> BoardState:
    return BoardState(
        question=question,
        case_seeds=None,
        retrieval_plan=None,
        evidence_pack=None,
        claims=[],
        interpreter_notes=[],
        trust_findings=[],
        round=0,
        max_rounds=max_rounds,
        round_state=None,
        opinion_draft=None,
        validation_report=None,
        scorecard=None,
        agent_statuses={},
        final_status="",
        trust_gate_mode=trust_gate_mode,
        trust_gate_tau=trust_gate_tau,
    )
