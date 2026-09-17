from __future__ import annotations

from langchain_openai import ChatOpenAI

from labourcrew import tools
from labourcrew.agents.common import isolated
from labourcrew.config import Settings
from labourcrew.schemas import CaseSeeds, Claim, InterpreterNote, OpinionDraft, TrustFinding
from labourcrew.state import BoardState


def make_opinion_writer(llm: ChatOpenAI, settings: Settings):
    @isolated("OpinionWriter")
    def opinion_writer(state: BoardState) -> dict:
        case_seeds = CaseSeeds(**state["case_seeds"]) if state.get("case_seeds") else CaseSeeds()
        claims = [Claim(**c) for c in (state.get("claims") or [])]
        findings = [TrustFinding(**f) for f in (state.get("trust_findings") or [])]
        notes = [InterpreterNote(**n) for n in (state.get("interpreter_notes") or [])]
        degraded = [
            name for name, s in (state.get("agent_statuses") or {}).items() if s.get("status") == "failed"
        ]
        mode = state.get("trust_gate_mode") or settings.trust_gate_mode
        tau = state.get("trust_gate_tau")
        if tau is None:
            tau = settings.trust_gate_tau
        if not claims:
            draft = OpinionDraft(
                narrative="প্রাপ্ত তথ্যপ্রমাণের ভিত্তিতে এই প্রশ্নের জন্য কোনো সুনির্দিষ্ট দাবি প্রতিষ্ঠা করা যায়নি।",
                degraded_channels=degraded,
            )
        else:
            draft = tools.compose_opinion(llm, case_seeds, claims, findings, notes, degraded, mode=mode, tau=tau)
        return {"opinion_draft": draft.model_dump()}

    return opinion_writer
