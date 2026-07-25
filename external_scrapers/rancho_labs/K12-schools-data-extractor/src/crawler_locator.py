"""
src/crawler_locator.py — Module 2: Dual-Pronged Deep Crawler
────────────────────────────────────────────────────────────
Visits each school website and performs a semantic search (depth ≤ 2) for:
  • Target A — Compliance / Mandatory Disclosure documents
  • Target B — Fee Structure / Tuition documents

Handles: .pdf download, .html body extraction, Google Workspace override.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from config.settings import (
    COMPLIANCE_LINK_PATTERN,
    FEE_LINK_PATTERN,
    GOOGLE_DRIVE_DOMAINS,
    MAX_CRAWL_DEPTH,
    PAGE_TIMEOUT_MS,
    RAW_PDF_DIR,
)
from src.models import CrawlResult, DocumentType, SchoolProcessingStatus
from src.state import StateManager
from src.utils.browser import BrowserPool
from src.utils.gdrive import download_google_doc_as_pdf, is_google_workspace_url

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────


def _classify_url(url: str) -> str:
    """Classify a URL as 'pdf', 'google', or 'html'."""
    if is_google_workspace_url(url):
        return "google"
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    if path.endswith(".pdf") or ".pdf" in path or ".pdf" in query:
        return "pdf"
    return "html"


async def _download_pdf(url: str, dest_path: Path, session: aiohttp.ClientSession) -> bool:
    """Download a PDF from a direct URL. Returns True on success."""
    try:
        async with session.get(url, ssl=False, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                logger.warning("PDF download HTTP %d: %s", resp.status, url)
                return False
            content = await resp.read()
            dest_path.write_bytes(content)
            logger.info("Downloaded PDF → %s (%d bytes)", dest_path, len(content))
            return True
    except Exception as exc:
        logger.error("PDF download error: %s — %s", url, exc)
        return False


async def _extract_body_text(page: Page) -> str:
    """Extract visible text from the current page body."""
    try:
        return await page.inner_text("body")
    except Exception:
        return ""


async def _find_target_link(
    page: Page,
    pattern: str,
    base_url: str,
    depth: int = 0,
    max_depth: int = MAX_CRAWL_DEPTH,
    visited: set[str] | None = None,
) -> Optional[str]:
    """
    Recursively search for a link matching `pattern` on the page.
    Returns the absolute URL of the matching link, or None.
    
    Uses standard checks and context-aware JS execution to match anchors like [ Click Here ] 
    where the surrounding parent container or table row contains the keyword.
    """
    if visited is None:
        visited = set()

    if depth > max_depth:
        return None

    current_url = page.url
    if current_url in visited:
        return None
    visited.add(current_url)

    try:
        # ── 1. Smart In-Browser Context-Aware JS Search ──
        js_find_script = """
        (patternStr) => {
            const regex = new RegExp(patternStr, 'i');
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            
            // Phase 1: Try direct matches on href or text
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                const text = a.innerText || '';
                if (regex.test(href) || regex.test(text)) {
                    return a.href;
                }
            }
            
            // Phase 2: Try parent container context (e.g. table row / list item)
            for (const a of anchors) {
                let parent = a.parentElement;
                let depth = 0;
                while (parent && depth < 3) {
                    const tagName = parent.tagName.toUpperCase();
                    if (tagName === 'TR' || tagName === 'LI' || parent.classList.contains('row') || parent.classList.contains('item')) {
                        const parentText = parent.innerText || '';
                        if (regex.test(parentText)) {
                            return a.href;
                        }
                        break;
                    }
                    parent = parent.parentElement;
                    depth++;
                }
            }
            return null;
        }
        """
        resolved_url = await page.evaluate(js_find_script, pattern)
        if resolved_url:
            logger.debug("Context-aware search found matching link: %s", resolved_url)
            return resolved_url

        # ── 2. Clickable elements check (buttons, divs, spans) ──
        try:
            js_click_script = """
            (patternStr) => {
                const regex = new RegExp(patternStr, 'i');
                const elements = Array.from(document.querySelectorAll('button, div, span, li'));
                for (const el of elements) {
                    const text = (el.innerText || '').trim();
                    if (regex.test(text) && text.length < 100) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
            """
            clicked = await page.evaluate(js_click_script, pattern)
            if clicked:
                logger.debug("Clicked matching non-anchor element in browser")
                await page.wait_for_load_state("networkidle", timeout=5000)
                new_url = page.url
                if new_url != current_url:
                    return new_url
        except Exception as exc:
            logger.debug("Clickable search error: %s", exc)

        # ── Depth search: follow internal links ──
        if depth < max_depth:
            base_domain = urlparse(base_url).netloc
            relevance_keywords = [
                "disclosure", "mandatory", "statutory", "public",
                "fee", "tuition", "admission", "infrastructure",
                "about", "information", "documents", "cbse", "saras"
            ]
            
            # Extract and filter all anchors on the page in a single high-speed JS evaluation
            js_extract_links = """
            (baseDomain, keywords) => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                const results = [];
                const seen = new Set();
                
                for (const a of anchors) {
                    try {
                        const href = a.getAttribute('href') || '';
                        const text = (a.innerText || '').trim();
                        const absUrl = a.href;
                        if (!absUrl.startsWith('http')) continue;
                        
                        const urlObj = new URL(absUrl);
                        if (urlObj.hostname === baseDomain && !seen.has(absUrl)) {
                            seen.add(absUrl);
                            const hrefLower = absUrl.toLowerCase();
                            const textLower = text.toLowerCase();
                            
                            const isRelevant = keywords.some(kw => textLower.includes(kw) || hrefLower.includes(kw));
                            if (isRelevant) {
                                results.push({ url: absUrl, text: text });
                            }
                        }
                    } catch (e) {}
                }
                return results;
            }
            """
            extracted_links = await page.evaluate(js_extract_links, (base_domain, relevance_keywords))
            
            # Capping target internal links traversal to avoid infinite crawling, but checking first 15 relevant links
            for link_info in extracted_links[:15]:
                internal_url = link_info["url"]
                link_text = link_info["text"]
                if internal_url in visited:
                    continue
                
                try:
                    # If this is a PDF or Google doc link, check if it matches pattern directly and skip goto!
                    url_type = _classify_url(internal_url)
                    if url_type in ("pdf", "google"):
                        if re.search(pattern, internal_url, re.IGNORECASE) or re.search(pattern, link_text, re.IGNORECASE):
                            logger.debug("Found matching PDF/Google link in traversal: %s", internal_url)
                            return internal_url
                        continue

                    await page.goto(internal_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                    result = await _find_target_link(
                        page, pattern, page.url, depth + 1, max_depth, visited
                    )
                    if result:
                        return result
                except PlaywrightTimeout:
                    logger.debug("Timeout on depth-%d link: %s", depth + 1, internal_url)
                except Exception as exc:
                    logger.debug("Error on depth-%d link %s: %s", depth + 1, internal_url, exc)

    except Exception as exc:
        logger.debug("Link search error at depth %d: %s", depth, exc)

    return None


async def _search_fallback_doc(
    school_name: str,
    query: str,
    pattern: str,
    page: Page,
    session: aiohttp.ClientSession,
    school_id: str,
    doc_type: DocumentType,
) -> Optional[str]:
    """Perform a targeted Google Search fallback to find a disclosure or fee document."""
    import urllib.parse
    try:
        search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        logger.info("[%s] Executing Google search fallback for: %s", school_id, query)
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        
        # Log search result page title to diagnose bot blocking / consent pages
        title = await page.title()
        logger.info("[%s] Google search result page title: %s", school_id, title)
        
        js_find_google = """
        (patternStr) => {
            const regex = new RegExp(patternStr, 'i');
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            for (const a of anchors) {
                const href = a.getAttribute('href') || '';
                const text = a.innerText || '';
                
                let actualUrl = href;
                if (href.includes('google.com/url?')) {
                    try {
                        const urlParams = new URLSearchParams(href.split('?')[1]);
                        actualUrl = urlParams.get('url') || urlParams.get('q') || href;
                    } catch (e) {}
                }
                
                if (actualUrl.startsWith('http') && !actualUrl.includes('google.com')) {
                    if (regex.test(actualUrl) || regex.test(text) || actualUrl.toLowerCase().endsWith('.pdf')) {
                        return actualUrl;
                    }
                }
            }
            return null;
        }
        """
        found_url = await page.evaluate(js_find_google, pattern)
        if found_url:
            logger.info("[%s] Google search found fallback: %s", school_id, found_url)
            res_path = await _handle_document(found_url, school_id, doc_type, page, session)
            return res_path
    except Exception as exc:
        logger.debug("[%s] Google search fallback failed: %s", school_id, exc)
    return None


def _extract_links_from_pdf(pdf_path: str) -> list[str]:
    """Extract all external URIs from a PDF file using PyMuPDF."""
    import fitz
    uris = []
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            for link in page.get_links():
                uri = link.get("uri")
                if uri:
                    uris.append(uri)
        doc.close()
    except Exception as exc:
        logger.debug("Failed to extract links from PDF %s: %s", pdf_path, exc)
    return uris


async def crawl_school(
    school_id: str,
    website_url: str,
    pool: BrowserPool,
    session: aiohttp.ClientSession,
    state_mgr: StateManager,
    board: str = "CBSE",
) -> CrawlResult:
    """
    Execute the dual-pronged deep crawl for one school.
    Returns a CrawlResult with paths to downloaded documents.
    """
    result = CrawlResult(school_id=school_id)

    # Choose patterns dynamically based on the board
    is_cbse = board.upper() == "CBSE"
    if is_cbse:
        compliance_pattern = COMPLIANCE_LINK_PATTERN
        fee_pattern = FEE_LINK_PATTERN
        logger.info("[%s] Using CBSE strict mandatory compliance crawling patterns", school_id)
    else:
        compliance_pattern = r"(admission|procedure|policy|downloads|prospectus|curriculum|faq|rules|registration|about|disclosures|compliance|statutory)"
        fee_pattern = r"(fee|tuition|cost|charge|structure|pricing|payment)"
        logger.info("[%s] Using non-CBSE (ICSE/IB) broad admissions/fee crawling patterns", school_id)

    # Sanitize and clean raw website URL
    url_to_goto = website_url.strip()
    is_https = url_to_goto.lower().startswith("https")
    while True:
        bad_prefix_match = re.match(r'^([a-z]+)([^a-z0-9]+)', url_to_goto, re.IGNORECASE)
        if bad_prefix_match:
            prefix, separators = bad_prefix_match.groups()
            prefix_lower = prefix.lower()
            if any(prefix_lower.startswith(s) or s.startswith(prefix_lower) or prefix_lower in ('htpp', 'htt', 'tp') for s in ('http', 'https', 'tp')):
                if "https" in prefix_lower:
                    is_https = True
                url_to_goto = url_to_goto[len(prefix) + len(separators):]
                continue
        break
    url_to_goto = url_to_goto.lstrip(':/ ')
    scheme = "https" if is_https else "http"
    url_to_goto = f"{scheme}://{url_to_goto}"

    async with pool.new_page() as page:
        # ── Navigate to school homepage ──
        try:
            await page.goto(url_to_goto, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        except PlaywrightTimeout:
            logger.warning("[%s] Homepage timeout: %s", school_id, url_to_goto)
            await state_mgr.update_status(school_id, SchoolProcessingStatus.TIMEOUT, f"Homepage timeout: {url_to_goto}")
            return result
        except Exception as exc:
            error_msg = str(exc)
            if "net::ERR_" in error_msg or "NS_ERROR" in error_msg:
                logger.warning("[%s] Dead link: %s", school_id, url_to_goto)
                await state_mgr.update_status(school_id, SchoolProcessingStatus.DEAD_LINK, error_msg)
            else:
                logger.warning("[%s] Navigation error: %s (Target URL: %s)", school_id, exc, url_to_goto)
                await state_mgr.update_status(school_id, SchoolProcessingStatus.UNKNOWN_ERROR, error_msg)
            return result

        # ── Check for bot protection ──
        page_text = await _extract_body_text(page)
        if _is_bot_blocked(page, page_text):
            logger.warning("[%s] Bot blocked: %s", school_id, url_to_goto)
            await state_mgr.update_status(school_id, SchoolProcessingStatus.BOT_BLOCKED, "Cloudflare/CAPTCHA detected")
            return result

        # Retrieve actual clean school name from DB for search fallbacks
        db_school = await state_mgr.get_school(school_id)
        school_name = db_school["name"] if db_school else school_id
        if school_name == "DEBUG_SCHOOL":
            try:
                title_text = await page.title()
                if title_text and len(title_text.strip()) > 3:
                    school_name = title_text.split("-")[0].split("|")[0].strip()
                    school_name = re.sub(r'^[^\w]+', '', school_name).strip()
            except Exception:
                pass

        # ── Prong A: Compliance / Mandatory Disclosure ──
        compliance_url = await _find_target_link(page, compliance_pattern, page.url)
        if compliance_url:
            result.compliance_source_url = compliance_url
            result.compliance_doc_path = await _handle_document(
                compliance_url, school_id, DocumentType.COMPLIANCE, page, session
            )

        # ── Prong B: Fee Structure ──
        # Navigate back to homepage first
        try:
            await page.goto(url_to_goto, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        except Exception:
            pass  # best-effort return to homepage

        fees_url = await _find_target_link(page, fee_pattern, page.url)
        if fees_url:
            result.fees_source_url = fees_url
            result.fees_doc_path = await _handle_document(
                fees_url, school_id, DocumentType.FEES, page, session
            )

        # ── Indirection Fallback: Extract links from Compliance PDF ──
        if result.compliance_doc_path and result.compliance_doc_path.lower().endswith(".pdf") and not result.fees_doc_path:
            logger.info("[%s] Checking compliance PDF for embedded fee structure links...", school_id)
            pdf_links = _extract_links_from_pdf(result.compliance_doc_path)
            for pdf_link in pdf_links:
                if re.search(fee_pattern, pdf_link, re.IGNORECASE):
                    logger.info("[%s] Found embedded fee link in compliance PDF: %s", school_id, pdf_link)
                    result.fees_source_url = pdf_link
                    result.fees_doc_path = await _handle_document(
                        pdf_link, school_id, DocumentType.FEES, page, session
                    )
                    if result.fees_doc_path:
                        break

        # ── Deep Fee Resolution Fallback ──
        # If no fee structure was found but we found a compliance/disclosure page, search that page specifically
        if not result.fees_doc_path and compliance_url:
            logger.info("[%s] Fee not found on homepage, scanning compliance disclosure page: %s", school_id, compliance_url)
            try:
                await page.goto(compliance_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                fees_url_fallback = await _find_target_link(page, fee_pattern, compliance_url)
                if fees_url_fallback:
                    result.fees_source_url = fees_url_fallback
                    result.fees_doc_path = await _handle_document(
                        fees_url_fallback, school_id, DocumentType.FEES, page, session
                    )
            except Exception as exc:
                logger.debug("[%s] Deep fee resolution scan failed: %s", school_id, exc)

        # ── Google Search Fallback ──
        # If any document is still missing, attempt Google search fallback to find them
        if not result.compliance_doc_path:
            logger.info("[%s] Compliance missing, running Google search fallback", school_id)
            result.compliance_doc_path = await _search_fallback_doc(
                school_name, f'"{school_name}" mandatory disclosure pdf', compliance_pattern, page, session, school_id, DocumentType.COMPLIANCE
            )
        if not result.fees_doc_path:
            logger.info("[%s] Fee structure missing, running Google search fallback", school_id)
            result.fees_doc_path = await _search_fallback_doc(
                school_name, f'"{school_name}" fee structure pdf', fee_pattern, page, session, school_id, DocumentType.FEES
            )

    # ── Determine final status ──
    if result.compliance_doc_path or result.fees_doc_path:
        await state_mgr.save_crawl_result(
            school_id,
            result.compliance_doc_path,
            result.fees_doc_path,
            result.compliance_source_url,
            result.fees_source_url,
        )
    else:
        await state_mgr.update_status(
            school_id, SchoolProcessingStatus.DOCS_NOT_FOUND,
            "No compliance or fee documents found at depth 2"
        )

    return result


async def _handle_document(
    url: str,
    school_id: str,
    doc_type: DocumentType,
    page: Page,
    session: aiohttp.ClientSession,
) -> str | None:
    """
    Download or extract content from a discovered document URL.
    Returns a local file path on success.
    
    If the discovered URL is an HTML page (like a CBSE Mandatory Disclosure index page),
    it scans that page for direct PDF or Google Workspace links before extracting visible text.
    """
    url_type = _classify_url(url)

    if url_type == "google":
        return await download_google_doc_as_pdf(url, school_id, doc_type.value, session)

    if url_type == "pdf":
        dest = RAW_PDF_DIR / f"{school_id}_{doc_type.value}.pdf"
        ok = await _download_pdf(url, dest, session)
        return str(dest) if ok else None

    # HTML page handling
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        
        # Scan HTML page for ALL direct PDF/Google Doc links
        js_find_all_docs = """
        () => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            const docs = [];
            const seen = new Set();
            for (const a of anchors) {
                try {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim();
                    const absUrl = a.href;
                    if (!absUrl.startsWith('http')) continue;
                    
                    const isDoc = absUrl.toLowerCase().endsWith('.pdf') || 
                                  absUrl.includes('drive.google.com') || 
                                  absUrl.includes('docs.google.com') ||
                                  absUrl.toLowerCase().includes('.pdf?') ||
                                  absUrl.toLowerCase().includes('/pdf/');
                                  
                    if (isDoc && !seen.has(absUrl)) {
                        seen.add(absUrl);
                        docs.push({ url: absUrl, text: text });
                    }
                } catch (e) {}
            }
            return docs;
        }
        """
        docs = await page.evaluate(js_find_all_docs)
        
        if docs:
            logger.info("[%s] HTML index page contains %d sub-documents. Running multi-document deep crawler...", school_id, len(docs))
            combined_parts = []
            
            # 1. Main HTML visible text
            main_text = await _extract_body_text(page)
            if main_text.strip():
                combined_parts.append(f"=== {doc_type.value.upper()} MAIN INDEX ===\n{main_text}")
                
            # 2. Iterate and download sub-documents
            for idx, doc_info in enumerate(docs, 1):
                sub_url = doc_info["url"]
                sub_label = doc_info["text"] or f"Document {idx}"
                logger.info("[%s] Fetching sub-doc %d/%d: %s (%s)", school_id, idx, len(docs), sub_label, sub_url)
                
                sub_type = _classify_url(sub_url)
                sub_dest = RAW_PDF_DIR / f"{school_id}_sub_{idx}.pdf"
                
                sub_path = None
                try:
                    if sub_type == "google":
                        sub_path = await download_google_doc_as_pdf(sub_url, school_id, f"sub_{idx}", session)
                    else:
                        ok = await _download_pdf(sub_url, sub_dest, session)
                        if ok:
                            sub_path = str(sub_dest)
                            
                    if sub_path and Path(sub_path).exists():
                        from src.parser_text import extract_text_from_pdf
                        sub_text = await extract_text_from_pdf(sub_path)
                        if sub_text.strip():
                            combined_parts.append(f"\n--- SUB-DOCUMENT: {sub_label} ({sub_url}) ---\n{sub_text}")
                except Exception as exc:
                    logger.debug("[%s] Failed to extract sub-document %s: %s", school_id, sub_url, exc)
                finally:
                    if sub_path and Path(sub_path).exists():
                        try:
                            Path(sub_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                            
            if len(combined_parts) > 1:
                # Successfully merged sub-documents! Save as txt
                dest = RAW_PDF_DIR / f"{school_id}_{doc_type.value}.txt"
                dest.write_text("\n\n".join(combined_parts), encoding="utf-8")
                logger.info("[%s] Saved combined index + %d sub-docs to %s", school_id, len(combined_parts) - 1, dest)
                return str(dest)

        # Fallback to saving raw HTML visible text
        text = await _extract_body_text(page)
        if text.strip():
            dest = RAW_PDF_DIR / f"{school_id}_{doc_type.value}.txt"
            dest.write_text(text, encoding="utf-8")
            return str(dest)
    except Exception as exc:
        logger.warning("[%s] HTML extraction failed for %s: %s", school_id, url, exc)

    return None


def _is_bot_blocked(page: Page, body_text: str) -> bool:
    """Heuristic check for CAPTCHA / Cloudflare challenge pages."""
    lower = body_text.lower()
    indicators = [
        "checking your browser",
        "just a moment",
        "cloudflare",
        "captcha",
        "access denied",
        "403 forbidden",
    ]
    return any(ind in lower for ind in indicators)


# ──────────────────────────────────────────────────────────────
# Batch orchestrator
# ──────────────────────────────────────────────────────────────


async def crawl_all_schools(
    pool: BrowserPool,
    state_mgr: StateManager,
    flush_interval: int = 50,
) -> list[CrawlResult]:
    """
    Crawl all schools at SEED_SCRAPED status.
    Runs up to MAX_BROWSER_CONCURRENCY concurrent crawls.
    Flushes browser memory every `flush_interval` schools.
    """
    from config.settings import MAX_BROWSER_CONCURRENCY

    pending = await state_mgr.get_pending_for_stage(SchoolProcessingStatus.CRAWL_COMPLETE)
    if not pending:
        logger.info("No schools pending for crawling.")
        return []

    logger.info("Starting crawl for %d schools concurrently (max_concurrency=%d)...", len(pending), MAX_BROWSER_CONCURRENCY)
    
    sem = asyncio.Semaphore(MAX_BROWSER_CONCURRENCY)
    processed_count = 0
    count_lock = asyncio.Lock()

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        
        async def worker(school):
            nonlocal processed_count
            async with sem:
                res = await crawl_school(
                    school_id=school["school_id"],
                    website_url=school["website_url"],
                    pool=pool,
                    session=session,
                    state_mgr=state_mgr,
                    board=school.get("board", "CBSE"),
                )
                async with count_lock:
                    processed_count += 1
                    if processed_count % 25 == 0:
                        logger.info("Crawl progress: %d / %d", processed_count, len(pending))
                return res

        tasks = [worker(school) for school in pending]
        results = list(await asyncio.gather(*tasks))
        
        # Safe memory flush after all parallel tasks have completed
        logger.info("Batch crawl completed. Restarting browser pool to flush memory.")
        await pool.restart()

    logger.info("Crawl complete. %d schools processed.", len(results))
    return results
