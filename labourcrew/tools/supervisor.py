from __future__ import annotations

from labourcrew.schemas import RoundState, TrustFinding


def moderate_round(
    round_num: int,
    max_rounds: int,
    trust_findings: list[TrustFinding],
    agent_statuses: dict[str, dict],
) -> RoundState:
    worker_failed = agent_statuses.get("WorkerCounsel", {}).get("status") == "failed"
    employer_failed = agent_statuses.get("EmployerCounsel", {}).get("status") == "failed"

    if round_num == 0:
        if worker_failed and not employer_failed:
            return RoundState(decision="RETRY_A5", retry_targets=["WorkerCounsel"], rationale="retry failed advocate")
        if employer_failed and not worker_failed:
            return RoundState(decision="RETRY_A6", retry_targets=["EmployerCounsel"], rationale="retry failed advocate")

    untrusted_with_request = [
        f for f in trust_findings if f.trust_status == "untrusted" and f.retrieval_request
    ]
    if untrusted_with_request and round_num < max_rounds:
        return RoundState(
            decision="RETRIEVE",
            rationale=f"{len(untrusted_with_request)} untrusted claim(s) with a retrieval request",
        )

    if round_num >= max_rounds:
        return RoundState(decision="COMPOSE", rationale="max rounds reached; compose from trusted subset")

    any_trusted_or_partial = any(f.trust_status != "untrusted" for f in trust_findings)
    if any_trusted_or_partial or not trust_findings:
        return RoundState(decision="COMPOSE", rationale="enough trusted evidence to answer")

    if round_num >= max_rounds - 1:
        return RoundState(decision="ABORT_SOFT", rationale="no trusted evidence and rounds exhausted")

    return RoundState(decision="RETRIEVE", rationale="no trusted claims yet; try broader retrieval")
