from __future__ import annotations

from labourcrew.schemas import Claim, OpinionDraft, ValidationReport
from labourcrew.tools.text_utils import normalize_ws
from statutegraph.schema import EvidencePack


def validate_citations(
    opinion_draft: OpinionDraft, claims: list[Claim], evidence_pack: EvidencePack
) -> ValidationReport:
    claims_by_id = {c.claim_id: c for c in claims}
    text_by_id = {n.node_id: n.verbatim_text for n in evidence_pack.nodes}

    total = 0
    passed = 0
    failed: list[str] = []
    for claim_id in opinion_draft.accepted_claims:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            failed.append(claim_id)
            total += 1
            continue
        for ref in claim.evidence:
            total += 1
            node_text = text_by_id.get(ref.node_id)
            if node_text is None:
                failed.append(f"{claim_id}:{ref.node_id}")
                continue
            if not ref.span:
                # An empty span is unverifiable, not free credit -- same
                # treatment as tools/trust_score.py's quote_fidelity term.
                failed.append(f"{claim_id}:{ref.node_id}:empty-span")
                continue
            if normalize_ws(ref.span) not in normalize_ws(node_text):
                failed.append(f"{claim_id}:{ref.node_id}:quote-mismatch")
                continue
            passed += 1

    return ValidationReport(
        citations_checked=total,
        citations_passed=passed,
        failed_citations=failed,
        passed=total > 0 and not failed,
    )
