from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from labourcrew.prompts import load_prompt
from labourcrew.schemas import Claim, InterpreterNote
from statutegraph.schema import EvidencePack


def interpret_path(llm: ChatOpenAI, claims: list[Claim], evidence_pack: EvidencePack) -> InterpreterNote:
    system = load_prompt("legal_interpreter")
    evidence_view = [{"node_id": n.node_id, "text": n.verbatim_text} for n in evidence_pack.nodes]
    payload = {"claims": [c.model_dump() for c in claims], "evidence": evidence_view}
    return llm.with_structured_output(InterpreterNote).invoke(
        [SystemMessage(system), HumanMessage(str(payload))]
    )
