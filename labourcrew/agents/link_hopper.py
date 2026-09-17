from __future__ import annotations

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import RetrievalPlan
from labourcrew.state import BoardState
from labourcrew.tools import BoardContext
from statutegraph.schema import EvidencePack


def make_link_hopper(ctx: BoardContext):
    @isolated("LinkHopper")
    def link_hopper(state: BoardState) -> dict:
        plan = (
            RetrievalPlan(**state["retrieval_plan"])
            if state.get("retrieval_plan")
            else RetrievalPlan(semantic_queries=[state["question"]])
        )
        pack = EvidencePack(**state["evidence_pack"]) if state.get("evidence_pack") else EvidencePack()
        question_type = (state.get("case_seeds") or {}).get("question_type")
        expanded = tools.hop_links(ctx, plan, pack, question_type=question_type)
        return {"evidence_pack": expanded.model_dump()}

    return link_hopper
