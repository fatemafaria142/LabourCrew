from __future__ import annotations

import re
from dataclasses import dataclass, field

from statutegraph.bangla_numerals import (
    bn_digits_to_int,
    bn_section_num_to_ascii,
    chapter_ordinal_to_int,
)
from statutegraph.schema import ChunkLevel, StatuteChunk

_PAGE_MARKER_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->", re.IGNORECASE)
_PAGE_NUMBER_LINE_RE = re.compile(r"^[০-৯]+$")

_BN_DIGIT = "[০-৯]"
_BN_LETTER_SUFFIX = "[ক-হ]"  # amendment suffix, e.g. ৩ক (section "3-ka")

_CHAPTER_RE = re.compile(rf"^(\S+)\s+অধ্যায়\s*$")
_SECTION_START_RE = re.compile(
    rf"^({_BN_DIGIT}+{_BN_LETTER_SUFFIX}?)\s*।\s*(.+)$", re.DOTALL
)
_SUBSECTION_START_RE = re.compile(rf"^\(({_BN_DIGIT}+)\)\s*(.+)$", re.DOTALL)
_LETTERED_CLAUSE_START_RE = re.compile(rf"^\({_BN_LETTER_SUFFIX}\)\s*")

_PROVISO_RE = re.compile(r"^(তবে\s+)?(আরও\s+)?শর্ত\s+থাকে\s+যে")
_EXPLANATION_RE = re.compile(r"^ব্যাখ্যা\s*[।.:]")

# Cross-reference patterns: "উপ-ধারা (২)" (same-section subsection ref),
# "ধারা ৪" / "ধারা ৪ক" (another section in the same chapter). A single
# "ধারা" often introduces a comma/conjunction-separated list of sections
# ("ধারা ১৯, ২০ অথবা ২৩ এর অধীন") -- _SECTION_REF_RE captures the whole list
# so every number in it is picked up, not just the one right after "ধারা".
_SUBSECTION_REF_RE = re.compile(rf"উপ-?ধারা\s*\(({_BN_DIGIT}+)\)")
_BN_NUM = rf"{_BN_DIGIT}+{_BN_LETTER_SUFFIX}?"
_SECTION_REF_LIST_SEP = r"\s*(?:,|অথবা|এবং|ও|বা)\s*"
_SECTION_REF_RE = re.compile(rf"(?<!উপ-)(?<!উপ)ধারা\s+({_BN_NUM}(?:{_SECTION_REF_LIST_SEP}{_BN_NUM})*)")
_SECTION_REF_NUM_RE = re.compile(_BN_NUM)


def _split_paragraphs(text: str) -> list[str]:
    """Blank-line-separated blocks — the OCR output's own paragraph structure
    lines up with statute structure closely enough to use directly (each
    subsection / proviso / explanation is its own blank-line-delimited block).
    """
    blocks = re.split(r"\n\s*\n", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def _clean_and_join_pages(raw_text: str, running_header: str | None = None) -> str:
    """Strip page markers/footers and rejoin content split mid-paragraph across
    a page boundary.

    Heuristic: if a page's last non-blank line does NOT end in sentence/clause
    -final punctuation, assume the next page continues the same paragraph and
    join without a blank line; otherwise insert a paragraph break.
    """
    pages = _PAGE_MARKER_RE.split(raw_text)
    # re.split with a capturing group yields: ['', '1', page1_text, '2', page2_text, ...]
    page_texts = [pages[i] for i in range(2, len(pages), 2)] if len(pages) > 1 else [raw_text]

    cleaned_pages: list[str] = []
    for page_text in page_texts:
        lines = [ln for ln in page_text.strip().splitlines()]
        kept = []
        for ln in lines:
            s = ln.strip()
            if not s:
                kept.append("")
                continue
            if running_header and s == running_header:
                continue
            if _PAGE_NUMBER_LINE_RE.match(s):
                continue
            kept.append(ln)
        cleaned_pages.append("\n".join(kept).strip())

    if not cleaned_pages:
        return ""

    joined = cleaned_pages[0]
    for page_text in cleaned_pages[1:]:
        if not page_text:
            continue
        prev_tail = joined.rstrip()
        ends_clause = bool(prev_tail) and prev_tail[-1] in "।:;-"
        joined = joined + ("\n\n" if ends_clause else "\n") + page_text
    return joined


@dataclass
class _ParserState:
    chapter_num: int | None = None
    chapter_id: str = ""
    section_id: str | None = None
    section_num: str | None = None
    open_subsection_id: str | None = None
    proviso_count: int = 0
    explanation_count: int = 0
    chunks: dict[str, StatuteChunk] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    awaiting_chapter_title: bool = False

    def add(self, chunk: StatuteChunk) -> None:
        self.chunks[chunk.node_id] = chunk
        self.order.append(chunk.node_id)

    def link_child(self, parent_id: str | None, child_id: str) -> None:
        if parent_id and parent_id in self.chunks:
            self.chunks[parent_id].children_ids.append(child_id)


def chunk_statute(
    raw_text: str,
    version: str,
    statute_prefix: str = "BLA",
    running_header: str | None = None,
) -> list[StatuteChunk]:
    """Parse OCR'd statute text into a flat list of linked StatuteChunks."""
    text = _clean_and_join_pages(raw_text, running_header=running_header)
    blocks = _split_paragraphs(text)
    st = _ParserState()

    for block in blocks:
        first_line = block.splitlines()[0].strip()

        chapter_m = _CHAPTER_RE.match(first_line)
        if chapter_m and len(block.splitlines()) == 1:
            num = chapter_ordinal_to_int(chapter_m.group(1))
            if num is not None:
                st.chapter_num = num
                st.chapter_id = f"{statute_prefix}.Ch{num}"
                st.section_id = None
                st.open_subsection_id = None
                st.awaiting_chapter_title = True
                if st.chapter_id not in st.chunks:
                    st.add(
                        StatuteChunk(
                            node_id=st.chapter_id,
                            level=ChunkLevel.CHAPTER,
                            title="",
                            verbatim_text=block,
                            parent_id=None,
                            version=version,
                        )
                    )
                continue

        if st.awaiting_chapter_title and st.chapter_id in st.chunks:
            st.chunks[st.chapter_id].title = block
            st.awaiting_chapter_title = False
            continue

        section_m = _SECTION_START_RE.match(block)
        if section_m:
            sec_num = bn_section_num_to_ascii(section_m.group(1))
            rest = section_m.group(2)
            chapter_num = st.chapter_num if st.chapter_num is not None else 0
            chapter_id = st.chapter_id or f"{statute_prefix}.Ch{chapter_num}"
            section_id = f"{chapter_id}.S{sec_num}"

            # Title runs up to the first "।-"/"-"/"।" delimiter that precedes the
            # operative text (which itself often starts with a "(১)" marker).
            title, body = _split_title_and_body(rest)

            st.section_id = section_id
            st.section_num = sec_num
            st.open_subsection_id = None
            st.add(
                StatuteChunk(
                    node_id=section_id,
                    level=ChunkLevel.SECTION,
                    title=title,
                    verbatim_text=block,
                    parent_id=chapter_id,
                    version=version,
                )
            )
            st.link_child(chapter_id, section_id)
            _extract_cross_refs(st, section_id, block)

            if body:
                sub_m = _SUBSECTION_START_RE.match(body)
                if sub_m:
                    _add_subsection(st, sub_m.group(1), sub_m.group(2), version)
            continue

        if st.section_id is None:
            # Front matter (title page / preamble) we don't yet have a home
            # for — skip rather than mis-attach it to the wrong section.
            continue

        sub_m = _SUBSECTION_START_RE.match(block)
        if sub_m:
            _add_subsection(st, sub_m.group(1), sub_m.group(2), version, full_block=block)
            continue

        proviso_m = _PROVISO_RE.match(block)
        if proviso_m:
            st.proviso_count += 1
            suffix = "proviso" if st.proviso_count == 1 else f"proviso{st.proviso_count}"
            parent_id = st.open_subsection_id or st.section_id
            proviso_id = f"{parent_id}.{suffix}"
            st.add(
                StatuteChunk(
                    node_id=proviso_id,
                    level=ChunkLevel.PROVISO,
                    verbatim_text=block,
                    parent_id=parent_id,
                    version=version,
                )
            )
            st.chunks[parent_id].proviso_ids.append(proviso_id)
            st.link_child(parent_id, proviso_id)
            _extract_cross_refs(st, proviso_id, block)
            continue

        if _EXPLANATION_RE.match(block):
            st.explanation_count += 1
            suffix = "explanation" if st.explanation_count == 1 else f"explanation{st.explanation_count}"
            explanation_id = f"{st.section_id}.{suffix}"
            st.add(
                StatuteChunk(
                    node_id=explanation_id,
                    level=ChunkLevel.EXPLANATION,
                    verbatim_text=block,
                    parent_id=st.section_id,
                    version=version,
                )
            )
            st.link_child(st.section_id, explanation_id)
            _extract_cross_refs(st, explanation_id, block)
            continue

        if _LETTERED_CLAUSE_START_RE.match(block):
            # Enumerated clause list (ক/খ/গ...) — not an independently citable
            # unit; keep it attached to whichever unit is currently open.
            target_id = st.open_subsection_id or st.section_id
            st.chunks[target_id].verbatim_text += "\n\n" + block
            st.chunks[target_id].char_len = len(st.chunks[target_id].verbatim_text)
            continue

        # Unclassified block: treat as a continuation of the most recently
        # opened chunk rather than silently dropping it.
        target_id = st.open_subsection_id or st.section_id
        if target_id in st.chunks:
            st.chunks[target_id].verbatim_text += "\n\n" + block
            st.chunks[target_id].char_len = len(st.chunks[target_id].verbatim_text)

    return [st.chunks[nid] for nid in st.order]


def _split_title_and_body(rest: str) -> tuple[str, str]:
    """Split '<title>।- <body...>' / '<title>- <body...>' into (title, body)."""
    m = re.match(r"^(.*?)(?:।\s*-|-|।)\s*(.*)$", rest, re.DOTALL)
    if not m:
        return rest.strip(), ""
    title, body = m.group(1).strip(), m.group(2).strip()
    return title, body


def _add_subsection(
    st: _ParserState, num: str, _rest: str, version: str, full_block: str | None = None
) -> None:
    subsection_id = f"{st.section_id}.{bn_digits_to_int(num)}"
    st.open_subsection_id = subsection_id
    text = full_block if full_block is not None else f"({num}) {_rest}"
    st.add(
        StatuteChunk(
            node_id=subsection_id,
            level=ChunkLevel.SUBSECTION,
            verbatim_text=text,
            parent_id=st.section_id,
            version=version,
        )
    )
    st.link_child(st.section_id, subsection_id)
    _extract_cross_refs(st, subsection_id, text)


def _extract_cross_refs(st: _ParserState, node_id: str, text: str) -> None:
    refs: list[str] = []
    if st.section_id:
        for m in _SUBSECTION_REF_RE.finditer(text):
            refs.append(f"{st.section_id}.{bn_digits_to_int(m.group(1))}")
    chapter_id = st.chapter_id
    for m in _SECTION_REF_RE.finditer(text):
        for num in _SECTION_REF_NUM_RE.findall(m.group(1)):
            ref_id = f"{chapter_id}.S{bn_section_num_to_ascii(num)}"
            if ref_id != st.section_id:
                refs.append(ref_id)
    if refs and node_id in st.chunks:
        existing = st.chunks[node_id].cross_refs
        for r in refs:
            if r not in existing:
                existing.append(r)
