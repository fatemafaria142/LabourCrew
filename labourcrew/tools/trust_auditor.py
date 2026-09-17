from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from labourcrew.prompts import load_prompt
from labourcrew.schemas import Claim, TrustFinding
from labourcrew.tools.trust_score import compute_trust_score
from statutegraph.schema import EvidencePack


class _FindingList(BaseModel):
    findings: list[TrustFinding]


def audit_trust(llm: ChatOpenAI, claims: list[Claim], evidence_pack: EvidencePack) -> list[TrustFinding]:
    valid_ids = evidence_pack.node_ids()
    text_by_id = {n.node_id: n.verbatim_text for n in evidence_pack.nodes}
    scores_by_claim = {c.claim_id: compute_trust_score(c, evidence_pack) for c in claims}

    # Deterministic rule-based pass first (fallback if LLM audit fails) —
    # every claim's cited node_ids must exist in the pack.
    rule_findings: dict[str, TrustFinding] = {}
    for c in claims:
        bad = [e.node_id for e in c.evidence if e.node_id not in valid_ids]
        if bad or not c.evidence:
            rule_findings[c.claim_id] = TrustFinding(
                claim_id=c.claim_id,
                trust_status="untrusted",
                missing_hops=bad,
                trust_score=scores_by_claim[c.claim_id],
            )

    remaining = [c for c in claims if c.claim_id not in rule_findings]
    if not remaining:
        return list(rule_findings.values())

    system = load_prompt("trust_auditor")
    payload = {
        "claims": [c.model_dump() for c in remaining],
        "evidence_text_by_id": text_by_id,
    }
    result = llm.with_structured_output(_FindingList).invoke(
        [SystemMessage(system), HumanMessage(str(payload))]
    )

    findings = list(rule_findings.values())
    seen = {f.claim_id for f in findings}
    valid_claim_ids = {c.claim_id for c in remaining}
    for f in result.findings:
        if f.claim_id not in valid_claim_ids or f.claim_id in seen:
            # Model didn't echo a real claim_id (or duplicated one) — drop rather
            # than let a free-text "claim_id" leak into the opinion draft.
            continue
        f.trust_score = scores_by_claim[f.claim_id]
        findings.append(f)
        seen.add(f.claim_id)

    # Fail-closed: any claim the model silently skipped gets an explicit
    # untrusted finding instead of being invisibly excluded from the audit.
    for c in remaining:
        if c.claim_id not in seen:
            findings.append(
                TrustFinding(claim_id=c.claim_id, trust_status="untrusted", trust_score=scores_by_claim[c.claim_id])
            )
    return findings
