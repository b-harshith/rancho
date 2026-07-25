#!/usr/bin/env python3
"""Create an analysis dataset with reported and conservatively inferred board groups."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/output/schools_analysis.json"
OUTPUT = ROOT / "data/output/schools_analysis_with_boards.json"
REPORT = ROOT / "data/output/board_inference_report.json"
NO_BOARD_OUTPUT = ROOT / "data/output/unresolved_board_schools.json"


def family(value):
    text = str(value or "").lower()
    if "state board" in text:
        return "State Board"
    if "cbse" in text:
        return "CBSE"
    if "icse" in text or "cisce" in text:
        return "CISCE"
    if any(token in text for token in ("international", "igcse", "cambridge", "ib")):
        return "International"
    return None


def classify(school):
    metadata = school["metadata"]
    affiliation = metadata.get("board_affiliation") or {}
    families = sorted(
        {
            family(affiliation.get("secondary")),
            family(affiliation.get("higher_secondary")),
        }
        - {None}
    )

    if len(families) > 1:
        return {
            "board_group": "Multi-board",
            "source_boards": families,
            "status": "reported",
            "confidence": 1.0,
            "reason": "Distinct secondary and higher-secondary affiliations reported by UDISE.",
        }
    if families:
        return {
            "board_group": families[0],
            "source_boards": families,
            "status": "reported",
            "confidence": 1.0,
            "reason": "Affiliation reported by UDISE.",
        }

    management = str(metadata.get("management") or "")
    if management in {
        "Department of Education",
        "Local Body",
        "Local body",
        "Other State Govt. Managed",
        "Tribal Welfare Department",
        "Social Welfare Department",
        "Government Aided",
    }:
        return {
            "board_group": "State Board",
            "source_boards": [],
            "status": "inferred",
            "confidence": 0.9,
            "reason": f"Missing affiliation; inferred from management: {management}.",
        }
    if management in {"Kendriya Vidyalaya Sangathan", "Navodaya Vidyalaya Samiti"}:
        return {
            "board_group": "CBSE",
            "source_boards": [],
            "status": "inferred",
            "confidence": 0.95,
            "reason": f"Missing affiliation; inferred from management: {management}.",
        }

    return {
        "board_group": "Unresolved",
        "source_boards": [],
        "status": "unresolved",
        "confidence": 0.0,
        "reason": "Secondary-level affiliation is missing and private management is not board-specific.",
    }


def main():
    document = json.loads(INPUT.read_text())
    counts = Counter()
    status_counts = Counter()
    unresolved = []
    unresolved_board_schools = []
    unresolved_board_students = 0
    unresolved_students_by_class = Counter()

    for school in document["schools"]:
        result = classify(school)
        result["boards_present"] = list(result["source_boards"])
        school["board_classification"] = result
        counts[result["board_group"]] += 1
        status_counts[result["status"]] += 1
        if result["status"] == "unresolved":
            unresolved.append(
                {
                    "udise_code": school["udise_code"],
                    "school_name": school["metadata"].get("school_name"),
                    "management": school["metadata"].get("management"),
                    "highest_class": school["metadata"].get("highest_class"),
                }
            )
        if result["status"] == "unresolved":
            enrollment = school.get("enrollment") or {}
            total_students = enrollment.get("total_students") or 0
            unresolved_board_students += total_students
            for row in enrollment.get("by_class") or []:
                unresolved_students_by_class[str(row.get("class_level"))] += row.get("total") or 0
            unresolved_board_schools.append(
                {
                    "udise_code": school["udise_code"],
                    "school_id": school.get("school_id"),
                    "school_name": school["metadata"].get("school_name"),
                    "management": school["metadata"].get("management"),
                    "category": school["metadata"].get("category"),
                    "lowest_class": school["metadata"].get("lowest_class"),
                    "highest_class": school["metadata"].get("highest_class"),
                    "pincode": school["metadata"].get("reported_pincode"),
                    "address": school["metadata"].get("address"),
                    "total_students": total_students,
                }
            )

    generated_at = datetime.now(timezone.utc).isoformat()
    document["generated_at"] = generated_at
    document["board_summary"] = {
        "total_schools": len(document["schools"]),
        "by_group": dict(counts),
        "by_status": dict(status_counts),
    }
    OUTPUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    REPORT.write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "total_schools": len(document["schools"]),
                "by_group": dict(counts),
                "by_status": dict(status_counts),
                "unresolved_schools": unresolved,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    NO_BOARD_OUTPUT.write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "definition": "Schools with no reported affiliation whose management does not support a reliable board inference.",
                "summary": {
                    "schools": len(unresolved_board_schools),
                    "total_students": unresolved_board_students,
                    "students_by_class": dict(unresolved_students_by_class),
                },
                "schools": unresolved_board_schools,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(json.dumps({"by_group": counts, "by_status": status_counts}, default=dict, indent=2))


if __name__ == "__main__":
    main()
