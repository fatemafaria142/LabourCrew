from __future__ import annotations

import logging
from typing import Protocol

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from labourcrew.config import Settings
from labourcrew.observability import get_current_tracker

logger = logging.getLogger("labourcrew.embeddings")

# text-embedding-3-large's native dimension; kept explicit (rather than probed
# at runtime) so the Milvus collection schema can be created before any
# embedding call is made.
EMBED_DIM = 3072

# BAAI/bge-m3's native dimension (dense head).
BGE_EMBED_DIM = 1024

_BATCH_SIZE = 96


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    dim = EMBED_DIM

    def __init__(self, settings: Settings):
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embed_model

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30))
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        tracker = get_current_tracker()
        if tracker is not None:
            tracker.add_embedding_usage(self._model, len(texts), resp.usage.total_tokens)
        logger.debug("embedded batch: model=%s texts=%d tokens=%d", self._model, len(texts), resp.usage.total_tokens)
        return [d.embedding for d in resp.data]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches, preserving input order."""
        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            out.extend(self._embed_batch(texts[i : i + _BATCH_SIZE]))
        logger.info("embedded %d text(s) via %s", len(texts), self._model)
        return out


class BGEEmbedder:
    """Local BAAI/bge-m3 embedder — multilingual (100+ languages incl. Bangla),
    dense-retrieval head, no external API calls. Chosen over OpenAI embeddings
    for this corpus because the source statute is Bangla and bge-m3 is
    explicitly trained/evaluated for Bangla dense retrieval, unlike
    text-embedding-3-large which is English-centric.
    """

    dim = BGE_EMBED_DIM

    def __init__(self, settings: Settings):
        from sentence_transformers import SentenceTransformer

        logger.info("loading local embedding model %s", settings.bge_model_name)
        self._model_name = settings.bge_model_name
        self._model = SentenceTransformer(settings.bge_model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=_BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        logger.debug("embedded %d text(s) locally via %s (no API cost)", len(texts), self._model_name)
        return vectors.tolist()


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "bge":
        return BGEEmbedder(settings)
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings)
    raise ValueError(f"Unknown embedding_provider: {settings.embedding_provider!r}")
