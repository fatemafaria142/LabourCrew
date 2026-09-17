from __future__ import annotations

from dataclasses import dataclass

from pymilvus import MilvusClient

from labourcrew.config import Settings
from statutegraph.embeddings import Embedder


@dataclass
class BoardContext:
    """Shared substrate handles every retrieval-capable node closes over."""

    client: MilvusClient
    settings: Settings
    embedder: Embedder
