"""
src/models.py
─────────────
Canonical Pydantic schemas — the single data contract for the entire pipeline.
Every module that produces or consumes structured school data MUST use these models.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────
class Board(str, Enum):
    """Recognised school boards."""
    CBSE = "CBSE"
    ICSE = "ICSE"
    IB = "IB"
    STATE = "STATE"
    UNKNOWN = "UNKNOWN"


class SchoolProcessingStatus(str, Enum):
    """Pipeline state-machine states persisted in SQLite."""
    PENDING = "PENDING"
    SEED_SCRAPED = "SEED_SCRAPED"
    CRAWL_COMPLETE = "CRAWL_COMPLETE"
    TEXT_EXTRACTED = "TEXT_EXTRACTED"
    LLM_PROCESSED = "LLM_PROCESSED"
    VALIDATED = "VALIDATED"
    EXPORTED = "EXPORTED"

    # Terminal failure states
    DEAD_LINK = "DEAD_LINK"
    BOT_BLOCKED = "BOT_BLOCKED"
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    DOCS_NOT_FOUND = "DOCS_NOT_FOUND"
    LLM_ERROR = "LLM_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class FeePeriod(str, Enum):
    """Billing cycle for a fee amount."""
    MONTHLY = "Monthly"
    QUARTERLY = "Quarterly"
    SEMI_ANNUAL = "Semi-Annual"
    ANNUAL = "Annual"
    UNKNOWN = "Unknown"


class DocumentType(str, Enum):
    """The two prongs of the deep crawler."""
    COMPLIANCE = "compliance"
    FEES = "fees"


# ──────────────────────────────────────────────
# Seed / Registry record
# ──────────────────────────────────────────────
class SeedSchool(BaseModel):
    """One row from the registry seed generator (Module 1)."""
    school_id: str = Field(description="Deterministic ID: {board}_{affiliation_code or slug}")
    name: str
    board: Board
    locality: str = ""
    pincode: str = ""
    website_url: str = ""


# ──────────────────────────────────────────────
# Crawler output
# ──────────────────────────────────────────────
class CrawlResult(BaseModel):
    """Result from the dual-pronged deep crawler (Module 2) for one school."""
    school_id: str
    compliance_doc_path: Optional[str] = None  # path or None
    fees_doc_path: Optional[str] = None
    compliance_source_url: Optional[str] = None
    fees_source_url: Optional[str] = None


# ──────────────────────────────────────────────
# LLM output schemas (Module 4) — matches spec exactly
# ──────────────────────────────────────────────
class GradeFeeTuple(BaseModel):
    """A single grade-band ↔ fee row extracted by the LLM."""
    grade_band: str = Field(description="e.g., 'Primary', 'Grade 1-5', 'Grade 11-12'")
    raw_fee_amount: int = Field(description="The exact numerical fee amount stated on the document.")
    fee_period: FeePeriod = Field(description="The billing cycle associated with the raw_fee_amount.")


class SchoolIntelligenceData(BaseModel):
    """
    Structured facts extracted by the LLM from raw text.
    This is the enforced output schema for `instructor` / `openai` calls.
    """
    # ── Volume & Infrastructure Facts ──
    direct_student_count: Optional[int] = Field(
        default=None, description="Explicitly stated total number of students"
    )
    total_teachers: Optional[int] = Field(
        default=None, description="Total number of teaching staff"
    )
    total_sections: Optional[int] = Field(
        default=None, description="Total number of class sections/divisions"
    )
    grades_offered: Optional[int] = Field(
        default=None, description="Number of grades, e.g., 1 to 12 = 12"
    )
    student_teacher_ratio: Optional[str] = Field(
        default=None, description="Stated ratio, e.g., '1:20'"
    )

    # ── Pricing Facts ──
    fee_table: Optional[list[GradeFeeTuple]] = Field(
        default=None,
        description="Array of grades and their respective extracted fee structures",
    )


# ──────────────────────────────────────────────
# Validated / enriched row (Module 5 output)
# ──────────────────────────────────────────────
class ValidatedSchoolRecord(BaseModel):
    """Final enriched record ready for export."""
    school_id: str
    name: str
    board: str
    locality: str
    pincode: str
    website_url: str

    # LLM-extracted fields
    direct_student_count: Optional[int] = None
    total_teachers: Optional[int] = None
    total_sections: Optional[int] = None
    grades_offered: Optional[int] = None
    student_teacher_ratio: Optional[str] = None

    # Computed fee fields
    fee_table_json: Optional[str] = None  # stringified JSON array
    calculated_average_annual_fee_inr: Optional[float] = None
    highest_annual_fee_inr: Optional[int] = None
    fee_data_found: bool = False
    fee_anomaly: bool = False

    # Geocode prepper
    geocode_query: str = ""

    # Status
    status: SchoolProcessingStatus = SchoolProcessingStatus.PENDING
    error_detail: Optional[str] = None
