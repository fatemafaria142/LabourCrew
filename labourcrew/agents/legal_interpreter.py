from __future__ import annotations

from langchain_openai import ChatOpenAI

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.schemas import Claim
from labourcrew.state import BoardState
from statutegraph.schema import EvidencePack


def make_legal_interpreter(llm: ChatOpenAI):
    @isolated("LegalInterpreter")
    def legal_interpreter(state: BoardState) -> dict:
        claims = [Claim(**c) for c in (state.get("claims") or [])]
        pack = EvidencePack(**state["evidence_pack"]) if state.get("evidence_pack") else EvidencePack()
        if not claims:
            return {"interpreter_notes": state.get("interpreter_notes") or []}
        note = tools.interpret_path(llm, claims, pack)
        return {"interpreter_notes": (state.get("interpreter_notes") or []) + [note.model_dump()]}

    return legal_interpreter
