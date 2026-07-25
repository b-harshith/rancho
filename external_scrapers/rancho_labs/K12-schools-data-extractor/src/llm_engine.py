"""
src/llm_engine.py — Module 4: LLM Data Structuring Engine
─────────────────────────────────────────────────────────
Sends extracted text payloads to OpenAI (gpt-4o-mini) and enforces
structured JSON output via instructor + Pydantic.

Key rules:
  • Extract raw facts only — do NOT infer or calculate downstream metrics.
  • Translate regional languages (Kannada, Hindi, etc.) to English.
  • Enforce the exact SchoolIntelligenceData schema.
  • Retry on rate limits with exponential backoff (tenacity).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import instructor
import openai

from config.settings import OPENAI_API_KEY, OPENAI_MODEL, GEMINI_API_KEY, GEMINI_MODEL
from src.models import SchoolIntelligenceData, SchoolProcessingStatus
from src.state import StateManager
from src.utils.retry import llm_retry

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a data extraction assistant for Indian K-12 schools.

TASK: Extract ONLY explicitly stated facts from the provided school document text.
OUTPUT: A structured JSON matching the provided schema exactly.

RULES:
1. Extract RAW FACTS only. Do NOT calculate, infer, or derive any values.
2. If a data point is not explicitly stated in the text, return null for that field.
3. If the text is in a regional Indian language (Hindi, Kannada, Tamil, Telugu, etc.),
   translate the relevant data to English before structuring.
4. For fee_table: extract every distinct grade band and its associated fee.
   - grade_band: Use the exact label from the document (e.g., "LKG-UKG", "Grade 1-5").
   - raw_fee_amount: The numerical fee amount as stated. Remove commas, keep as integer.
   - fee_period: Determine the billing cycle (Monthly, Quarterly, Semi-Annual, Annual).
     If ambiguous, use "Unknown".
5. For student_teacher_ratio: Copy the exact ratio string (e.g., "1:20") if stated.
6. Do NOT fabricate data. Accuracy is paramount.
"""


# ──────────────────────────────────────────────
# LLM client setup
# ──────────────────────────────────────────────


def _get_client() -> instructor.Instructor:
    """Build an instructor-patched LLM client (supporting Gemini or OpenAI)."""
    if GEMINI_API_KEY:
        raw_client = openai.OpenAI(
            api_key=GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        return instructor.from_openai(raw_client, mode=instructor.Mode.MD_JSON)
    else:
        raw_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        return instructor.from_openai(raw_client)


# ──────────────────────────────────────────────
# Core extraction function
# ──────────────────────────────────────────────


@llm_retry(max_attempts=5, min_wait=2, max_wait=60)
def _call_llm(client: instructor.Instructor, text_payload: str) -> SchoolIntelligenceData:
    """
    Synchronous LLM call (instructor currently wraps sync openai).
    Decorated with tenacity retry for rate limits.
    """
    result = client.chat.completions.create(
        model=GEMINI_MODEL if GEMINI_API_KEY else OPENAI_MODEL,
        response_model=SchoolIntelligenceData,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract structured school data from the following document text. "
                    "Return ONLY facts explicitly stated in the text.\n\n"
                    f"--- DOCUMENT TEXT ---\n{text_payload}\n--- END ---"
                ),
            },
        ],
        max_retries=2,  # instructor-level retries for validation failures
    )
    return result


async def process_school_text(
    school_id: str,
    text_payload: str,
    state_mgr: StateManager,
) -> SchoolIntelligenceData | None:
    """
    Process a single school's text payload through the LLM.
    Persists the structured output to SQLite.
    """
    if not text_payload or not text_payload.strip():
        logger.warning("[%s] Empty text payload, skipping LLM.", school_id)
        return None

    if not OPENAI_API_KEY and not GEMINI_API_KEY:
        logger.error("Neither OPENAI_API_KEY nor GEMINI_API_KEY is set. Cannot call LLM.")
        await state_mgr.update_status(
            school_id, SchoolProcessingStatus.LLM_ERROR, "No API key configured"
        )
        return None

    client = _get_client()

    try:
        # Truncate payload if excessively long (gpt-4o-mini context window)
        # Keep ~12k chars to stay well within limits with system prompt
        truncated = text_payload[:12000] if len(text_payload) > 12000 else text_payload

        # Execute blocking LLM HTTP request in a thread pool for concurrency
        result = await asyncio.to_thread(_call_llm, client, truncated)
        llm_json = result.model_dump_json()
        await state_mgr.save_llm_output(school_id, llm_json)
        logger.info("[%s] LLM extraction complete.", school_id)
        return result

    except openai.RateLimitError as exc:
        logger.error("[%s] OpenAI rate limit exhausted after retries: %s", school_id, exc)
        await state_mgr.update_status(
            school_id, SchoolProcessingStatus.LLM_ERROR, f"Rate limited: {exc}"
        )
    except openai.APIError as exc:
        logger.error("[%s] OpenAI API error: %s", school_id, exc)
        await state_mgr.update_status(
            school_id, SchoolProcessingStatus.LLM_ERROR, f"API error: {exc}"
        )
    except Exception as exc:
        logger.error("[%s] LLM processing failed: %s", school_id, exc)
        await state_mgr.update_status(
            school_id, SchoolProcessingStatus.LLM_ERROR, str(exc)
        )

    return None


async def process_all_pending(state_mgr: StateManager) -> int:
    """
    Process all schools at TEXT_EXTRACTED status through the LLM.
    Returns count of successfully processed schools.
    """
    pending = await state_mgr.get_pending_for_stage(SchoolProcessingStatus.LLM_PROCESSED)
    if not pending:
        logger.info("No schools pending for LLM processing.")
        return 0

    # Upgraded quota allows highly concurrent processing (sending 10 requests at once)
    sem = asyncio.Semaphore(10)
    delay = 0.0

    logger.info("Starting concurrent LLM processing for %d schools...", len(pending))
    
    success_count = 0
    processed_count = 0
    count_lock = asyncio.Lock()

    async def worker(school):
        nonlocal success_count, processed_count
        text_payload = school.get("extracted_text_payload", "")
        async with sem:
            result = await process_school_text(
                school_id=school["school_id"],
                text_payload=text_payload,
                state_mgr=state_mgr,
            )
            async with count_lock:
                processed_count += 1
                if result is not None:
                    success_count += 1
                if processed_count % 10 == 0 or processed_count == len(pending):
                    logger.info("LLM progress: %d / %d completed", processed_count, len(pending))
            
            # Apply rate limiting delay between consecutive tasks if configured
            if delay > 0 and processed_count < len(pending):
                await asyncio.sleep(delay)

    tasks = [worker(school) for school in pending]
    await asyncio.gather(*tasks)

    logger.info("LLM processing complete. %d / %d successful.", success_count, len(pending))
    return success_count
