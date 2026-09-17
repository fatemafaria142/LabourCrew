from __future__ import annotations

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import Claim, OpinionDraft, TrustFinding
from labourcrew.state import BoardState
from statutegraph.schema import EvidencePack


def make_citation_checker():
    @isolated("CitationChecker")
    def citation_checker(state: BoardState) -> dict:
        draft = OpinionDraft(**state["opinion_draft"]) if state.get("opinion_draft") else OpinionDraft()
        claims = [Claim(**c) for c in (state.get("claims") or [])]
        pack = EvidencePack(**state["evidence_pack"]) if state.get("evidence_pack") else EvidencePack()

        report = tools.validate_citations(draft, claims, pack)
        if report.failed_citations and draft.accepted_claims:
            bad_claim_ids = {f.split(":")[0] for f in report.failed_citations}
            draft.rejected_claims = list(set(draft.rejected_claims) | bad_claim_ids)
            draft.accepted_claims = [c for c in draft.accepted_claims if c not in bad_claim_ids]
            report = tools.validate_citations(draft, claims, pack)

        scorecard = tools.build_scorecard(
            claims,
            [TrustFinding(**f) for f in (state.get("trust_findings") or [])],
            report,
            state.get("round", 0),
            accepted_claim_ids=draft.accepted_claims,
        )

        if draft.accepted_claims:
            final_status = "TGLO"
        elif claims:
            final_status = "DEGRADED"
        else:
            final_status = "UNDECIDED"

        return {
            "opinion_draft": draft.model_dump(),
            "validation_report": report.model_dump(),
            "scorecard": scorecard.model_dump(),
            "final_status": final_status,
        }

    return citation_checker
