from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from labourcrew.prompts import load_prompt
from labourcrew.schemas import CaseSeeds, Claim, InterpreterNote, OpinionDraft, TrustFinding
from labourcrew.tools.trust_gate import TrustGateMode, select_usable_claims


def compose_opinion(
    llm: ChatOpenAI,
    case_seeds: CaseSeeds,
    claims: list[Claim],
    trust_findings: list[TrustFinding],
    interpreter_notes: list[InterpreterNote],
    degraded_channels: list[str],
    mode: TrustGateMode = "calibrated",
    tau: float = 0.5,
) -> OpinionDraft:
    usable, rejected_ids = select_usable_claims(claims, trust_findings, mode=mode, tau=tau)

    system = load_prompt("opinion_writer")
    payload = {
        "case_seeds": case_seeds.model_dump(),
        "usable_claims": [c.model_dump() for c in usable],
        "rejected_claim_ids": rejected_ids,
        "interpreter_notes": [n.model_dump() for n in interpreter_notes],
        "degraded_channels": degraded_channels,
    }
    draft = llm.with_structured_output(OpinionDraft).invoke(
        [SystemMessage(system), HumanMessage(str(payload))]
    )
    usable_ids = {c.claim_id for c in usable}
    draft.accepted_claims = [c for c in draft.accepted_claims if c in usable_ids]
    draft.undecided_conflicts = [c for c in draft.undecided_conflicts if c in usable_ids]
    draft.rejected_claims = rejected_ids
    draft.degraded_channels = degraded_channels
    return draft
