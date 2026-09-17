from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from labourcrew.config import PROCESSED_DIR, get_settings
from labourcrew.observability import configure_logging, track_costs
from statutegraph.pdf_ocr import assemble_document, ocr_pdf_to_pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path, help="Path to the raw PDF")
    parser.add_argument(
        "--force", action="store_true", help="Re-OCR every page, ignoring cache"
    )
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (higher = sharper OCR, slower)")
    parser.add_argument("--log-level", default=None, help="Override LABOURCREW_LOG_LEVEL (e.g. DEBUG)")
    args = parser.parse_args()

    configure_logging(args.log_level)

    if not args.pdf_path.exists():
        raise SystemExit(f"PDF not found: {args.pdf_path}")

    settings = get_settings()
    stem = args.pdf_path.stem
    cache_dir = PROCESSED_DIR / stem / "pages"

    print(f"OCR'ing {args.pdf_path} -> {cache_dir} (dpi={args.dpi}, force={args.force})")
    with track_costs() as cost:
        pages = ocr_pdf_to_pages(args.pdf_path, cache_dir, settings, dpi=args.dpi, force=args.force)
    print(f"OCR'd {len(pages)} pages.")
    cost.log_summary(prefix="ingest_pdf")
    print(f"Estimated OCR cost: ${cost.total_cost_usd():.6f}")

    doc_text = assemble_document(pages)
    out_path = PROCESSED_DIR / f"{stem}.txt"
    out_path.write_text(doc_text, encoding="utf-8")
    print(f"Wrote assembled text -> {out_path} ({len(doc_text)} chars)")


if __name__ == "__main__":
    main()
