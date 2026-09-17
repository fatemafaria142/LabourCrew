from __future__ import annotations

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import RetrievalPlan
from labourcrew.state import BoardState
from labourcrew.tools import BoardContext


def make_statute_retriever(ctx: BoardContext):
    @isolated("StatuteRetriever")
    def statute_retriever(state: BoardState) -> dict:
        plan = (
            RetrievalPlan(**state["retrieval_plan"])
            if state.get("retrieval_plan")
            else RetrievalPlan(semantic_queries=[state["question"]])
        )
        question_type = (state.get("case_seeds") or {}).get("question_type")
        pack = tools.retrieve_statutes(ctx, plan, question=state["question"], question_type=question_type)
        return {"evidence_pack": pack.model_dump()}

    return statute_retriever
