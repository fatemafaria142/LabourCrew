from __future__ import annotations

from langchain_openai import ChatOpenAI

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import Claim
from labourcrew.state import BoardState
from statutegraph.schema import EvidencePack


def make_trust_auditor(llm: ChatOpenAI):
    @isolated("TrustAuditor")
    def trust_auditor(state: BoardState) -> dict:
        claims = [Claim(**c) for c in (state.get("claims") or [])]
        pack = EvidencePack(**state["evidence_pack"]) if state.get("evidence_pack") else EvidencePack()
        if not claims:
            return {"trust_findings": []}
        findings = tools.audit_trust(llm, claims, pack)
        return {"trust_findings": [f.model_dump() for f in findings]}

    return trust_auditor
