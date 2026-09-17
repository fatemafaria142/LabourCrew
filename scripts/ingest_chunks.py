from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from labourcrew.config import get_settings
from labourcrew.observability import configure_logging, track_costs
from statutegraph.chunking import chunk_statute
from statutegraph.embeddings import get_embedder
from statutegraph.milvus_store import ensure_collection, get_client, upsert_chunks

RUNNING_HEADER_DEFAULT = "বাংলাদেশ শ্রম আইন, ২০০৬"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text_path", type=Path, help="OCR'd statute .txt (from scripts/ingest_pdf.py)")
    parser.add_argument(
        "--running-header",
        default=RUNNING_HEADER_DEFAULT,
        help="Repeating page header line to strip (default: Bangladesh Labour Act running header)",
    )
    parser.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Drop and recreate the Milvus collection before upserting",
    )
    parser.add_argument("--log-level", default=None, help="Override LABOURCREW_LOG_LEVEL (e.g. DEBUG)")
    args = parser.parse_args()

    configure_logging(args.log_level)

    if not args.text_path.exists():
        raise SystemExit(f"Text file not found: {args.text_path}")

    settings = get_settings()
    raw_text = args.text_path.read_text(encoding="utf-8")

    chunks = chunk_statute(raw_text, version=settings.statute_version, running_header=args.running_header)
    print(f"Parsed {len(chunks)} chunks from {args.text_path.name}")
    by_level: dict[str, int] = {}
    for c in chunks:
        by_level[c.level.value] = by_level.get(c.level.value, 0) + 1
    print("By level:", by_level)

    client = get_client(settings)
    try:
        embedder = get_embedder(settings)
        ensure_collection(client, settings, embed_dim=embedder.dim, recreate=args.recreate_collection)
        with track_costs() as cost:
            n = upsert_chunks(client, settings, chunks, embedder)
        print(f"Upserted {n} chunks into Milvus collection '{settings.statutegraph_milvus_collection}'")
        cost.log_summary(prefix="ingest_chunks")
        print(f"Estimated embedding cost: ${cost.total_cost_usd():.6f}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
