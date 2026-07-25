"""
src/exporter.py — Module 6: Exporter & Geocode Prepper
─────────────────────────────────────────────────────
Compiles all VALIDATED records from SQLite into a master Pandas DataFrame
and exports to Excel (.xlsx) and JSON formats.

Output columns include:
  • All seed + LLM + computed fields
  • Geocode_Query: "{School_Name} {Locality} {Pincode} Bangalore"
  • Calculated_Average_Annual_Fee_INR
  • Highest_Annual_Fee_INR
  • Fee_Data_Found (bool)
  • Fee_Anomaly (bool)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from config.settings import OUTPUT_DIR
from src.models import SchoolProcessingStatus
from src.state import StateManager

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Column ordering for final export
# ──────────────────────────────────────────────
_EXPORT_COLUMNS = [
    "school_id",
    "name",
    "board",
    "locality",
    "pincode",
    "website_url",
    "direct_student_count",
    "total_teachers",
    "total_sections",
    "grades_offered",
    "student_teacher_ratio",
    "fee_table_json",
    "calculated_average_annual_fee_inr",
    "highest_annual_fee_inr",
    "fee_data_found",
    "fee_anomaly",
    "geocode_query",
    "status",
    "error_detail",
    "compliance_source_url",
    "fees_source_url",
]


async def export_master_database(
    state_mgr: StateManager,
    output_dir: Path | None = None,
    include_failed: bool = False,
) -> tuple[Path, Path]:
    """
    Export the master database to Excel and JSON.

    Args:
        state_mgr:      Active StateManager instance.
        output_dir:     Override output directory (default: ./data/output/).
        include_failed: If True, include schools with failure statuses in export.

    Returns:
        Tuple of (xlsx_path, json_path).
    """
    dest = output_dir or OUTPUT_DIR
    dest.mkdir(parents=True, exist_ok=True)

    # ── Fetch records ──
    validated = await state_mgr.get_all_exportable()

    if include_failed:
        # Also include schools that failed at various stages (for review)
        for status in [
            SchoolProcessingStatus.DEAD_LINK,
            SchoolProcessingStatus.BOT_BLOCKED,
            SchoolProcessingStatus.DOCS_NOT_FOUND,
            SchoolProcessingStatus.ENCRYPTED_PDF,
            SchoolProcessingStatus.TIMEOUT,
            SchoolProcessingStatus.LLM_ERROR,
            SchoolProcessingStatus.UNKNOWN_ERROR,
        ]:
            failed = await state_mgr.get_schools_by_status(status)
            validated.extend(failed)

    if not validated:
        logger.warning("No records to export.")
        empty_xlsx = dest / "stage1_master_database.xlsx"
        empty_json = dest / "stage1_master_database.json"
        pd.DataFrame(columns=_EXPORT_COLUMNS).to_excel(str(empty_xlsx), index=False)
        pd.DataFrame(columns=_EXPORT_COLUMNS).to_json(str(empty_json), orient="records", indent=2)
        return empty_xlsx, empty_json

    # ── Build DataFrame ──
    df = pd.DataFrame(validated)

    # Ensure all expected columns exist
    for col in _EXPORT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # ── Type cleanup ──
    bool_cols = ["fee_data_found", "fee_anomaly"]
    for col in bool_cols:
        df[col] = df[col].fillna(0).astype(bool)

    int_cols = ["direct_student_count", "total_teachers", "total_sections", "grades_offered", "highest_annual_fee_inr"]
    for col in int_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")  # nullable int

    # ── Keep only designated export columns ──
    df = df[_EXPORT_COLUMNS]

    # Clean any illegal XML control characters from string columns to prevent openpyxl errors
    def _clean_xml_chars(val):
        if not isinstance(val, str):
            return val
        return "".join(c for c in val if ord(c) >= 32 or c in "\t\n\r")

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(_clean_xml_chars)

    # ── Sort ──
    df = df.sort_values(["board", "name"]).reset_index(drop=True)

    # ── Export ──
    xlsx_path = dest / "stage1_master_database.xlsx"
    json_path = dest / "stage1_master_database.json"

    df.to_excel(str(xlsx_path), index=False, engine="openpyxl")
    logger.info("Exported Excel: %s (%d rows)", xlsx_path, len(df))

    # JSON export — convert DataFrame to records
    df_json = df.copy()
    # Convert Int64 to regular int for JSON serialization
    for col in int_cols:
        df_json[col] = df_json[col].where(df_json[col].notna(), None)
    records = df_json.to_dict(orient="records")
    json_path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    logger.info("Exported JSON: %s (%d records)", json_path, len(records))

    # ── Summary stats ──
    _log_export_summary(df)

    # Mark all as exported
    for _, row in df.iterrows():
        if row.get("status") == SchoolProcessingStatus.VALIDATED.value:
            await state_mgr.update_status(
                row["school_id"], SchoolProcessingStatus.EXPORTED
            )

    return xlsx_path, json_path


def _log_export_summary(df: pd.DataFrame) -> None:
    """Print a summary of the exported dataset."""
    total = len(df)
    with_fees = df["fee_data_found"].sum()
    anomalies = df["fee_anomaly"].sum()
    boards = df["board"].value_counts().to_dict()

    logger.info("=" * 50)
    logger.info("EXPORT SUMMARY")
    logger.info("=" * 50)
    logger.info("Total schools:      %d", total)
    logger.info("With fee data:      %d (%.0f%%)", with_fees, 100 * with_fees / max(total, 1))
    logger.info("Fee anomalies:      %d", anomalies)
    logger.info("Board breakdown:    %s", boards)
    logger.info("=" * 50)
