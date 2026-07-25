"""
src/validator.py — Module 5: Data Normalization & Validation
────────────────────────────────────────────────────────────
Cleans LLM output, calculates annual fees using Pandas math,
flags anomalies, and produces ValidatedSchoolRecords.

Key responsibilities:
  • Fee math: raw_fee_amount × period multiplier → Calculated_Annual_Fee
  • Anomaly detection: avg annual fee < ₹1,500 → Fee_Anomaly = True
  • Type casting: all numerical fields → int
  • Compile fee_table JSON array → stringified representation
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import pandas as pd

from config.settings import FEE_PERIOD_MULTIPLIERS, MIN_PLAUSIBLE_ANNUAL_FEE_INR
from src.models import (
    SchoolIntelligenceData,
    SchoolProcessingStatus,
    ValidatedSchoolRecord,
)
from src.state import StateManager

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Fee calculation
# ──────────────────────────────────────────────


def _calculate_annual_fees(llm_data: SchoolIntelligenceData) -> dict:
    """
    Process the fee_table and calculate annual equivalents.

    Returns dict with:
        fee_table_json: str (stringified JSON array with annual fees added)
        calculated_average_annual_fee_inr: float | None
        highest_annual_fee_inr: int | None
        fee_data_found: bool
        fee_anomaly: bool
    """
    result = {
        "fee_table_json": None,
        "calculated_average_annual_fee_inr": None,
        "highest_annual_fee_inr": None,
        "fee_data_found": False,
        "fee_anomaly": False,
    }

    if not llm_data.fee_table:
        return result

    result["fee_data_found"] = True

    # Build a DataFrame from fee tuples
    records = []
    for ft in llm_data.fee_table:
        multiplier = FEE_PERIOD_MULTIPLIERS.get(ft.fee_period.value, 1)
        annual = ft.raw_fee_amount * multiplier
        records.append(
            {
                "grade_band": ft.grade_band,
                "raw_fee_amount": ft.raw_fee_amount,
                "fee_period": ft.fee_period.value,
                "annual_fee": annual,
            }
        )

    df = pd.DataFrame(records)

    # Calculate metrics
    avg_annual = float(df["annual_fee"].mean())
    highest_annual = int(df["annual_fee"].max())

    result["fee_table_json"] = df.to_json(orient="records")
    result["calculated_average_annual_fee_inr"] = round(avg_annual, 2)
    result["highest_annual_fee_inr"] = highest_annual

    # Anomaly check
    if avg_annual < MIN_PLAUSIBLE_ANNUAL_FEE_INR:
        result["fee_anomaly"] = True
        logger.warning(
            "Fee anomaly detected: avg annual fee = ₹%.0f (threshold = ₹%d)",
            avg_annual,
            MIN_PLAUSIBLE_ANNUAL_FEE_INR,
        )

    return result


# ──────────────────────────────────────────────
# Validation pipeline for one school
# ──────────────────────────────────────────────


async def validate_school(
    school_id: str,
    school_row: dict,
    state_mgr: StateManager,
) -> ValidatedSchoolRecord | None:
    """
    Validate and enrich a single school's LLM output.
    """
    llm_json = school_row.get("llm_output_json")
    if not llm_json:
        logger.warning("[%s] No LLM output to validate.", school_id)
        return None

    try:
        llm_data = SchoolIntelligenceData.model_validate_json(llm_json)
    except Exception as exc:
        logger.error("[%s] LLM JSON parse error: %s", school_id, exc)
        await state_mgr.update_status(
            school_id, SchoolProcessingStatus.UNKNOWN_ERROR, f"Validation parse error: {exc}"
        )
        return None

    # ── Fee calculations ──
    fee_result = _calculate_annual_fees(llm_data)

    # ── Build geocode query ──
    geocode_query = (
        f"{school_row.get('name', '')} "
        f"{school_row.get('locality', '')} "
        f"{school_row.get('pincode', '')} "
        f"Bangalore"
    ).strip()

    # ── Assemble validated record ──
    record = ValidatedSchoolRecord(
        school_id=school_id,
        name=school_row.get("name", ""),
        board=school_row.get("board", ""),
        locality=school_row.get("locality", ""),
        pincode=school_row.get("pincode", ""),
        website_url=school_row.get("website_url", ""),

        # LLM fields (cast to int where applicable)
        direct_student_count=_safe_int(llm_data.direct_student_count),
        total_teachers=_safe_int(llm_data.total_teachers),
        total_sections=_safe_int(llm_data.total_sections),
        grades_offered=_safe_int(llm_data.grades_offered),
        student_teacher_ratio=llm_data.student_teacher_ratio,

        # Fee fields
        fee_table_json=fee_result["fee_table_json"],
        calculated_average_annual_fee_inr=fee_result["calculated_average_annual_fee_inr"],
        highest_annual_fee_inr=fee_result["highest_annual_fee_inr"],
        fee_data_found=fee_result["fee_data_found"],
        fee_anomaly=fee_result["fee_anomaly"],

        geocode_query=geocode_query,
        status=SchoolProcessingStatus.VALIDATED,
    )

    # Persist
    await state_mgr.save_validated_record(record)
    logger.info("[%s] Validation complete.", school_id)
    return record


def _safe_int(value: Optional[int | float | str]) -> Optional[int]:
    """Safely cast a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────
# Batch validator
# ──────────────────────────────────────────────


async def validate_all_pending(state_mgr: StateManager) -> int:
    """
    Validate all schools at LLM_PROCESSED status.
    Returns count of successfully validated schools.
    """
    pending = await state_mgr.get_pending_for_stage(SchoolProcessingStatus.VALIDATED)
    if not pending:
        logger.info("No schools pending for validation.")
        return 0

    logger.info("Starting validation for %d schools...", len(pending))
    success_count = 0

    for i, school in enumerate(pending, 1):
        result = await validate_school(
            school_id=school["school_id"],
            school_row=school,
            state_mgr=state_mgr,
        )
        if result is not None:
            success_count += 1

    logger.info("Validation complete. %d / %d successful.", success_count, len(pending))
    return success_count
