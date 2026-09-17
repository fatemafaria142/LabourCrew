from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from labourcrew.prompts import load_prompt
from labourcrew.schemas import CaseSeeds, Claim
from statutegraph.schema import EvidencePack


class _ClaimList(BaseModel):
    claims: list[Claim]


def argue_employer_claim(
    llm: ChatOpenAI,
    case_seeds: CaseSeeds,
    evidence_pack: EvidencePack,
    opponent_claims: list[Claim],
    claim_id_prefix: str,
) -> list[Claim]:
    system = load_prompt("employer_counsel")
    evidence_view = [
        {"node_id": n.node_id, "text": n.verbatim_text, "level": str(n.level)} for n in evidence_pack.nodes
    ]
    payload = {
        "case_seeds": case_seeds.model_dump(),
        "evidence": evidence_view,
        "opponent_claims": [c.model_dump() for c in opponent_claims],
    }

    result = llm.with_structured_output(_ClaimList).invoke(
        [SystemMessage(system), HumanMessage(str(payload))]
    )
    valid_ids = evidence_pack.node_ids()
    claims = []
    for i, c in enumerate(result.claims):
        c.claim_id = f"{claim_id_prefix}{i + 1}"
        c.side = "EmployerCounsel"  # type: ignore[assignment]
        c.evidence = [e for e in c.evidence if e.node_id in valid_ids]
        if c.evidence:  # drop claims that ended up with zero valid evidence
            claims.append(c)
    return claims
