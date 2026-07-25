#!/usr/bin/env python3
"""Build compact analysis classifications while preserving every original field."""

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHOOLS_INPUT = ROOT / "data/output/schools_analysis_with_fees.json"
BOARDS_INPUT = ROOT / "data/output/schools_analysis_with_boards.json"
JSON_OUTPUT = ROOT / "data/output/schools_analysis_classified.json"
DB_OUTPUT = ROOT / "data/output/schools_analytics.sqlite3"
REPORT_OUTPUT = ROOT / "data/output/classification_summary.json"


def management_group(value):
    text = str(value or "").lower()
    if "private unaided" in text or "madrasa private" in text:
        return "Private Unaided"
    if "aided" in text:
        return "Government Aided"
    if "private" in text or "madrasa" in text:
        return "Private Unaided"
    if any(x in text for x in ("department", "local body", "state govt", "welfare")):
        return "Government"
    return "Special / Autonomous"


def board_group(board):
    value = board.get("board_group")
    if value in {"State Board", "CBSE", "CISCE"}:
        return value
    if value in {"International", "Multi-board"}:
        return "International / Multi-board"
    # Unresolved private schools stay null; inferred government schools are already State Board.
    return None


def board_structure(board):
    status = board.get("status")
    if board.get("board_group") == "Multi-board":
        return "Multi-board"
    if status == "reported":
        return "Single-board"
    if status == "inferred":
        return "Inferred"
    return "Unresolved"


def school_level(highest):
    if not isinstance(highest, int):
        return None
    if highest <= 5:
        return "Primary"
    if highest <= 8:
        return "Upper Primary"
    if highest <= 10:
        return "Secondary"
    return "Higher Secondary"


def gender_group(value):
    text = str(value or "").lower()
    if "co-ed" in text or "coed" in text:
        return "Co-ed"
    if "boys" in text or "boy" in text:
        return "Boys"
    if "girls" in text or "girl" in text:
        return "Girls"
    return None


def enrollment_group(total):
    if not isinstance(total, (int, float)):
        return None
    if total <= 100:
        return "Small (0-100)"
    if total <= 500:
        return "Medium (101-500)"
    if total <= 1500:
        return "Large (501-1500)"
    return "Very Large (1501+)"


def fee_group(fee):
    if not fee:
        return None
    value = fee.get("average_annual_fee")
    if not isinstance(value, (int, float)):
        return None
    if value <= 45000:
        return "Budget (≤45k)"
    if value <= 75000:
        return "Affordable (45-75k)"
    if value <= 150000:
        return "Premium (75-150k)"
    return "Luxury (>150k)"


def language_group(values):
    langs = {str(x).split("-", 1)[-1].strip().lower() for x in (values or [])}
    if len(langs) > 1:
        return "Multilingual"
    if "english" in langs:
        return "English"
    if "kannada" in langs:
        return "Kannada"
    return "Other Indian Language" if langs else None


def age_group(year):
    try:
        age = 2025 - int(year)
    except (TypeError, ValueError):
        return None
    if age < 10:
        return "New (<10 years)"
    if age < 25:
        return "Established (10-24)"
    if age < 50:
        return "Mature (25-49)"
    return "Legacy (50+ years)"


def region_group(location, address=None, school_name=None):
    state = str(location.get("state") or "").upper()
    district = str(location.get("district") or "").upper()
    locality_text = f"{address or ''} {school_name or ''}".upper()
    if any(x in district for x in ("BENGALURU URBAN", "BANGALORE URBAN", "BENGALURU U ", "BANGALORE U ", "BENGALURU REGION")):
        return "Bengaluru Urban"
    if "BENGALURU URBAN" in locality_text or "BANGALORE URBAN" in locality_text:
        return "Bengaluru Urban"
    if "BENGALURU RURAL" in district or "BANGALORE RURAL" in district:
        return "Bengaluru Rural"
    if state == "KARNATAKA":
        return "Other Karnataka"
    return "Outside Karnataka"


def quality_group(quality):
    status = str(quality.get("status") or "").lower()
    missing = len(quality.get("missing_sections") or [])
    if status == "complete" and missing == 0:
        return "Complete"
    if missing <= 1:
        return "Minor Gaps"
    if missing <= 3:
        return "Partial"
    return "Major Gaps"


def main():
    fee_document = json.loads(SCHOOLS_INPUT.read_text())
    board_document = json.loads(BOARDS_INPUT.read_text())
    boards = {s["udise_code"]: s["board_classification"] for s in board_document["schools"]}
    # Karnataka UDISE codes begin with 29. Use the code instead of the reported
    # state field because centrally managed schools may store an administrative
    # region or organisation name there.
    excluded_non_karnataka = [
        s for s in fee_document["schools"] if not str(s.get("udise_code") or "").startswith("29")
    ]
    fee_document["schools"] = [
        s for s in fee_document["schools"] if str(s.get("udise_code") or "").startswith("29")
    ]
    distributions = defaultdict(Counter)

    for school in fee_document["schools"]:
        metadata = school["metadata"]
        enrollment = school.get("enrollment") or {}
        board = boards.get(school["udise_code"], {})
        school["board_classification"] = board
        dimensions = {
            "board_group": board_group(board),
            "board_structure": board_structure(board),
            "boards_present": board.get("boards_present") or [],
            "management_group": management_group(metadata.get("management")),
            "school_level": school_level(metadata.get("highest_class")),
            "gender_group": gender_group(metadata.get("school_type")),
            "enrollment_group": enrollment_group(enrollment.get("total_students")),
            "fee_group": fee_group(school.get("fee_information")),
            "language_group": language_group(metadata.get("mediums_of_instruction")),
            "school_age_group": age_group(metadata.get("established_year")),
            "region_group": region_group(
                metadata.get("location") or {}, metadata.get("address"), metadata.get("school_name")
            ),
            "data_quality_group": quality_group(school.get("data_quality") or {}),
        }
        school["analysis_dimensions"] = dimensions
        for key, value in dimensions.items():
            if key != "boards_present":
                distributions[key][value if value is not None else "Unclassified"] += 1

    generated_at = datetime.now(timezone.utc).isoformat()
    fee_document["generated_at"] = generated_at
    fee_document["classification_schema"] = {
        "maximum_categories_per_dimension": 4,
        "null_policy": "Missing or unsupported classifications are null, not a fifth category.",
        "dimensions": {key: sorted(v for v in counts if v != "Unclassified") for key, counts in distributions.items()},
    }
    fee_document["summary"]["schools"] = len(fee_document["schools"])
    fee_document["summary"]["students"] = sum(
        (s.get("enrollment") or {}).get("total_students") or 0 for s in fee_document["schools"]
    )
    fee_document["summary"]["with_enrollment"] = sum(
        1 for s in fee_document["schools"] if (s.get("enrollment") or {}).get("total_students") is not None
    )
    fee_document["summary"]["partial"] = sum(
        1 for s in fee_document["schools"] if (s.get("data_quality") or {}).get("status") != "complete"
    )
    fee_document["exclusions"] = {
        "rule": "Exclude UDISE codes not beginning with Karnataka state code 29.",
        "count": len(excluded_non_karnataka),
        "schools": [
            {
                "udise_code": s.get("udise_code"),
                "school_name": s.get("metadata", {}).get("school_name"),
                "reported_state": s.get("metadata", {}).get("location", {}).get("state"),
            }
            for s in excluded_non_karnataka
        ],
    }
    JSON_OUTPUT.write_text(json.dumps(fee_document, ensure_ascii=False, indent=2) + "\n")

    if DB_OUTPUT.exists():
        DB_OUTPUT.unlink()
    connection = sqlite3.connect(DB_OUTPUT)
    connection.execute(
        """CREATE TABLE school_analytics (
            udise_code TEXT PRIMARY KEY, school_id TEXT, school_name TEXT,
            reported_management TEXT, reported_secondary_board TEXT,
            reported_higher_secondary_board TEXT, reported_mediums_json TEXT,
            board_group TEXT, board_structure TEXT, boards_present_json TEXT,
            management_group TEXT, school_level TEXT, gender_group TEXT,
            enrollment_group TEXT, fee_group TEXT, language_group TEXT,
            school_age_group TEXT, region_group TEXT, data_quality_group TEXT,
            total_students INTEGER, annual_fee REAL, fee_is_estimated INTEGER,
            pincode TEXT, latitude REAL, longitude REAL, original_json TEXT
        )"""
    )
    for school in fee_document["schools"]:
        m = school["metadata"]
        d = school["analysis_dimensions"]
        b = m.get("board_affiliation") or {}
        loc = m.get("location") or {}
        fee = school.get("fee_information") or {}
        connection.execute(
            "INSERT INTO school_analytics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                school["udise_code"], school.get("school_id"), m.get("school_name"),
                m.get("management"), b.get("secondary"), b.get("higher_secondary"),
                json.dumps(m.get("mediums_of_instruction") or []), d["board_group"],
                d["board_structure"], json.dumps(d["boards_present"]), d["management_group"],
                d["school_level"], d["gender_group"], d["enrollment_group"], d["fee_group"],
                d["language_group"], d["school_age_group"], d["region_group"],
                d["data_quality_group"], (school.get("enrollment") or {}).get("total_students"),
                fee.get("average_annual_fee"), int(bool(fee.get("is_fee_estimated"))) if fee else None,
                m.get("reported_pincode"), loc.get("latitude"), loc.get("longitude"),
                json.dumps(school, ensure_ascii=False),
            ),
        )
    for column in ("board_group", "management_group", "school_level", "enrollment_group", "fee_group", "region_group"):
        connection.execute(f"CREATE INDEX idx_school_analytics_{column} ON school_analytics({column})")
    connection.commit()
    connection.close()

    summary = {
        "generated_at": generated_at,
        "schools": len(fee_document["schools"]),
        "distributions": {key: dict(counts) for key, counts in distributions.items()},
    }
    REPORT_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
