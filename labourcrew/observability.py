from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Generator

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tracers.context import register_configure_hook

logger = logging.getLogger("labourcrew.cost")

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Set up root logging once per process. Level from arg, else
    LABOURCREW_LOG_LEVEL env var, else INFO."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    resolved = (level or os.environ.get("LABOURCREW_LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # These libraries log per-HTTP-request at INFO, which drowns out our own
    # logs; keep them at WARNING unless the user explicitly asked for DEBUG.
    if resolved != "DEBUG":
        for noisy in ("httpx", "httpcore", "urllib3", "pymilvus", "sentence_transformers", "google_genai"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


# USD per 1M tokens: (input_rate, output_rate). Approximate published list
# prices -- update here when OpenAI/Google reprice. Unknown models fall back
# to (0.0, 0.0) (usage is still logged, just costed as $0).
CHAT_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "o4-mini": (1.10, 4.40),
}
EMBED_PRICING: dict[str, float] = {  # USD per 1M tokens
    "text-embedding-3-large": 0.13,
    "text-embedding-3-small": 0.02,
    "text-embedding-ada-002": 0.10,
}
OCR_PRICING: dict[str, tuple[float, float]] = {  # USD per 1M tokens: (input, output)
    "gemini-3-flash-preview": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
}


def _rate_lookup(table: dict, model: str, default):
    if model in table:
        return table[model]
    for prefix, rate in table.items():
        if model.startswith(prefix):
            return rate
    return default


@dataclass
class CostTracker:
    llm_usage: dict[str, dict[str, int]] = field(default_factory=dict)
    embedding_usage: dict[str, dict[str, int]] = field(default_factory=dict)
    ocr_usage: dict[str, dict[str, int]] = field(default_factory=dict)

    def add_llm_call(self, model: str, input_tokens: int, output_tokens: int) -> None:
        bucket = self.llm_usage.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        bucket["calls"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens

    def add_embedding_usage(self, model: str, num_texts: int, num_tokens: int) -> None:
        bucket = self.embedding_usage.setdefault(model, {"calls": 0, "texts": 0, "tokens": 0})
        bucket["calls"] += 1
        bucket["texts"] += num_texts
        bucket["tokens"] += num_tokens

    def add_ocr_usage(self, model: str, input_tokens: int, output_tokens: int) -> None:
        bucket = self.ocr_usage.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        bucket["calls"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens

    def total_cost_usd(self) -> float:
        total = 0.0
        for model, u in self.llm_usage.items():
            rate_in, rate_out = _rate_lookup(CHAT_PRICING, model, (0.0, 0.0))
            total += u["input_tokens"] / 1_000_000 * rate_in + u["output_tokens"] / 1_000_000 * rate_out
        for model, u in self.embedding_usage.items():
            rate = _rate_lookup(EMBED_PRICING, model, 0.0)
            total += u["tokens"] / 1_000_000 * rate
        for model, u in self.ocr_usage.items():
            rate_in, rate_out = _rate_lookup(OCR_PRICING, model, (0.0, 0.0))
            total += u["input_tokens"] / 1_000_000 * rate_in + u["output_tokens"] / 1_000_000 * rate_out
        return total

    def merge(self, other: "CostTracker") -> None:
        for model, u in other.llm_usage.items():
            bucket = self.llm_usage.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            for k in bucket:
                bucket[k] += u[k]
        for model, u in other.embedding_usage.items():
            bucket = self.embedding_usage.setdefault(model, {"calls": 0, "texts": 0, "tokens": 0})
            for k in bucket:
                bucket[k] += u[k]
        for model, u in other.ocr_usage.items():
            bucket = self.ocr_usage.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            for k in bucket:
                bucket[k] += u[k]

    def to_dict(self) -> dict:
        return {
            "llm_usage": self.llm_usage,
            "embedding_usage": self.embedding_usage,
            "ocr_usage": self.ocr_usage,
            "estimated_cost_usd": round(self.total_cost_usd(), 6),
        }

    def log_summary(self, prefix: str = "") -> None:
        tag = f"{prefix}: " if prefix else ""
        if not (self.llm_usage or self.embedding_usage or self.ocr_usage):
            logger.info("%scost: no billable API calls recorded", tag)
            return
        for model, u in self.llm_usage.items():
            logger.info(
                "%scost: chat model=%s calls=%d input_tokens=%d output_tokens=%d",
                tag, model, u["calls"], u["input_tokens"], u["output_tokens"],
            )
        for model, u in self.embedding_usage.items():
            logger.info(
                "%scost: embedding model=%s calls=%d texts=%d tokens~=%d",
                tag, model, u["calls"], u["texts"], u["tokens"],
            )
        for model, u in self.ocr_usage.items():
            logger.info(
                "%scost: ocr model=%s calls=%d input_tokens=%d output_tokens=%d",
                tag, model, u["calls"], u["input_tokens"], u["output_tokens"],
            )
        logger.info("%scost: estimated total = $%.6f", tag, self.total_cost_usd())


_current_tracker: ContextVar[CostTracker | None] = ContextVar("_current_tracker", default=None)


def get_current_tracker() -> CostTracker | None:
    """The CostTracker for the innermost open `track_costs()` block, or None."""
    return _current_tracker.get()


class _LLMCallCallbackHandler(BaseCallbackHandler):
    """Records one call (with token usage) per chat-model completion into a
    CostTracker. Registered the same way LangChain's own
    `get_usage_metadata_callback` registers its handler (a ContextVar hooked
    via `register_configure_hook`), so it's picked up automatically by every
    LangChain/LangGraph run nested inside `track_costs()` -- no callbacks=
    wiring needed at each agent's `.invoke()` call site."""

    def __init__(self, tracker: CostTracker) -> None:
        super().__init__()
        self._tracker = tracker
        self._lock = threading.Lock()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            generation = response.generations[0][0]
        except IndexError:
            return
        if not isinstance(generation, ChatGeneration):
            return
        message = generation.message
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            return
        model = message.response_metadata.get("model_name") or "unknown"
        usage = message.usage_metadata
        with self._lock:
            self._tracker.add_llm_call(
                model, usage.get("input_tokens", 0) or 0, usage.get("output_tokens", 0) or 0
            )


_cost_callback_var: ContextVar[_LLMCallCallbackHandler | None] = ContextVar("_cost_callback_var", default=None)
register_configure_hook(_cost_callback_var, inheritable=True)


@contextmanager
def track_costs() -> Generator[CostTracker, None, None]:
    """Aggregate every billable API call made inside this block into one
    CostTracker: chat-model calls/tokens (any depth of LangChain/LangGraph
    nesting) plus any embedding/OCR usage reported via `get_current_tracker()`."""
    tracker = CostTracker()
    tracker_token = _current_tracker.set(tracker)
    callback_token = _cost_callback_var.set(_LLMCallCallbackHandler(tracker))
    try:
        yield tracker
    finally:
        _current_tracker.reset(tracker_token)
        _cost_callback_var.reset(callback_token)
