"""
src/parser_text.py — Module 3: Universal Text Extractor
───────────────────────────────────────────────────────
Converts downloaded documents (PDF, HTML/TXT) into clean UTF-8 text
payloads ready for the LLM.

Key behaviours:
  • PyMuPDF (fitz) for standard PDFs
  • pytesseract fallback for scanned-image PDFs (< 100 chars extracted)
  • OCR runs via asyncio.to_thread() to avoid blocking the event loop
  • Boilerplate trimming before concatenation
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from config.settings import (
    EXTRACTED_TEXT_DIR,
    MIN_TEXT_FOR_OCR_FALLBACK,
    OCR_MAX_PAGES,
    TESSERACT_CMD,
)
from src.models import SchoolProcessingStatus
from src.state import StateManager

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Boilerplate patterns to strip
# ──────────────────────────────────────────────
_BOILERPLATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)terms\s+and\s+conditions.*?(?=\n{2,}|\Z)", re.DOTALL),
    re.compile(r"(?i)privacy\s+policy.*?(?=\n{2,}|\Z)", re.DOTALL),
    re.compile(r"(?i)disclaimer.*?(?=\n{2,}|\Z)", re.DOTALL),
    # Long lists of student names (heuristic: 20+ comma-separated proper nouns)
    re.compile(r"(?:(?:[A-Z][a-z]+ ){1,3}(?:,\s*)){20,}", re.MULTILINE),
]


def _strip_boilerplate(text: str) -> str:
    """Remove common boilerplate sections to save LLM context window."""
    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ──────────────────────────────────────────────
# PDF extraction
# ──────────────────────────────────────────────


def _extract_pdf_text(pdf_path: str) -> str:
    """
    Extract text from a PDF using PyMuPDF.
    Returns raw text string.
    """
    try:
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except fitz.FileDataError:
        # Password-protected or corrupted PDF
        logger.warning("Encrypted/corrupted PDF: %s", pdf_path)
        raise
    except Exception as exc:
        logger.error("PDF extraction error for %s: %s", pdf_path, exc)
        return ""


def _ocr_pdf_pages(pdf_path: str, max_pages: int = OCR_MAX_PAGES) -> str:
    """
    OCR fallback: convert PDF pages to images and run pytesseract.
    This is a BLOCKING function — must be called via asyncio.to_thread().
    """
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    try:
        doc = fitz.open(pdf_path)
        ocr_texts = []

        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]
            # Render page to a pixmap (image)
            pix = page.get_pixmap(dpi=200)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            text = pytesseract.image_to_string(img, lang="eng")
            ocr_texts.append(text)
            logger.debug("OCR page %d of %s: %d chars", page_num + 1, pdf_path, len(text))

        doc.close()
        return "\n".join(ocr_texts)

    except Exception as exc:
        logger.error("OCR failed for %s: %s", pdf_path, exc)
        return ""


async def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Async-safe PDF text extraction with OCR fallback.

    1. Try PyMuPDF direct text extraction.
    2. If result < 100 chars → assume scanned image → run OCR in thread pool.
    """
    try:
        text = _extract_pdf_text(pdf_path)
    except fitz.FileDataError:
        return ""  # encrypted PDF — handled upstream

    if len(text.strip()) < MIN_TEXT_FOR_OCR_FALLBACK:
        logger.info("PDF text too short (%d chars), falling back to OCR: %s", len(text.strip()), pdf_path)
        text = await asyncio.to_thread(_ocr_pdf_pages, pdf_path)

    return text


# ──────────────────────────────────────────────
# TXT / HTML extraction
# ──────────────────────────────────────────────


def _extract_txt_file(txt_path: str) -> str:
    """Read a plain text / extracted HTML body file."""
    try:
        return Path(txt_path).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.error("Text file read error %s: %s", txt_path, exc)
        return ""


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────


async def extract_text_for_school(
    school_id: str,
    compliance_doc_path: str | None,
    fees_doc_path: str | None,
    state_mgr: StateManager,
) -> str:
    """
    Extract and concatenate text from a school's downloaded documents.
    Returns the full text payload for LLM processing.
    Saves payload to SQLite and to a text file.
    """
    parts: list[str] = []

    for label, doc_path in [("COMPLIANCE", compliance_doc_path), ("FEES", fees_doc_path)]:
        if not doc_path:
            continue

        path = Path(doc_path)
        if not path.exists():
            logger.warning("[%s] Document not found: %s", school_id, doc_path)
            continue

        if path.suffix.lower() == ".pdf":
            try:
                text = await extract_text_from_pdf(doc_path)
            except Exception as exc:
                logger.error("[%s] PDF extraction failed: %s", school_id, exc)
                await state_mgr.update_status(
                    school_id, SchoolProcessingStatus.ENCRYPTED_PDF, str(exc)
                )
                continue
        else:
            text = _extract_txt_file(doc_path)

        if text.strip():
            parts.append(f"=== {label} DOCUMENT ===\n{text}")

    if not parts:
        logger.warning("[%s] No text extracted from any documents.", school_id)
        return ""

    # Concatenate and clean
    full_payload = "\n\n".join(parts)
    full_payload = _strip_boilerplate(full_payload)

    # Persist
    out_path = EXTRACTED_TEXT_DIR / f"{school_id}.txt"
    out_path.write_text(full_payload, encoding="utf-8")
    await state_mgr.save_extracted_text(school_id, full_payload)

    logger.info("[%s] Extracted %d chars of text", school_id, len(full_payload))
    return full_payload


async def extract_all_pending(state_mgr: StateManager) -> int:
    """
    Process all schools at CRAWL_COMPLETE status.
    Returns count of successfully extracted schools.
    """
    pending = await state_mgr.get_pending_for_stage(SchoolProcessingStatus.TEXT_EXTRACTED)
    if not pending:
        logger.info("No schools pending for text extraction.")
        return 0

    logger.info("Starting text extraction for %d schools...", len(pending))
    success_count = 0

    for i, school in enumerate(pending, 1):
        text = await extract_text_for_school(
            school_id=school["school_id"],
            compliance_doc_path=school.get("compliance_doc_path"),
            fees_doc_path=school.get("fees_doc_path"),
            state_mgr=state_mgr,
        )
        if text:
            success_count += 1

        if i % 50 == 0:
            logger.info("Extraction progress: %d / %d", i, len(pending))

    logger.info("Text extraction complete. %d / %d successful.", success_count, len(pending))
    return success_count


if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path
    
    # Add project root directory to PYTHONPATH
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
        
    from src.state import StateManager
    
    async def run_standalone():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)-7s | %(message)s"
        )
        async with StateManager() as state_mgr:
            await extract_all_pending(state_mgr)
            
    asyncio.run(run_standalone())

