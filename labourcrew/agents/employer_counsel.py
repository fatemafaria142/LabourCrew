from __future__ import annotations

from langchain_openai import ChatOpenAI

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import CaseSeeds, Claim
from labourcrew.state import BoardState
from statutegraph.schema import EvidencePack


def make_employer_counsel(llm: ChatOpenAI):
    @isolated("EmployerCounsel")
    def employer_counsel(state: BoardState) -> dict:
        case_seeds = CaseSeeds(**state["case_seeds"]) if state.get("case_seeds") else CaseSeeds()
        pack = EvidencePack(**state["evidence_pack"]) if state.get("evidence_pack") else EvidencePack()
        opponent_claims = [
            Claim(**c) for c in (state.get("claims") or []) if c.get("side") == "WorkerCounsel"
        ]
        round_num = state.get("round", 0)
        new_claims = tools.argue_employer_claim(
            llm, case_seeds, pack, opponent_claims, claim_id_prefix=f"e{round_num}_"
        )
        return {"claims": [c.model_dump() for c in new_claims]}

    return employer_counsel
