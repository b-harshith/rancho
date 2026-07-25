"""
config/settings.py
──────────────────
Single source of truth for every tuneable constant in the pipeline.
All modules import from here — never hard-code magic numbers elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Paths (all relative to project root)
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
RAW_PDF_DIR = DATA_DIR / "raw_pdfs"
EXTRACTED_TEXT_DIR = DATA_DIR / "extracted_text"
OUTPUT_DIR = DATA_DIR / "output"
LOGS_DIR = PROJECT_ROOT / "logs"

SEED_CACHE_FILE = CACHE_DIR / "local_seed_cache.csv"
SQLITE_DB_PATH = PROJECT_ROOT / "pipeline.db"

# Ensure directories exist at import time
for _d in (CACHE_DIR, RAW_PDF_DIR, EXTRACTED_TEXT_DIR, OUTPUT_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# OpenAI / LLM / Gemini
# ──────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ──────────────────────────────────────────────
# Browser / Playwright
# ──────────────────────────────────────────────
MAX_BROWSER_CONCURRENCY: int = int(os.getenv("MAX_BROWSER_CONCURRENCY", "4"))
BROWSER_FLUSH_INTERVAL: int = int(os.getenv("BROWSER_FLUSH_INTERVAL", "50"))
PAGE_TIMEOUT_MS: int = int(os.getenv("PAGE_TIMEOUT_SECONDS", "30")) * 1000  # Playwright uses ms

CHROMIUM_ARGS: list[str] = [
    "--disable-gpu",
    "--no-sandbox",
    "--blink-settings=imagesEnabled=false",
]

# ──────────────────────────────────────────────
# OCR / Tesseract
# ──────────────────────────────────────────────
TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "/opt/homebrew/bin/tesseract")

# ──────────────────────────────────────────────
# Crawler
# ──────────────────────────────────────────────
MAX_CRAWL_DEPTH: int = 2

# Regex patterns for dual-pronged link discovery
COMPLIANCE_LINK_PATTERN: str = r"(mandatory.*disclosure|public.*disclosure|statutory.*declaration|cbse.*info|cbse.*disclosure|disclosures|compliance|saras(?!wati)|s\.a\.r\.a\.s|cbse.*saras|cbse.*mandatories)"
FEE_LINK_PATTERN: str = r"(fee.*structure|tuition|fee.*details|fees|fee.*chart|fee.*schedule|school.*fee)"

# Google Workspace domain prefixes (used for export-as-PDF override)
GOOGLE_DRIVE_DOMAINS: tuple[str, ...] = ("docs.google.com", "drive.google.com")

# ──────────────────────────────────────────────
# Validation thresholds
# ──────────────────────────────────────────────
MIN_PLAUSIBLE_ANNUAL_FEE_INR: int = 1500  # below this → Fee_Anomaly = True
MIN_TEXT_FOR_OCR_FALLBACK: int = 100       # chars — below this, trigger pytesseract
OCR_MAX_PAGES: int = 3                     # how many pages to OCR on scanned PDFs

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ──────────────────────────────────────────────
# Fee period → annual multiplier mapping
# ──────────────────────────────────────────────
FEE_PERIOD_MULTIPLIERS: dict[str, int] = {
    "Monthly": 12,
    "Quarterly": 4,
    "Semi-Annual": 2,
    "Annual": 1,
    "Unknown": 1,  # conservative fallback
}
