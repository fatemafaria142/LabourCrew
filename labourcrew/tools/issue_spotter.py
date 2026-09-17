from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from labourcrew.prompts import load_prompt
from labourcrew.schemas import CaseSeeds


def parse_case(llm: ChatOpenAI, question: str) -> CaseSeeds:
    system = load_prompt("issue_spotter")
    return llm.with_structured_output(CaseSeeds).invoke(
        [SystemMessage(system), HumanMessage(question)]
    )
