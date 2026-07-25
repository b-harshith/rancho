"""
src/state.py
────────────
Async SQLite state manager — the single source of pipeline progress truth.
Provides idempotent resume: if the script crashes at school N, restart picks up at N+1.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from config.settings import SQLITE_DB_PATH
from src.models import SchoolProcessingStatus, SeedSchool, ValidatedSchoolRecord

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Schema DDL
# ──────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schools (
    school_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    board           TEXT NOT NULL,
    locality        TEXT DEFAULT '',
    pincode         TEXT DEFAULT '',
    website_url     TEXT DEFAULT '',

    -- Pipeline status
    status          TEXT DEFAULT 'PENDING',
    error_detail    TEXT,

    -- Crawler outputs (file paths)
    compliance_doc_path  TEXT,
    fees_doc_path        TEXT,
    compliance_source_url TEXT,
    fees_source_url      TEXT,

    -- Extracted raw text payload (stored for debugging / re-runs)
    extracted_text_payload TEXT,

    -- LLM structured output (JSON blob)
    llm_output_json  TEXT,

    -- Validated / computed fields
    direct_student_count  INTEGER,
    total_teachers        INTEGER,
    total_sections        INTEGER,
    grades_offered        INTEGER,
    student_teacher_ratio TEXT,
    fee_table_json        TEXT,
    calculated_average_annual_fee_inr REAL,
    highest_annual_fee_inr INTEGER,
    fee_data_found        INTEGER DEFAULT 0,
    fee_anomaly           INTEGER DEFAULT 0,
    geocode_query         TEXT DEFAULT '',

    -- Timestamps
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_schools_status ON schools(status);
CREATE INDEX IF NOT EXISTS idx_schools_board  ON schools(board);
"""


class StateManager:
    """
    Thin async wrapper around aiosqlite for pipeline state tracking.

    Usage:
        async with StateManager() as sm:
            await sm.upsert_seed(seed_school)
            ...
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(SQLITE_DB_PATH)
        self._conn: Optional[aiosqlite.Connection] = None

    # ── Context manager ──────────────────────
    async def __aenter__(self) -> "StateManager":
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA_SQL)
        await self._conn.commit()
        logger.info("StateManager connected to %s", self._db_path)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ── Seed upsert (idempotent) ─────────────
    async def upsert_seed(self, school: SeedSchool) -> None:
        """Insert or ignore a seed school record."""
        assert self._conn is not None
        await self._conn.execute(
            """
            INSERT INTO schools (school_id, name, board, locality, pincode, website_url, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(school_id) DO UPDATE SET
                name       = excluded.name,
                board      = excluded.board,
                locality   = excluded.locality,
                pincode    = excluded.pincode,
                website_url = excluded.website_url,
                updated_at = datetime('now')
            """,
            (
                school.school_id,
                school.name,
                school.board.value,
                school.locality,
                school.pincode,
                school.website_url,
                SchoolProcessingStatus.PENDING.value,
            ),
        )
        await self._conn.commit()

    async def bulk_upsert_seeds(self, schools: list[SeedSchool]) -> int:
        """Batch upsert seed records. Returns count inserted/updated."""
        assert self._conn is not None
        rows = [
            (s.school_id, s.name, s.board.value, s.locality, s.pincode, s.website_url, SchoolProcessingStatus.SEED_SCRAPED.value)
            for s in schools
        ]
        await self._conn.executemany(
            """
            INSERT INTO schools (school_id, name, board, locality, pincode, website_url, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(school_id) DO UPDATE SET
                name       = excluded.name,
                board      = excluded.board,
                locality   = excluded.locality,
                pincode    = excluded.pincode,
                website_url = excluded.website_url,
                status     = CASE WHEN schools.status = 'PENDING' THEN excluded.status ELSE schools.status END,
                updated_at = datetime('now')
            """,
            rows,
        )
        await self._conn.commit()
        return len(rows)

    # ── Status updates ───────────────────────
    async def update_status(
        self,
        school_id: str,
        status: SchoolProcessingStatus,
        error_detail: str | None = None,
    ) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """
            UPDATE schools SET status = ?, error_detail = ?, updated_at = datetime('now')
            WHERE school_id = ?
            """,
            (status.value, error_detail, school_id),
        )
        await self._conn.commit()

    # ── Crawler result persistence ───────────
    async def save_crawl_result(
        self,
        school_id: str,
        compliance_doc_path: str | None,
        fees_doc_path: str | None,
        compliance_source_url: str | None,
        fees_source_url: str | None,
    ) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """
            UPDATE schools SET
                compliance_doc_path   = ?,
                fees_doc_path         = ?,
                compliance_source_url = ?,
                fees_source_url       = ?,
                status                = ?,
                updated_at            = datetime('now')
            WHERE school_id = ?
            """,
            (
                compliance_doc_path,
                fees_doc_path,
                compliance_source_url,
                fees_source_url,
                SchoolProcessingStatus.CRAWL_COMPLETE.value,
                school_id,
            ),
        )
        await self._conn.commit()

    # ── Text extraction persistence ──────────
    async def save_extracted_text(self, school_id: str, text_payload: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """
            UPDATE schools SET
                extracted_text_payload = ?,
                status                = ?,
                updated_at            = datetime('now')
            WHERE school_id = ?
            """,
            (text_payload, SchoolProcessingStatus.TEXT_EXTRACTED.value, school_id),
        )
        await self._conn.commit()

    # ── LLM output persistence ───────────────
    async def save_llm_output(self, school_id: str, llm_json: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """
            UPDATE schools SET
                llm_output_json = ?,
                status          = ?,
                updated_at      = datetime('now')
            WHERE school_id = ?
            """,
            (llm_json, SchoolProcessingStatus.LLM_PROCESSED.value, school_id),
        )
        await self._conn.commit()

    # ── Validated record persistence ─────────
    async def save_validated_record(self, record: ValidatedSchoolRecord) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """
            UPDATE schools SET
                direct_student_count              = ?,
                total_teachers                    = ?,
                total_sections                    = ?,
                grades_offered                    = ?,
                student_teacher_ratio             = ?,
                fee_table_json                    = ?,
                calculated_average_annual_fee_inr = ?,
                highest_annual_fee_inr            = ?,
                fee_data_found                    = ?,
                fee_anomaly                       = ?,
                geocode_query                     = ?,
                status                            = ?,
                error_detail                      = ?,
                updated_at                        = datetime('now')
            WHERE school_id = ?
            """,
            (
                record.direct_student_count,
                record.total_teachers,
                record.total_sections,
                record.grades_offered,
                record.student_teacher_ratio,
                record.fee_table_json,
                record.calculated_average_annual_fee_inr,
                record.highest_annual_fee_inr,
                int(record.fee_data_found),
                int(record.fee_anomaly),
                record.geocode_query,
                record.status.value,
                record.error_detail,
                record.school_id,
            ),
        )
        await self._conn.commit()

    # ── Queries ──────────────────────────────
    async def get_schools_by_status(self, status: SchoolProcessingStatus) -> list[dict]:
        """Return all schools at a given pipeline stage."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT * FROM schools WHERE status = ?", (status.value,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_pending_for_stage(self, target_status: SchoolProcessingStatus) -> list[dict]:
        """
        Return schools that are ready for the NEXT stage.
        E.g., target_status=CRAWL_COMPLETE → returns schools at SEED_SCRAPED.
        """
        # Map target status to its prerequisite
        _prerequisites: dict[SchoolProcessingStatus, SchoolProcessingStatus] = {
            SchoolProcessingStatus.CRAWL_COMPLETE: SchoolProcessingStatus.SEED_SCRAPED,
            SchoolProcessingStatus.TEXT_EXTRACTED: SchoolProcessingStatus.CRAWL_COMPLETE,
            SchoolProcessingStatus.LLM_PROCESSED: SchoolProcessingStatus.TEXT_EXTRACTED,
            SchoolProcessingStatus.VALIDATED: SchoolProcessingStatus.LLM_PROCESSED,
            SchoolProcessingStatus.EXPORTED: SchoolProcessingStatus.VALIDATED,
        }
        prereq = _prerequisites.get(target_status)
        if prereq is None:
            return []
        return await self.get_schools_by_status(prereq)

    async def get_all_exportable(self) -> list[dict]:
        """Return all schools that reached VALIDATED or EXPORTED status for final export."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT * FROM schools WHERE status IN (?, ?)",
            (SchoolProcessingStatus.VALIDATED.value, SchoolProcessingStatus.EXPORTED.value)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_school(self, school_id: str) -> dict | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT * FROM schools WHERE school_id = ?", (school_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def count_by_status(self) -> dict[str, int]:
        """Return a {status: count} summary for progress display."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM schools GROUP BY status"
        )
        rows = await cursor.fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    async def total_count(self) -> int:
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT COUNT(*) FROM schools")
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Maintenance ──────────────────────────
    async def reset_all(self) -> None:
        """Drop and recreate the schools table. Used by `clean` CLI command."""
        assert self._conn is not None
        await self._conn.execute("DROP TABLE IF EXISTS schools")
        await self._conn.executescript(_SCHEMA_SQL)
        await self._conn.commit()
        logger.warning("Database reset complete.")
