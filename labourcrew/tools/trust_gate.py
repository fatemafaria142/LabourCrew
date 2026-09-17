from __future__ import annotations

from typing import Literal

from labourcrew.schemas import Claim, TrustFinding

TrustGateMode = Literal["categorical", "calibrated"]


def select_usable_claims(
    claims: list[Claim],
    findings: list[TrustFinding],
    mode: TrustGateMode = "calibrated",
    tau: float = 0.5,
) -> tuple[list[Claim], list[str]]:
    """Returns (usable_claims, rejected_claim_ids).

    A claim with no matching TrustFinding was never audited and is rejected
    regardless of mode -- an unaudited claim cannot be trusted by construction.
    """
    findings_by_id = {f.claim_id: f for f in findings}
    usable: list[Claim] = []
    rejected: list[str] = []
    for c in claims:
        finding = findings_by_id.get(c.claim_id)
        if finding is None:
            rejected.append(c.claim_id)
            continue
        if mode == "calibrated":
            accept = finding.trust_score >= tau
        else:
            accept = finding.trust_status in ("trusted", "partial")
        if accept:
            usable.append(c)
        else:
            rejected.append(c.claim_id)
    return usable, rejected
