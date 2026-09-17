from __future__ import annotations

import re

_BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_BN_TO_ASCII = str.maketrans(_BN_DIGITS, "0123456789")

# Ordinal chapter-name words as printed in Bangla statutes (১-৩০ covers any
# real-world Bangladesh Labour Act chapter; extend if a document uses higher).
_CHAPTER_ORDINALS: dict[str, int] = {
    "প্রথম": 1,
    "দ্বিতীয়": 2,
    "তৃতীয়": 3,
    "চতুর্থ": 4,
    "পঞ্চম": 5,
    "ষষ্ঠ": 6,
    "সপ্তম": 7,
    "অষ্টম": 8,
    "নবম": 9,
    "দশম": 10,
    "একাদশ": 11,
    "দ্বাদশ": 12,
    "ত্রয়োদশ": 13,
    "চতুর্দশ": 14,
    "পঞ্চদশ": 15,
    "ষোড়শ": 16,
    "সপ্তদশ": 17,
    "অষ্টাদশ": 18,
    "ঊনবিংশ": 19,
    "বিংশ": 20,
    "একবিংশ": 21,
    "দ্বাবিংশ": 22,
    "ত্রয়োবিংশ": 23,
    "চতুর্বিংশ": 24,
    "পঞ্চবিংশ": 25,
    "ষড়বিংশ": 26,
    "সপ্তবিংশ": 27,
    "অষ্টাবিংশ": 28,
    "ঊনত্রিংশ": 29,
    "ত্রিংশ": 30,
}


def bn_digits_to_int(s: str) -> int:
    """Convert a run of Bangla digits (e.g. '১২০') to an int (120)."""
    return int(s.translate(_BN_TO_ASCII))


def bn_section_num_to_ascii(s: str) -> str:
    """Convert a section number's digit run to ASCII, keeping any trailing
    Bangla amendment-letter suffix as-is (e.g. '৩ক' -> '3ক', '৩' -> '3').
    """
    return s.translate(_BN_TO_ASCII)


def chapter_ordinal_to_int(word: str) -> int | None:
    """Map a Bangla ordinal chapter-name word (e.g. 'দ্বিতীয়') to its number."""
    return _CHAPTER_ORDINALS.get(word.strip())


_BN_LETTER_SUFFIX = "[ক-য]"
_BN_NUM = rf"[{_BN_DIGITS}]+{_BN_LETTER_SUFFIX}?"
# A conjunction/comma-separated list following one "ধারা": "১৯, ২০ অথবা ২৩"
# refers to sections 19, 20, AND 23 -- not just the first number. Bangla
# statutes routinely cite a run of sections this way (e.g. "ধারা ১৯, ২০
# অথবা ২৩ এর অধীন"), so a naive "one number right after ধারা" match silently
# drops every number after the first.
_LIST_SEP = r"\s*(?:,|অথবা|এবং|ও|বা)\s*"
# "ধারা ২০" / "ধারা ৩ক" but not "উপ-ধারা (২০)" (a subsection reference).
_QUESTION_SECTION_REF_BN_RE = re.compile(rf"(?<!উপ-)(?<!উপ)ধারা\s+({_BN_NUM}(?:{_LIST_SEP}{_BN_NUM})*)")
_QUESTION_SECTION_REF_EN_RE = re.compile(r"\bsection\s+(\d+[a-zA-Z]?)\b", re.IGNORECASE)
_BN_NUM_RE = re.compile(_BN_NUM)


def extract_referenced_section_nums(text: str) -> list[str]:
    """Pull explicit section-number references out of a free-form question.

    Matches Bangla "ধারা ২০" (never "উপ-ধারা", a subsection ref) -- including
    comma/conjunction-separated lists like "ধারা ১৯, ২০ অথবা ২৩" (all three
    numbers) -- and English "section 20", returning ASCII-digit section
    numbers (amendment-letter suffix preserved, e.g. "3ক") suitable for an
    exact node_id suffix match ("...S{num}") against StatuteChunk node_ids.
    """
    nums: list[str] = []
    for m in _QUESTION_SECTION_REF_BN_RE.finditer(text):
        for num in _BN_NUM_RE.findall(m.group(1)):
            nums.append(bn_section_num_to_ascii(num))
    for m in _QUESTION_SECTION_REF_EN_RE.finditer(text):
        nums.append(m.group(1))
    # de-dupe, preserve order
    seen: set[str] = set()
    out = []
    for n in nums:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out
