from __future__ import annotations

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import TrustFinding
from labourcrew.state import BoardState


def make_supervisor():
    @isolated("Supervisor")
    def supervisor(state: BoardState) -> dict:
        round_num = state.get("round", 0)
        findings = [TrustFinding(**f) for f in (state.get("trust_findings") or [])]
        round_state = tools.moderate_round(
            round_num, state.get("max_rounds", 3), findings, state.get("agent_statuses") or {}
        )
        return {"round_state": round_state.model_dump(), "round": round_num + 1}

    return supervisor


def route_after_supervisor(state: BoardState) -> str:
    decision = (state.get("round_state") or {}).get("decision", "COMPOSE")
    return {
        "RETRY_A5": "worker_counsel",
        "RETRY_A6": "employer_counsel",
        "RETRIEVE": "retrieval_planner",
        "COMPOSE": "opinion_writer",
        "ABORT_SOFT": "opinion_writer",
    }.get(decision, "opinion_writer")
