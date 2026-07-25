"""
src/enricher_udise.py — Module 2 (Alternative): UDISE+ Know Your School Enricher
─────────────────────────────────────────────────────────────────────────────
Queries the official UDISE+ portal to harvest student strength, teacher counts, and pupil-teacher ratios.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from src.models import SchoolIntelligenceData, GradeFeeTuple, FeePeriod, SchoolProcessingStatus
from src.state import StateManager
from src.utils.browser import BrowserPool

logger = logging.getLogger(__name__)


def parse_udise_metrics(page_text: str) -> dict:
    """
    Scans UDISE+ school profile text using smart regex to extract key metrics.
    """
    metrics = {
        "student_count": None,
        "teacher_count": None,
        "student_teacher_ratio": None,
        "grades_offered": None,
    }
    
    if not page_text:
        return metrics
        
    low_text = page_text.lower()
    
    # 1. Extract Student Count / Enrollment
    student_patterns = [
        r"total\s+enrol[l]?ment\s*[:\-\s]+(\d+)",
        r"enrol[l]?ment\s*\(total\)\s*[:\-\s]+(\d+)",
        r"total\s+students\s*[:\-\s]+(\d+)",
        r"boys\s*:\s*\d+\s*,\s*girls\s*:\s*\d+\s*,\s*total\s*[:\-\s]+(\d+)",
        r"enrolment\s+details.*?\b(\d{2,5})\b",
    ]
    for pattern in student_patterns:
        m = re.search(pattern, low_text, re.DOTALL)
        if m:
            val = int(m.group(1))
            if 10 < val < 50000:
                metrics["student_count"] = val
                break
                
    # 2. Extract Teacher Count
    teacher_patterns = [
        r"total\s+teachers\s*[:\-\s]+(\d+)",
        r"total\s+teaching\s+staff\s*[:\-\s]+(\d+)",
        r"regular\s+teachers\s*[:\-\s]+(\d+)",
        r"teachers\s*\(total\)\s*[:\-\s]+(\d+)",
    ]
    for pattern in teacher_patterns:
        m = re.search(pattern, low_text)
        if m:
            val = int(m.group(1))
            if 2 <= val < 1000:
                metrics["teacher_count"] = val
                break
                
    # 3. Extract Student-Teacher Ratio (PTR)
    ptr_patterns = [
        r"pupil\s+teacher\s+ratio\s*\(ptr\)\s*[:\-\s]+(\d+(?:\.\d+)?|1\s*:\s*\d+)",
        r"student\s+teacher\s+ratio\s*[:\-\s]+(\d+(?:\.\d+)?|1\s*:\s*\d+)",
        r"ptr\s*[:\-\s]+(\d+(?:\.\d+)?|1\s*:\s*\d+)",
    ]
    for pattern in ptr_patterns:
        m = re.search(pattern, low_text)
        if m:
            metrics["student_teacher_ratio"] = m.group(1).strip()
            break
            
    # Compute ratio if metrics exist but ratio does not
    if not metrics["student_teacher_ratio"] and metrics["student_count"] and metrics["teacher_count"]:
        ratio = round(metrics["student_count"] / metrics["teacher_count"], 1)
        metrics["student_teacher_ratio"] = f"1:{int(ratio)}" if ratio >= 1 else "1:1"
        
    # 4. Extract Grades Offered
    class_match = re.search(r"lowest\s+class\s*[:\-\s]+(\d+).*?highest\s+class\s*[:\-\s]+(\d+)", low_text, re.DOTALL)
    if class_match:
        try:
            low = int(class_match.group(1))
            high = int(class_match.group(2))
            metrics["grades_offered"] = max(1, high - low + 1)
        except Exception:
            pass
            
    return metrics


async def enrich_school_with_udise(
    school_id: str,
    school_name: str,
    locality: str,
    pincode: str,
    page: Page,
) -> dict:
    """
    Performs UDISE+ KYS search for a single school and extracts metrics.
    """
    logger.info("[%s] Searching UDISE+ for: %s (%s)", school_id, school_name, locality)
    url = "https://src.udiseplus.gov.in/"  # KYS public interface
    
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1000)
        
        # Look for search input and enter school name
        search_inputs = [
            "input#search",
            "input[type='text'][placeholder*='school']",
            "input[placeholder*='Search']",
            "input[name='schoolName']"
        ]
        
        input_el = None
        for selector in search_inputs:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                input_el = el
                break
                
        if not input_el:
            # Fallback: Check if there's an iframe or click a search tab
            logger.debug("[%s] Search input not found directly. Scanning page elements...", school_id)
            input_el = await page.query_selector("input")
            
        if input_el:
            search_query = f"{school_name}"
            await input_el.fill(search_query)
            await page.wait_for_timeout(500)
            
            # Select State (Karnataka) if dropdown exists
            try:
                state_select = await page.query_selector("select#state, select[name*='state']")
                if state_select:
                    await state_select.select_option(label="KARNATAKA")
                    await page.wait_for_timeout(1000)
            except Exception:
                pass
                
            # Press search / Enter
            await input_el.press("Enter")
            await page.wait_for_timeout(4000)
            
            # Wait for search results
            result_links = await page.query_selector_all("a[href*='schoolReportCard'], td a, .school-link")
            if not result_links:
                # Target name fallback without specific location
                await input_el.fill(school_name.split("school")[0].strip())
                await input_el.press("Enter")
                await page.wait_for_timeout(3000)
                result_links = await page.query_selector_all("a[href*='schoolReportCard'], td a")
                
            if result_links:
                # Match best school link by locality
                target_link = result_links[0]
                for link in result_links:
                    link_text = (await link.inner_text()).lower()
                    if locality.lower() in link_text or pincode in link_text:
                        target_link = link
                        break
                        
                logger.info("[%s] Found UDISE+ school profile link. Navigating...", school_id)
                await target_link.click()
                await page.wait_for_timeout(4000)
                
                # Check for profile view loading
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                profile_text = await page.inner_text("body")
                return parse_udise_metrics(profile_text)
                
        logger.warning("[%s] No matching school found on UDISE+", school_id)
        
    except Exception as e:
        logger.warning("[%s] UDISE+ enrichment lookup failed: %s", school_id, e)
        
    return parse_udise_metrics("")


async def enrich_all_pending_schools(
    pool: BrowserPool,
    state_mgr: StateManager,
    max_concurrency: int = 5,
) -> int:
    """
    Enriches all SEED_SCRAPED schools using UDISE+ metrics.
    """
    pending = await state_mgr.get_schools_by_status(SchoolProcessingStatus.SEED_SCRAPED)
    if not pending:
        logger.info("No schools pending for UDISE+ enrichment.")
        return 0
        
    logger.info("Enriching %d schools with UDISE+ metrics...", len(pending))
    sem = asyncio.Semaphore(max_concurrency)
    success_count = 0
    
    async def worker(school):
        nonlocal success_count
        async with sem:
            async with pool.new_page() as page:
                metrics = await enrich_school_with_udise(
                    school_id=school["school_id"],
                    school_name=school["name"],
                    locality=school["locality"],
                    pincode=school["pincode"],
                    page=page
                )
                
                # Save as LLM structured object to merge with UniApply fees
                # Load existing scraped listing fees from DB row
                db_row = await state_mgr.get_school(school["school_id"])
                avg_fee = db_row.get("calculated_average_annual_fee_inr") or 0.0
                highest_fee = db_row.get("highest_annual_fee_inr") or 0
                
                fee_tuples = []
                if avg_fee > 0:
                    fee_tuples.append(GradeFeeTuple(
                        grade_band="Average (UniApply)",
                        raw_fee_amount=int(avg_fee),
                        fee_period=FeePeriod.ANNUAL
                    ))
                    
                intel = SchoolIntelligenceData(
                    direct_student_count=metrics["student_count"],
                    total_teachers=metrics["teacher_count"],
                    student_teacher_ratio=metrics["student_teacher_ratio"],
                    grades_offered=metrics["grades_offered"],
                    fee_table=fee_tuples
                )
                
                # Upsert JSON representation to DB row (transitions status to LLM_PROCESSED)
                await state_mgr.save_llm_output(school["school_id"], intel.model_dump_json())
                success_count += 1

    tasks = [worker(school) for school in pending]
    await asyncio.gather(*tasks)
    
    logger.info("UDISE+ enrichment batch complete. Enriched %d schools.", success_count)
    return success_count
