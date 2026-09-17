from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from labourcrew.config import Settings
from labourcrew.observability import get_current_tracker

logger = logging.getLogger("labourcrew.ocr")

OCR_PROMPT = (
    "You are an OCR engine helping digitize a public-domain Bangladeshi government statute "
    "(the Bangladesh Labour Act, official legislation with no copyright restriction) "
    "for an academic legal-NLP research dataset. "
    "Read the page image and output the printed Bangla text as plain Unicode text, "
    "in correct reading order, with section/subsection numbers and punctuation preserved exactly. "
    "This is a pure OCR/digitization task, not reproduction of protected creative work. "
    "Do not translate or summarize. Output ONLY the Bangla text, nothing else."
)

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|```$", re.MULTILINE)


def render_pdf_pages(pdf_path: Path, dpi: int = 200) -> list[bytes]:
    """Render each PDF page to PNG bytes."""
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        pages.append(pix.tobytes("png"))
    doc.close()
    return pages


def _clean_ocr_text(text: str) -> str:
    """Strip incidental markdown the model sometimes adds (bold, code fences)."""
    text = _CODE_FENCE_RE.sub("", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    return text.strip()


class GeminiPageOCR:
    """OCRs a single rendered page image with Gemini vision."""

    def __init__(self, settings: Settings):
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_ocr_model

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=2, max=30))
    def ocr_page(self, png_bytes: bytes) -> str:
        resp = self._client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
                OCR_PROMPT,
            ],
        )
        if not resp.text:
            raise RuntimeError("Gemini OCR returned empty response")
        usage = resp.usage_metadata
        if usage is not None:
            tracker = get_current_tracker()
            if tracker is not None:
                tracker.add_ocr_usage(
                    self._model,
                    usage.prompt_token_count or 0,
                    usage.candidates_token_count or 0,
                )
            logger.debug(
                "OCR page: model=%s prompt_tokens=%s output_tokens=%s",
                self._model, usage.prompt_token_count, usage.candidates_token_count,
            )
        return _clean_ocr_text(resp.text)


def ocr_pdf_to_pages(
    pdf_path: Path,
    cache_dir: Path,
    settings: Settings,
    dpi: int = 200,
    force: bool = False,
) -> list[str]:
    """OCR every page of `pdf_path`, caching each page's text under `cache_dir`.

    Caching is per-page so a failed/interrupted run only re-OCRs missing pages,
    not the whole document (OCR calls are the expensive, rate-limited step).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    page_images = render_pdf_pages(pdf_path, dpi=dpi)
    ocr = GeminiPageOCR(settings)
    logger.info("OCR'ing %s: %d page(s), cache=%s, force=%s", pdf_path.name, len(page_images), cache_dir, force)

    texts: list[str] = []
    n_cached = 0
    for i, png_bytes in enumerate(page_images, start=1):
        cache_file = cache_dir / f"page_{i:04d}.txt"
        if cache_file.exists() and not force:
            texts.append(cache_file.read_text(encoding="utf-8"))
            n_cached += 1
            continue
        logger.debug("OCR page %d/%d", i, len(page_images))
        text = ocr.ocr_page(png_bytes)
        cache_file.write_text(text, encoding="utf-8")
        texts.append(text)
    logger.info("OCR done: %d page(s) from cache, %d newly OCR'd", n_cached, len(page_images) - n_cached)
    return texts


def assemble_document(pages: list[str]) -> str:
    """Join per-page OCR text into one document, page breaks marked for traceability."""
    parts = []
    for i, page_text in enumerate(pages, start=1):
        parts.append(f"<!-- page {i} -->\n{page_text}")
    return "\n\n".join(parts)
