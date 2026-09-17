from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from labourcrew.prompts import load_prompt
from labourcrew.schemas import CaseSeeds, RetrievalPlan


def plan_retrieve(
    llm: ChatOpenAI, case_seeds: CaseSeeds, retrieval_request: dict | None = None
) -> RetrievalPlan:
    system = load_prompt("retrieval_planner")
    payload = {"case_seeds": case_seeds.model_dump(), "retrieval_request": retrieval_request}
    return llm.with_structured_output(RetrievalPlan).invoke(
        [SystemMessage(system), HumanMessage(str(payload))]
    )
