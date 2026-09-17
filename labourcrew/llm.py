from __future__ import annotations

import logging
from functools import lru_cache

from langchain_openai import ChatOpenAI

from labourcrew.config import Settings

logger = logging.getLogger("labourcrew.llm")


@lru_cache(maxsize=8)
def _cached_chat_model(api_key: str, model: str, temperature: float) -> ChatOpenAI:
    logger.info("creating chat model %s (temperature=%s)", model, temperature)
    return ChatOpenAI(api_key=api_key, model=model, temperature=temperature)


def get_chat_model(settings: Settings, temperature: float = 0.0) -> ChatOpenAI:
    return _cached_chat_model(settings.openai_api_key, settings.openai_chat_model, temperature)
