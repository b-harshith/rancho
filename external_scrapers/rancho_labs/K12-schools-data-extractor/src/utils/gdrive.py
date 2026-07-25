"""
src/utils/gdrive.py
───────────────────
Google Drive / Google Sheets URL interceptor.

If a school's disclosure or fee doc is hosted on Google Workspace,
we do NOT scrape the DOM. Instead we rewrite the URL to the
/export?format=pdf endpoint and download the PDF directly.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse, urlencode

import aiohttp

from config.settings import RAW_PDF_DIR

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# URL detection
# ──────────────────────────────────────────────
_GOOGLE_DOMAINS = ("docs.google.com", "drive.google.com")


def is_google_workspace_url(url: str) -> bool:
    """Check if a URL is a Google Drive/Docs/Sheets link."""
    try:
        host = urlparse(url).hostname or ""
        return any(host.endswith(d) for d in _GOOGLE_DOMAINS)
    except Exception:
        return False


def build_export_url(url: str, fmt: str = "pdf") -> str:
    """
    Convert a Google Workspace URL to its /export?format=pdf form.

    Handles:
      • Google Docs:   /document/d/{id}/...  → /document/d/{id}/export?format=pdf
      • Google Sheets: /spreadsheets/d/{id}/... → /spreadsheets/d/{id}/export?format=pdf
      • Google Drive (direct file): /file/d/{id}/... → /uc?id={id}&export=download
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    # Google Docs / Sheets
    doc_match = re.search(r"/(document|spreadsheets)/d/([^/]+)", path)
    if doc_match:
        doc_type, doc_id = doc_match.groups()
        return f"https://docs.google.com/{doc_type}/d/{doc_id}/export?format={fmt}"

    # Google Drive file
    file_match = re.search(r"/file/d/([^/]+)", path)
    if file_match:
        file_id = file_match.group(1)
        return f"https://drive.google.com/uc?id={file_id}&export=download"

    # Fallback: append export param
    logger.warning("Could not parse Google URL pattern, appending export param: %s", url)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}format={fmt}"


# ──────────────────────────────────────────────
# Download helper
# ──────────────────────────────────────────────
async def download_google_doc_as_pdf(
    url: str,
    school_id: str,
    doc_type: str,  # "compliance" or "fees"
    session: aiohttp.ClientSession | None = None,
) -> str | None:
    """
    Download a Google Workspace document as PDF.
    Returns the local file path on success, None on failure.
    """
    export_url = build_export_url(url)
    dest = RAW_PDF_DIR / f"{school_id}_{doc_type}.pdf"

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))

    try:
        async with session.get(export_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                logger.warning(
                    "Google export failed (HTTP %d) for %s: %s",
                    resp.status, school_id, export_url,
                )
                return None

            content = await resp.read()
            dest.write_bytes(content)
            logger.info("Downloaded Google doc → %s (%d bytes)", dest, len(content))
            return str(dest)

    except Exception as exc:
        logger.error("Google download error for %s: %s", school_id, exc)
        return None

    finally:
        if own_session:
            await session.close()
