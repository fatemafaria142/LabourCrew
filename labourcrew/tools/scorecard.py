from __future__ import annotations

from labourcrew.schemas import Claim, TrustFinding, TrustworthinessScorecard, ValidationReport


def build_scorecard(
    claims: list[Claim],
    trust_findings: list[TrustFinding],
    validation_report: ValidationReport,
    round_num: int,
    accepted_claim_ids: list[str] | None = None,
) -> TrustworthinessScorecard:
    """`accepted_claim_ids` should be the Trust Gate's actual accept set
    (`trust_score >= tau` under "calibrated" mode, or the legacy
    `trust_status`-based set under "categorical") -- passed in rather than
    recomputed here so evidence_coverage always matches whichever mode
    actually decided release, instead of silently reverting to the
    categorical status regardless of which gate ran.
    """
    material = list(claims)
    if accepted_claim_ids is None:
        accepted_claim_ids = [f.claim_id for f in trust_findings if f.trust_status == "trusted"]
    evidence_coverage = (len(set(accepted_claim_ids)) / len(material)) if material else 0.0

    contradiction_residual = sum(len(f.contradiction_flags) for f in trust_findings)
    citation_precision = (
        validation_report.citations_passed / validation_report.citations_checked
        if validation_report.citations_checked
        else 0.0
    )
    findings_with_hops = [f for f in trust_findings if f.missing_hops == []]
    path_completeness = (len(findings_with_hops) / len(trust_findings)) if trust_findings else 0.0

    return TrustworthinessScorecard(
        evidence_coverage=evidence_coverage,
        path_completeness=path_completeness,
        citation_precision=citation_precision,
        contradiction_residual=contradiction_residual,
        retrieval_rounds=round_num,
    )
