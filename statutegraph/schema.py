from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ChunkLevel(StrEnum):
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    PROVISO = "proviso"
    EXPLANATION = "explanation"


class StatuteChunk(BaseModel):
    """One retrieval unit of StatuteGraph — one statutory unit, one Milvus row."""

    node_id: str
    level: ChunkLevel
    title: str = ""
    verbatim_text: str
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    proviso_ids: list[str] = Field(default_factory=list)
    cross_refs: list[str] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    version: str
    char_len: int = 0

    def model_post_init(self, __context: object) -> None:
        if not self.char_len:
            self.char_len = len(self.verbatim_text)

    def embed_text(self) -> str:
        """Title + verbatim text, used only for the embedding call.

        Citations must always quote `verbatim_text` alone — never this string.
        """
        if self.title:
            return f"{self.title}\n{self.verbatim_text}"
        return self.verbatim_text


class EvidenceNode(BaseModel):
    """One retrieved/hopped chunk inside an EvidencePack."""

    node_id: str
    verbatim_text: str
    retrieval_channels: list[str] = Field(default_factory=list)  # "dense" | "graph"
    provenance_score: float = 0.0
    level: ChunkLevel | None = None
    parent_id: str | None = None
    title: str = ""


class HopTrace(BaseModel):
    """One recorded multi-hop path."""

    path_id: str
    hops: list[str]
    reason: str


class EvidencePack(BaseModel):
    nodes: list[EvidenceNode] = Field(default_factory=list)
    paths: list[HopTrace] = Field(default_factory=list)
    version: str = ""

    def node_ids(self) -> set[str]:
        return {n.node_id for n in self.nodes}
