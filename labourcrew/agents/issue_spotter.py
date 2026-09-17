from __future__ import annotations

from langchain_openai import ChatOpenAI

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.state import BoardState


def make_issue_spotter(llm: ChatOpenAI):
    @isolated("IssueSpotter")
    def issue_spotter(state: BoardState) -> dict:
        seeds = tools.parse_case(llm, state["question"])
        return {"case_seeds": seeds.model_dump()}

    return issue_spotter
