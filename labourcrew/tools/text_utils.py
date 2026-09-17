from __future__ import annotations

import re


def normalize_ws(s: str) -> str:
    """Collapse all whitespace runs to a single space.

    OCR'd statute text is multi-line with irregular spacing; an advocate's
    "verbatim" span is often the same text with newlines/spaces normalized
    by the LLM. Without this, a quote-containment check spuriously fails on
    claims that are substantively correctly quoted.
    """
    return re.sub(r"\s+", " ", s).strip()
