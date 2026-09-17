from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import types
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ragas 0.4.3's ragas.llms.base unconditionally imports
# langchain_community.chat_models.vertexai, a submodule this langchain-community
# version no longer ships (langchain-community is being sunset upstream). We
# don't use VertexAI at all, so stub the import rather than pin/downgrade
# langchain-community and risk breaking the rest of the stack.
_stub = types.ModuleType("langchain_community.chat_models.vertexai")


class _StubChatVertexAI:  # pragma: no cover - never instantiated
    pass


_stub.ChatVertexAI = _StubChatVertexAI
sys.modules.setdefault("langchain_community.chat_models.vertexai", _stub)

from dotenv import load_dotenv  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from ragas.embeddings import HuggingFaceEmbeddings  # noqa: E402
from ragas.llms import llm_factory  # noqa: E402
from ragas.llms.base import InstructorBaseRagasLLM  # noqa: E402
from ragas.metrics.collections import (  # noqa: E402
    AnswerCorrectness,
    AnswerRelevancy,
    ContextEntityRecall,
    ContextPrecision,
    ContextRecall,
    ContextRelevance,
    Faithfulness,
    NoiseSensitivity,
)

from labourcrew.config import get_settings  # noqa: E402
from labourcrew.observability import configure_logging  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
RAGAS_JUDGE_MODEL = "gpt-4o"
# Same embedding model used for chunk/query embedding (statutegraph.embeddings.BGEEmbedder)
# -- one embedding space end-to-end instead of mixing in an English-centric OpenAI
# embedding model just for RAGAS's Answer Relevancy semantic-similarity term.
RAGAS_EMBED_MODEL = get_settings().bge_model_name

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


METRIC_NAMES = [
    "faithfulness",
    "answer_relevancy",
    "answer_correctness",
    "context_precision",
    "context_recall",
    "context_relevance",
    "noise_sensitivity",
    "context_entity_recall",
]


def _print(msg: str) -> None:
    print(msg, flush=True)


class JudgeLLM(InstructorBaseRagasLLM):
    """Judge-LLM wrapper that counts API calls and de-duplicates identical prompts.

    Two savings, neither of which changes any score:

    1. Several metrics ask the judge for the *same* thing. Faithfulness and
       Answer Correctness both decompose the response into atomic statements
       with a byte-identical prompt (both use ragas's shared
       StatementGeneratorPrompt -- verified equal, including the embedded JSON
       schema), so without this wrapper the same call is paid for twice.
    2. Because `score_ragas` fires all metrics through one `asyncio.gather`,
       those duplicates are usually *in flight simultaneously*, so a plain
       result cache would miss on both. Keying on the in-flight future instead
       makes the second caller await the first one's result.

    The prompt string embeds the full output JSON schema, so an identical
    prompt cannot mean two different requests -- the prompt alone is a safe
    cache key even though the callers pass different (structurally identical)
    response_model classes. The judge runs at temperature 0.01, so a re-ask
    would have returned the same thing anyway.

    Cache is per question (`reset()` between questions): prompts embed the
    question/answer/context, so cross-question hits are impossible and holding
    them just grows memory.
    """

    def __init__(self, inner: InstructorBaseRagasLLM) -> None:
        self._inner = inner
        self._inflight: dict[str, asyncio.Future] = {}
        self.calls = 0
        self.deduped = 0

    def reset(self) -> None:
        self._inflight.clear()

    def generate(self, prompt: str, response_model):  # pragma: no cover - metrics use agenerate
        self.calls += 1
        return self._inner.generate(prompt, response_model)

    async def agenerate(self, prompt: str, response_model):
        fut = self._inflight.get(prompt)
        if fut is None:
            self.calls += 1
            fut = asyncio.ensure_future(self._inner.agenerate(prompt, response_model))
            self._inflight[prompt] = fut
        else:
            self.deduped += 1
        return await fut


class SafeNoiseSensitivity(NoiseSensitivity):
    """NoiseSensitivity that survives a judge returning the wrong number of verdicts.

    Upstream builds its verdict matrices with `np.array(list_of_verdict_lists).T`,
    which assumes the judge returns exactly one verdict per input statement for
    every context. When it doesn't -- common on long Bangla narratives -- the
    lists are ragged and numpy raises, so the metric returns None *after* every
    one of its LLM calls has already been paid for. That is what produced the
    `N/A` noise_sensitivity cells in the chapter-2/3/4 reports (15 of 34 in
    chapter 3), all on questions that do have a generated answer.

    Padding a short verdict list with 0 (== "not inferable from this context")
    is the conservative reading: an unjudged statement is not counted as
    supported.
    """

    async def _evaluate_statement_faithfulness(self, statements: list[str], context: str) -> list[int]:
        verdicts = await super()._evaluate_statement_faithfulness(statements, context)
        if len(verdicts) < len(statements):
            verdicts = verdicts + [0] * (len(statements) - len(verdicts))
        return verdicts[: len(statements)]


async def score_ragas(
    llm,
    emb,
    question_bn: str,
    answer: str,
    contexts: list[str],
    reference: str,
    *,
    top_k: int | None = 5,
    strictness: int = 1,
    skip: frozenset[str] = frozenset(),
) -> dict:
    contexts = contexts or ["(কোনো তথ্যসূত্র পাওয়া যায়নি)"]
    # Context Precision costs one judge call per chunk and Noise Sensitivity two,
    # so a 15-chunk question costs 3x a 5-chunk one for those two metrics while
    # every other metric is flat. Cap them at the top-k retrieved chunks
    # (retriever rank order is preserved in raw_runs), making them precision@k /
    # noise@k at a fixed price. The metrics that concatenate all chunks into a
    # single prompt (Faithfulness, Context Recall, Context Relevance, Context
    # Entity Recall) still see the full retrieval -- they cost 1-2 calls either
    # way, so there is nothing to gain by degrading them.
    ranked = contexts[:top_k] if top_k else contexts

    # Built lazily: constructing a coroutine for a skipped metric and then
    # dropping it triggers "coroutine was never awaited".
    factories = {
        "faithfulness": lambda: Faithfulness(llm=llm).ascore(
            user_input=question_bn, response=answer, retrieved_contexts=contexts
        ),
        # strictness = how many questions the judge reverse-generates from the
        # answer before comparing them to the real one. Upstream default is 3
        # (i.e. 3 identical prompts) as a variance-reduction measure, but at
        # temperature 0.01 the three samples are near-duplicates -- 2 of the 3
        # calls buy almost nothing.
        "answer_relevancy": lambda: AnswerRelevancy(
            llm=llm, embeddings=emb, strictness=strictness
        ).ascore(user_input=question_bn, response=answer),
        "answer_correctness": lambda: AnswerCorrectness(llm=llm, embeddings=emb).ascore(
            user_input=question_bn, response=answer, reference=reference
        ),
        "context_precision": lambda: ContextPrecision(llm=llm).ascore(
            user_input=question_bn, reference=reference, retrieved_contexts=ranked
        ),
        "context_recall": lambda: ContextRecall(llm=llm).ascore(
            user_input=question_bn, retrieved_contexts=contexts, reference=reference
        ),
        "context_relevance": lambda: ContextRelevance(llm=llm).ascore(
            user_input=question_bn, retrieved_contexts=contexts
        ),
        # mode="irrelevant": what fraction of incorrect claims in the answer trace back
        # to off-topic (not question-relevant) retrieved context -- directly measures
        # whether noisy/over-fetched retrieval corrupts the answer, complementing
        # Context Precision (which only judges the chunks in isolation, not their
        # actual effect on the generated text).
        "noise_sensitivity": lambda: SafeNoiseSensitivity(llm=llm, mode="irrelevant").ascore(
            user_input=question_bn, response=answer, reference=reference, retrieved_contexts=ranked
        ),
        "context_entity_recall": lambda: ContextEntityRecall(llm=llm).ascore(
            reference=reference, retrieved_contexts=contexts
        ),
    }

    names = [n for n in METRIC_NAMES if n not in skip]
    results = await asyncio.gather(*(factories[n]() for n in names), return_exceptions=True)
    out = {n: None for n in METRIC_NAMES}
    for name, r in zip(names, results):
        if isinstance(r, Exception):
            _print(f"    ! ragas metric {name} failed: {r}")
        else:
            out[name] = float(r.value)
    return out


def _avg(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _fmt(v, digits: int = 3) -> str:
    return f"{v:.{digits}f}" if isinstance(v, (int, float)) else "N/A"


def write_ragas_report(rows: list[dict], out_path: Path, chapter: str, cfg: dict | None = None) -> None:
    cfg = cfg or {}
    judge = cfg.get("judge_model", RAGAS_JUDGE_MODEL)
    top_k = cfg.get("top_k")
    lines = [
        f"# RAGAS Metrics — LabourActQA Chapter {chapter} (Bangla)\n",
        f"Judge model: `{judge}` (OpenAI). Embeddings for Answer Relevancy's "
        f"semantic-similarity term: `{RAGAS_EMBED_MODEL}`. {len(rows)} questions scored, entirely "
        "in Bangla: `question_bn` / `gold_answer_bn` against the board's Bangla narrative and the "
        "(Bangla) retrieved statute text.\n",
        "Scoring configuration: per-chunk metrics (Context Precision, Noise Sensitivity) scored over "
        + (f"the **top-{top_k}** retrieved chunks" if top_k else "**all** retrieved chunks")
        + f"; Answer Relevancy strictness **{cfg.get('strictness', 1)}**"
        + (f"; skipped: {', '.join(sorted(cfg['skip']))}" if cfg.get("skip") else "")
        + ".\n",
        "## By category\n",
        "| Category | Difficulty | N | Faithfulness | Answer Relevancy | Answer Correctness | "
        "Context Relevancy | Context Precision | Context Recall | Noise Sensitivity | "
        "Context Entity Recall | Citation-Based Precision |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    metric_keys = [
        "faithfulness",
        "answer_relevancy",
        "answer_correctness",
        "context_relevance",
        "context_precision",
        "context_recall",
        "noise_sensitivity",
        "context_entity_recall",
        "citation_based_precision",
    ]
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    for cat in CATEGORY_ORDER:
        crows = by_cat.get(cat, [])
        if not crows:
            continue
        diff = crows[0]["difficulty"]
        cells = " | ".join(_fmt(_avg([r[k] for r in crows])) for k in metric_keys)
        lines.append(f"| {CATEGORY_LABELS[cat]} | {diff} | {len(crows)} | {cells} |")
    bold_cells = " | ".join(f"**{_fmt(_avg([r[k] for r in rows]))}**" for k in metric_keys)
    lines.append(f"| **Overall** | — | {len(rows)} | {bold_cells} |")
    lines += [
        "\n## Per-question scores\n",
        "| ID | Category | Faithfulness | Answer Relevancy | Answer Correctness | Context Relevancy | "
        "Context Precision | Context Recall | Noise Sensitivity | Context Entity Recall | "
        "Citation-Based Precision |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        cells = " | ".join(_fmt(r[k]) for k in metric_keys)
        lines.append(f"| {r['id']} | {CATEGORY_LABELS[r['category']]} | {cells} |")
    lines += [
        "\n## Methodology notes\n",
        "- All RAGAS metrics are scored against `question_bn` / `gold_answer_bn` — the board's agent "
        "prompts require Bangla output end-to-end (claims, interpreter notes, final narrative), so "
        "question, generated answer, retrieved context, and reference are all Bangla for every metric.",
        "- Answer Relevancy measures how well the answer addresses the question itself (via "
        "generated-question / original-question embedding similarity) — it does NOT check factual "
        "correctness against `gold_answer_bn`; a fluent, on-topic, but factually wrong answer can still "
        "score high here. Answer Correctness (factual + semantic match to `gold_answer_bn`) is the "
        "metric to read for \"is this actually right\" — Answer Relevancy and Answer Correctness are "
        "complementary, not substitutes for each other.",
        "- Context Relevancy scores retrieved passages against the question alone (no reference "
        "answer needed).",
        "- Noise Sensitivity (mode=irrelevant) measures what fraction of incorrect statements in the "
        "answer trace back to off-topic retrieved context — a direct, output-side test of whether "
        "over-fetched/noisy retrieval actually corrupts the answer, complementing Context Precision "
        "(which only judges each retrieved chunk in isolation against the reference, not its effect on "
        "the generated text). Lower is better here (it's a sensitivity/error rate, not a quality score).",
        "- Context Entity Recall checks whether specific entities in `gold_answer_bn` (section numbers, "
        "day-counts, monetary amounts) actually appear in the retrieved context — a sharper, more literal "
        "signal than Context Recall for statute QA where the exact number is the fact being asked for.",
        "- Citation-Based Precision is NOT a RAGAS/judge-model metric: it's `|retrieved nodes cited by an "
        "accepted claim| / |retrieved nodes|`, computed deterministically in `scripts/evaluate_system.py` "
        "from the board's own citation graph and merged in here for direct comparison against Context "
        "Precision. Unlike Context Precision, it isn't penalized for fetching chunks needed for one "
        "concept in a comparative/multi-hop question just because they don't individually match the "
        f"whole reference answer — see `system_metrics_chapter-{chapter}.md` for its per-category breakdown too.",
        "- A `None`/`N/A` score means that metric raised for that question — either the board produced no "
        f"narrative to score (see `final_status` in `raw_runs_chapter-{chapter}.json`, most often an "
        "`UNDECIDED` result with no claims to compose an opinion from), or the judge returned a malformed "
        "response the metric could not consume. The specific failure is printed by the scoring run.",
        f"- Source trace: `output/raw_runs_chapter-{chapter}.json`, produced by `scripts/evaluate_system.py` "
        "(this script does not re-run the board).",
    ]
    if top_k:
        lines.insert(
            -1,
            f"- Context Precision and Noise Sensitivity are scored over the top-{top_k} retrieved chunks "
            "(precision@k / noise@k) rather than over all of them: they are the only two metrics priced "
            "*per chunk* (1 and 2 judge calls each), so scoring every chunk made a 15-chunk question cost "
            "3x a 5-chunk one. Every other metric still sees the full retrieval.",
        )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _save_all(rows: list[dict], chapter: str, cfg: dict | None = None) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / f"ragas_scores_chapter-{chapter}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if rows:
        write_ragas_report(rows, OUTPUT_DIR / f"ragas_metrics_chapter-{chapter}.md", chapter, cfg)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chapter", default="2",
        help="dataset suffix: reads output/raw_runs_chapter-<N>.json, writes ragas_*_chapter-<N>.{json,md} (default: 2)",
    )
    parser.add_argument("--limit", type=int, default=None, help="only score the first N questions (smoke test)")
    parser.add_argument(
        "--resume", action="store_true",
        help="skip question ids already present in output/ragas_scores_chapter-<N>.json instead of re-scoring them",
    )
    parser.add_argument("--log-level", default=None, help="Override LABOURCREW_LOG_LEVEL (e.g. DEBUG)")
    parser.add_argument(
        "--judge-model", default=RAGAS_JUDGE_MODEL,
        help=f"OpenAI model used as RAGAS judge (default: {RAGAS_JUDGE_MODEL}). "
             "gpt-4o-mini costs a fraction of gpt-4o per call but is a weaker judge on Bangla.",
    )
    parser.add_argument(
        "--score-top-k", type=int, default=5,
        help="Score only the top-k retrieved chunks with the per-chunk metrics (Context Precision, "
             "Noise Sensitivity), which cost 1 and 2 judge calls per chunk respectively. 0 = all chunks "
             "(upstream behaviour). Default: 5",
    )
    parser.add_argument(
        "--strictness", type=int, default=1,
        help="Answer Relevancy: number of questions reverse-generated from the answer, one judge call "
             "each (upstream default 3, near-duplicates at temperature 0.01). Default: 1",
    )
    parser.add_argument(
        "--skip", default="", metavar="M1,M2",
        help="Comma-separated metrics to skip entirely, e.g. --skip noise_sensitivity (the single "
             f"most expensive metric). Choices: {','.join(METRIC_NAMES)}",
    )
    args = parser.parse_args()
    chapter = args.chapter

    skip = frozenset(m.strip() for m in args.skip.split(",") if m.strip())
    unknown = skip - set(METRIC_NAMES)
    if unknown:
        raise SystemExit(f"--skip: unknown metric(s) {sorted(unknown)}. Choices: {METRIC_NAMES}")
    top_k = args.score_top_k or None

    configure_logging(args.log_level)
    # NOTE: RAGAS's judge/embedding calls go through its own AsyncOpenAI/HF
    # clients, not LangChain, so they aren't captured by
    # labourcrew.observability's cost tracker (which hooks LangChain's
    # usage-metadata callback). Judge model is RAGAS_JUDGE_MODEL (gpt-4o) --
    # see OpenAI's usage dashboard for actual spend from this script.

    raw_runs_path = OUTPUT_DIR / f"raw_runs_chapter-{chapter}.json"
    if not raw_runs_path.exists():
        raise SystemExit(
            f"{raw_runs_path} not found. Run `python scripts/evaluate_system.py --chapter {chapter}` first to produce it."
        )
    raw_runs = json.loads(raw_runs_path.read_text(encoding="utf-8"))
    if args.limit:
        raw_runs = raw_runs[: args.limit]
        scores_path = OUTPUT_DIR / f"ragas_scores_chapter-{chapter}.json"
        if scores_path.exists() and not args.resume:
            # _save_all rewrites the scores file from the rows scored *this* run,
            # so a --limit smoke test would replace a full chapter's results with
            # a handful of rows.
            _print(
                f"WARNING: --limit {args.limit} will overwrite {scores_path.name} "
                f"(currently {len(json.loads(scores_path.read_text(encoding='utf-8')))} rows) "
                "with only the scored subset. Add --resume to keep the existing rows."
            )

    # Carried into the report header so a table always records the scoring
    # settings that produced it (top-k in particular changes what Context
    # Precision / Noise Sensitivity mean).
    cfg = {
        "judge_model": args.judge_model,
        "top_k": top_k,
        "strictness": args.strictness,
        "skip": sorted(skip),
    }

    ragas_rows: list[dict] = []
    done_ids: set[str] = set()
    if args.resume:
        scores_path = OUTPUT_DIR / f"ragas_scores_chapter-{chapter}.json"
        if scores_path.exists():
            ragas_rows = json.loads(scores_path.read_text(encoding="utf-8"))
            done_ids = {r["id"] for r in ragas_rows}
        _print(f"Resuming: {len(done_ids)} question(s) already scored, skipping them.")

    oai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    # Default max_tokens (1024) truncates judge output on longer narratives/contexts
    # (faithfulness generates structured statement lists) -- raise it.
    ragas_llm = JudgeLLM(llm_factory(args.judge_model, client=oai_client, max_tokens=4096))
    # Local sentence-transformers model, same one used for chunk/query embedding --
    # no OpenAI embeddings call, no extra API cost for this part of scoring.
    ragas_emb = HuggingFaceEmbeddings(model=RAGAS_EMBED_MODEL)

    for i, run in enumerate(raw_runs, 1):
        qid = run["id"]
        if qid in done_ids:
            continue
        _print(f"[{i}/{len(raw_runs)}] {qid} ({run['category']})...")

        ragas_llm.reset()
        calls_before, deduped_before = ragas_llm.calls, ragas_llm.deduped
        ragas_scores = asyncio.run(
            score_ragas(
                ragas_llm,
                ragas_emb,
                question_bn=run["question_bn"],
                answer=run.get("generated_answer") or "(কোনো উত্তর তৈরি হয়নি)",
                contexts=run.get("retrieved_contexts") or [],
                reference=run["gold_answer_bn"],
                top_k=top_k,
                strictness=args.strictness,
                skip=skip,
            )
        )
        q_calls = ragas_llm.calls - calls_before
        q_deduped = ragas_llm.deduped - deduped_before
        ragas_rows.append(
            {
                "id": qid,
                "category": run["category"],
                "difficulty": run["difficulty"],
                **ragas_scores,
                # Deterministic, non-judge-model metric computed in scripts/evaluate_system.py --
                # carried through here so it lands in the same report/table for direct comparison.
                "citation_based_precision": run.get("citation_based_precision"),
            }
        )
        _print(
            f"    faithfulness={_fmt(ragas_scores.get('faithfulness'))} "
            f"answer_relevancy={_fmt(ragas_scores.get('answer_relevancy'))} "
            f"answer_correctness={_fmt(ragas_scores.get('answer_correctness'))} "
            f"context_relevance={_fmt(ragas_scores.get('context_relevance'))} "
            f"context_precision={_fmt(ragas_scores.get('context_precision'))} "
            f"context_recall={_fmt(ragas_scores.get('context_recall'))} "
            f"noise_sensitivity={_fmt(ragas_scores.get('noise_sensitivity'))} "
            f"context_entity_recall={_fmt(ragas_scores.get('context_entity_recall'))} "
            f"citation_based_precision={_fmt(run.get('citation_based_precision'))}"
        )
        _print(f"    judge calls: {q_calls} ({q_deduped} deduped, {len(run.get('retrieved_contexts') or [])} chunks retrieved)")
        # Save after every question so an interruption doesn't lose completed scoring.
        _save_all(ragas_rows, chapter, cfg)

    _save_all(ragas_rows, chapter, cfg)
    scored = len(ragas_rows) - len(done_ids)
    _print(f"\nDone. {len(ragas_rows)}/{len(raw_runs)} questions scored. Results in {OUTPUT_DIR}")
    _print(
        f"Judge API calls this run: {ragas_llm.calls} ({args.judge_model})"
        + (f", mean {ragas_llm.calls / scored:.1f}/question" if scored else "")
        + f"; {ragas_llm.deduped} duplicate prompt(s) served from cache."
    )


if __name__ == "__main__":
    main()
