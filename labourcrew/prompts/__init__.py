from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(agent_name: str) -> str:
    """Return the full .md file content, verbatim, as the LLM's system message."""
    path = _PROMPTS_DIR / f"{agent_name}.md"
    return path.read_text(encoding="utf-8").strip()
