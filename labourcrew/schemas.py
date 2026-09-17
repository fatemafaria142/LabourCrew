from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TrustStatus = Literal["untrusted", "partial", "trusted"]
AgentStatus = Literal["ok", "partial", "failed"]
Side = Literal["WorkerCounsel", "EmployerCounsel"]
QuestionType = Literal[
    "direct_factual_retrieval",
    "definitional_classification",
    "procedural_reasoning",
    "conditional_reasoning",
    "comparative_reasoning",
    "multi_hop_reasoning",
    "hypothetical_legal_reasoning",
    "other",
]


class Party(BaseModel):
    role: Literal["worker", "employer", "other"]
    name_or_ref: str = ""


class CaseSeeds(BaseModel):
    parties: list[Party] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    primary_issues: list[str] = Field(default_factory=list)
    secondary_issues: list[str] = Field(default_factory=list)
    legal_concepts: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    question_type: QuestionType = "other"


class RetrievalPlan(BaseModel):
    semantic_queries: list[str] = Field(default_factory=list)
    seed_nodes: list[str] = Field(default_factory=list)
    hop_edges: list[str] = Field(default_factory=list)  # subset of proviso_ids/cross_refs/parent_id/children_ids
    max_hops: int = 2
    k: int = 5  # dense-search hits per semantic query; raise for comparative/multi-hop questions
    rationale: str = ""
    plan_confidence: float = 0.0


class EvidenceRef(BaseModel):
    node_id: str
    span: str = ""
    path_id: str | None = None


class Claim(BaseModel):
    claim_id: str
    side: Side
    claim: str
    reasoning_steps: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    challenge_to: str | None = None
    confidence: float = 0.0


class InterpreterNote(BaseModel):
    note: str
    referenced_claim_ids: list[str] = Field(default_factory=list)


class RetrievalRequest(BaseModel):
    seed_nodes: list[str] = Field(default_factory=list)
    allowed_edges: list[str] = Field(default_factory=list)
    max_hops: int = 2


class TrustFinding(BaseModel):
    claim_id: str
    trust_status: TrustStatus
    missing_hops: list[str] = Field(default_factory=list)
    contradiction_flags: list[str] = Field(default_factory=list)
    retrieval_request: RetrievalRequest | None = None
    trust_score: float = 0.0


class RoundState(BaseModel):
    decision: Literal["RETRY_A5", "RETRY_A6", "RETRIEVE", "COMPOSE", "ABORT_SOFT"]
    retry_targets: list[str] = Field(default_factory=list)
    rationale: str = ""


class OpinionDraft(BaseModel):
    accepted_claims: list[str] = Field(default_factory=list)  # claim_ids
    rejected_claims: list[str] = Field(default_factory=list)
    undecided_conflicts: list[str] = Field(default_factory=list)
    narrative: str = ""
    degraded_channels: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    citations_checked: int = 0
    citations_passed: int = 0
    failed_citations: list[str] = Field(default_factory=list)
    passed: bool = False


class TrustworthinessScorecard(BaseModel):
    evidence_coverage: float = 0.0
    path_completeness: float = 0.0
    citation_precision: float = 0.0
    contradiction_residual: int = 0
    retrieval_rounds: int = 0
