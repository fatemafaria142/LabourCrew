from __future__ import annotations

import functools
import logging
from typing import Callable

from labourcrew.state import BoardState

logger = logging.getLogger("labourcrew.agents")


def isolated(agent_name: str) -> Callable:
    def deco(fn: Callable[[BoardState], dict]) -> Callable[[BoardState], dict]:
        @functools.wraps(fn)
        def wrapped(state: BoardState) -> dict:
            logger.debug("agent %s: starting (round=%s)", agent_name, state.get("round"))
            try:
                update = fn(state) or {}
                update.setdefault("agent_statuses", {})
                update["agent_statuses"] = {
                    **update.get("agent_statuses", {}),
                    agent_name: {"status": "ok", "error": None},
                }
                logger.debug("agent %s: done", agent_name)
                return update
            except Exception as exc:  # noqa: BLE001 - deliberate: isolate any agent failure
                logger.warning("agent %s failed: %s", agent_name, exc)
                return {"agent_statuses": {agent_name: {"status": "failed", "error": str(exc)}}}

        return wrapped

    return deco
