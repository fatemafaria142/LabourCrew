from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Callable

from pymilvus import MilvusClient

from labourcrew.config import Settings, get_settings
from statutegraph.embeddings import Embedder, get_embedder
from statutegraph.milvus_store import get_client
from statutegraph.schema import EvidencePack

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_ROOT / "input"

CATEGORY_ORDER = [
    "direct_factual_retrieval",
    "definitional_classification",
    "procedural_reasoning",
    "conditional_reasoning",
    "comparative_reasoning",
    "multi_hop_reasoning",
    "hypothetical_legal_reasoning",
]
CATEGORY_LABELS = {
    "direct_factual_retrieval": "Direct Factual Retrieval",
    "definitional_classification": "Definitional and Classification",
    "procedural_reasoning": "Procedural Reasoning",
    "conditional_reasoning": "Conditional Reasoning",
    "comparative_reasoning": "Comparative Reasoning",
    "multi_hop_reasoning": "Multi-hop Reasoning",
    "hypothetical_legal_reasoning": "Hypothetical Legal Reasoning",
}

# Bangla Unicode block (U+0980-U+09FF) words, Bangla digit runs, or ASCII words --
# good enough for a lexical-overlap heuristic over this corpus's bilingual text.
_TOKEN_RE = re.compile(r"[ঀ-৿]+|[A-Za-z]+")
# High-frequency function words that would otherwise inflate coverage regardless
# of whether the retrieval actually found the relevant provision.
_STOPWORDS = {
    "এবং", "বা", "এর", "এই", "যে", "না", "হবে", "করিতে", "করিবে", "উক্ত",
    "কোন", "কোনো", "যদি", "তাহা", "তাহার", "সহ", "হইতে", "মধ্যে", "অথবা",
    "the", "a", "an", "of", "to", "and", "or", "is", "in", "on", "for",
}


@dataclass
class RunContext:
    client: MilvusClient
    settings: Settings
    embedder: Embedder


def build_context() -> RunContext:
    settings = get_settings()
    client = get_client(settings)
    embedder = get_embedder(settings)
    return RunContext(client=client, settings=settings, embedder=embedder)


def load_questions(chapters: list[int]) -> list[dict]:
    """Load and concatenate input/chapter-<N>.json for each chapter number."""
    questions: list[dict] = []
    for ch in chapters:
        path = INPUT_DIR / f"chapter-{ch}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for q in data:
            row = dict(q)
            row["chapter"] = ch
            questions.append(row)
    return questions


def tokenize(text: str) -> set[str]:
    tokens = _TOKEN_RE.findall(text or "")
    return {t for t in tokens if len(t) >= 2 and t not in _STOPWORDS}


def gold_term_coverage(gold_text: str, retrieved_texts: list[str]) -> float | None:
    """Fraction of significant gold_answer_bn tokens found verbatim in the
    concatenated retrieved evidence text. None if the gold answer has no
    scorable tokens."""
    gold_tokens = tokenize(gold_text)
    if not gold_tokens:
        return None
    retrieved_tokens = tokenize(" ".join(retrieved_texts))
    return len(gold_tokens & retrieved_tokens) / len(gold_tokens)


RetrieveFn = Callable[[RunContext, dict], tuple[EvidencePack, float]]


def make_retrieve_fn(method_fn: Callable[[RunContext, str], EvidencePack]) -> RetrieveFn:
    """Wrap a `(ctx, query_text) -> EvidencePack` method function into a
    `(ctx, question_row) -> (EvidencePack, elapsed_seconds)` retrieve_fn,
    querying with the Bangla question text (matching the corpus language)."""

    def retrieve_fn(ctx: RunContext, q: dict) -> tuple[EvidencePack, float]:
        query = q.get("question_bn") or q.get("question_en") or ""
        t0 = time.perf_counter()
        pack = method_fn(ctx, query)
        elapsed = time.perf_counter() - t0
        return pack, elapsed

    return retrieve_fn


def _avg(values: list[float | None]) -> float | None:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _fmt(v: float | None, digits: int = 3) -> str:
    return f"{v:.{digits}f}" if isinstance(v, (int, float)) else "N/A"


def run_experiment(
    method_name: str,
    method_slug: str,
    retrieve_fn: RetrieveFn,
    chapters: list[int],
    out_dir: Path,
    limit: int | None = None,
    extra_config: dict | None = None,
) -> None:
    """Run `retrieve_fn` over every question in the given chapters, print
    per-question progress, and write raw_results.json + metrics.md to out_dir."""
    ctx = build_context()
    questions = load_questions(chapters)
    if limit:
        questions = questions[:limit]

    print(f"[{method_name}] running {len(questions)} question(s) from chapters {chapters}", flush=True)

    rows: list[dict] = []
    for i, q in enumerate(questions, 1):
        pack, elapsed = retrieve_fn(ctx, q)
        texts = [n.verbatim_text for n in pack.nodes]
        coverage = gold_term_coverage(q.get("gold_answer_bn", ""), texts)
        row = {
            "id": q["id"],
            "category": q["category"],
            "difficulty": q.get("difficulty"),
            "chapter": q["chapter"],
            "n_retrieved": len(pack.nodes),
            "n_hops": len(pack.paths),
            "latency_s": round(elapsed, 3),
            "gold_term_coverage": coverage,
            "node_ids": [n.node_id for n in pack.nodes],
        }
        rows.append(row)
        cov_str = _fmt(coverage)
        print(
            f"  [{i}/{len(questions)}] {q['id']} ({q['category']}): "
            f"n_retrieved={len(pack.nodes)} coverage={cov_str} latency={elapsed:.2f}s",
            flush=True,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw_results.json"
    raw_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    report_path = out_dir / "metrics.md"
    write_report(method_name, method_slug, rows, report_path, extra_config or {})

    print(f"\n[{method_name}] wrote {raw_path}")
    print(f"[{method_name}] wrote {report_path}")


def write_report(
    method_name: str, method_slug: str, rows: list[dict], path: Path, extra_config: dict
) -> None:
    lines = [
        f"# Ablation Study: {method_name}\n",
        f"{len(rows)} questions from `input/chapter-*.json`, retrieval-only "
        f"(no debate/trust-gate/generation stage). Config: "
        f"{', '.join(f'{k}={v}' for k, v in extra_config.items()) or 'defaults'}.\n",
        "**Gold Term Coverage** is a deterministic lexical-overlap proxy (fraction "
        "of significant `gold_answer_bn` tokens found in the retrieved evidence "
        "text) -- not an LLM-judged relevance score, and not comparable to "
        "`paper/result-table.md` Table 1's Initial Retrieval Precision.\n",
        "## By category\n",
        "| Category | N | Avg Latency (s) | Avg N Retrieved | Avg Hops | Avg Gold Term Coverage |",
        "|---|---|---|---|---|---|",
    ]
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)

    for cat in CATEGORY_ORDER:
        cat_rows = by_cat.get(cat)
        if not cat_rows:
            continue
        label = CATEGORY_LABELS.get(cat, cat)
        lines.append(
            f"| {label} | {len(cat_rows)} | "
            f"{_fmt(_avg([r['latency_s'] for r in cat_rows]), 2)} | "
            f"{_fmt(_avg([r['n_retrieved'] for r in cat_rows]), 2)} | "
            f"{_fmt(_avg([r['n_hops'] for r in cat_rows]), 2)} | "
            f"{_fmt(_avg([r['gold_term_coverage'] for r in cat_rows]))} |"
        )

    lines.append(
        f"| **Aggregate** | **{len(rows)}** | "
        f"**{_fmt(_avg([r['latency_s'] for r in rows]), 2)}** | "
        f"**{_fmt(_avg([r['n_retrieved'] for r in rows]), 2)}** | "
        f"**{_fmt(_avg([r['n_hops'] for r in rows]), 2)}** | "
        f"**{_fmt(_avg([r['gold_term_coverage'] for r in rows]))}** |"
    )

    unscored = sum(1 for r in rows if r["gold_term_coverage"] is None)
    if unscored:
        lines.append(f"\n{unscored} question(s) had no scorable gold_answer_bn tokens and are excluded from the coverage average.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
