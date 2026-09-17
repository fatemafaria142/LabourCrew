from __future__ import annotations

from langchain_openai import ChatOpenAI

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import CaseSeeds, TrustFinding
from labourcrew.state import BoardState


def make_retrieval_planner(llm: ChatOpenAI):
    @isolated("RetrievalPlanner")
    def retrieval_planner(state: BoardState) -> dict:
        case_seeds = CaseSeeds(**state["case_seeds"]) if state.get("case_seeds") else CaseSeeds()
        retrieval_request = None
        for f in state.get("trust_findings") or []:
            finding = TrustFinding(**f)
            if finding.trust_status == "untrusted" and finding.retrieval_request:
                retrieval_request = finding.retrieval_request.model_dump()
                break
        plan = tools.plan_retrieve(llm, case_seeds, retrieval_request)
        if not plan.semantic_queries:
            # Fall back to the raw question so retrieval never runs on an empty query.
            plan.semantic_queries = [state["question"]]
        return {"retrieval_plan": plan.model_dump()}

    return retrieval_planner
