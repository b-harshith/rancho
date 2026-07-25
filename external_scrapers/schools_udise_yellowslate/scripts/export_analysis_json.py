#!/usr/bin/env python3
"""Build a compact nested school/enrolment JSON document from captured UDISE+ data."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def response_data(body: str | None) -> dict[str, Any]:
    payload = load_json(body)
    if payload.get("status") is not True:
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def class_breakdown(grade_data: dict[str, Any]) -> list[dict[str, Any]]:
    totals = grade_data.get("schEnrollmentYearDataTotal") or {}
    levels: list[tuple[str, str]] = [("PRE_PRIMARY", "Pry")]
    levels.extend((str(number), str(number)) for number in range(1, 13))
    output = []
    for label, key in levels:
        boys = totals.get(f"col{key}BoyTot")
        girls = totals.get(f"col{key}GirlTot")
        total = totals.get(f"col{key}BoyGirlTot")
        if boys is None and girls is None and total is None:
            continue
        boys = int(boys or 0)
        girls = int(girls or 0)
        total = int(total if total is not None else boys + girls)
        output.append({"class_level": label, "boys": boys, "girls": girls, "total": total})
    return output


def latest_responses(db: sqlite3.Connection) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    rows = db.execute(
        """
        SELECT id,school_id,year_id,url,body_json
        FROM network_responses
        WHERE school_id IS NOT NULL AND body_json IS NOT NULL
          AND (
            url LIKE '%/school/report-card?%'
            OR url LIKE '%/school/profile?%'
            OR url LIKE '%/school-statistics/enrolment-teacher?%'
            OR url LIKE '%/getSocialData?flag=3&%'
          )
        ORDER BY id
        """
    )
    for row in rows:
        data = response_data(row["body_json"])
        if not data:
            continue
        url = row["url"]
        if "/school/report-card?" in url:
            kind = "report"
        elif "/school/profile?" in url:
            kind = "profile"
        elif "/school-statistics/enrolment-teacher?" in url:
            kind = "enrollment"
        else:
            kind = "grades"
        result.setdefault(str(row["school_id"]), {})[kind] = {
            "response_id": row["id"],
            "year_id": clean(row["year_id"]),
            "data": data,
        }
    return result


def export(database: Path, output: Path) -> dict[str, int]:
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    responses = latest_responses(db)
    school_rows = db.execute(
        """
        SELECT s.*
        FROM schools s
        JOIN (
            SELECT udise_code,MAX(id) AS latest_id
            FROM schools
            WHERE udise_code IS NOT NULL AND udise_code != ''
            GROUP BY udise_code
        ) latest ON latest.latest_id=s.id
        ORDER BY s.udise_code
        """
    ).fetchall()

    schools = []
    totals = {"schools": 0, "students": 0, "with_enrollment": 0, "partial": 0}
    for row in school_rows:
        summary = load_json(row["summary_json"])
        source = responses.get(str(row["school_id"]), {})
        report = source.get("report", {}).get("data", {})
        profile = source.get("profile", {}).get("data", {})
        enrollment = source.get("enrollment", {}).get("data", {})
        grades = source.get("grades", {}).get("data", {})
        by_class = class_breakdown(grades)
        school_status = clean(report.get("schStatusName") or summary.get("schoolStatusName"))
        if str(school_status or "").strip().lower() != "operational":
            continue

        boys = enrollment.get("totalBoy")
        girls = enrollment.get("totalGirl")
        total_students = enrollment.get("totalCount")
        if total_students is None and by_class:
            boys = sum(item["boys"] for item in by_class)
            girls = sum(item["girls"] for item in by_class)
            total_students = sum(item["total"] for item in by_class)

        quality = "complete" if report and profile and enrollment and grades else "partial"
        if quality == "partial":
            totals["partial"] += 1
        if total_students is not None:
            totals["with_enrollment"] += 1
            totals["students"] += int(total_students or 0)

        academic_year = clean(report.get("yearDesc"))
        year_id = clean(report.get("yearId")) or source.get("grades", {}).get("year_id")
        school = {
            "udise_code": clean(row["udise_code"]),
            "school_id": clean(row["school_id"]),
            "academic_year": {"year_id": year_id, "description": academic_year},
            "metadata": {
                "school_name": clean(report.get("schoolName") or row["school_name"]),
                "status": school_status,
                "management": clean(report.get("schMgmtNationalDesc") or summary.get("schMgmtType")),
                "category": clean(report.get("schCategoryDesc") or summary.get("schCategoryType")),
                "school_type": clean(report.get("schTypeDesc") or summary.get("schTypeDesc")),
                "board_affiliation": {
                    "secondary": clean(profile.get("boardSecName")),
                    "higher_secondary": clean(profile.get("boardHighSecName")),
                },
                "mediums_of_instruction": [
                    medium for medium in (
                        clean(profile.get("mediumOfInstrName1")),
                        clean(profile.get("mediumOfInstrName2")),
                        clean(profile.get("mediumOfInstrName3")),
                        clean(profile.get("mediumOfInstrName4")),
                    ) if medium and medium != "NA"
                ],
                "lowest_class": report.get("lowClass") or summary.get("classFrm"),
                "highest_class": report.get("highClass") or summary.get("classTo"),
                "established_year": clean(profile.get("estdYear")),
                "address": clean(profile.get("address") or summary.get("address")),
                "searched_pincode": clean(row["pincode"]),
                "reported_pincode": clean(report.get("pincode") or summary.get("pincode")),
                "location": {
                    "state": clean(report.get("stateName") or summary.get("stateName")),
                    "district": clean(report.get("districtName") or summary.get("districtName")),
                    "block": clean(report.get("blockName") or summary.get("blockName")),
                    "cluster": clean(report.get("clusterName") or summary.get("clusterName")),
                    "village_or_ward": clean(report.get("villWardName") or summary.get("villageName")),
                    "latitude": summary.get("latitude"),
                    "longitude": summary.get("longitude"),
                },
                "contact": {
                    "email": clean(profile.get("email") or summary.get("email")),
                    "phone": clean(profile.get("schPhone")),
                    "website": clean(profile.get("website")),
                    "headmaster_name": clean(profile.get("headMasterName")),
                },
            },
            "enrollment": {
                "boys": int(boys) if boys is not None else None,
                "girls": int(girls) if girls is not None else None,
                "total_students": int(total_students) if total_students is not None else None,
                "by_class": by_class,
            },
            "data_quality": {
                "status": quality,
                "missing_sections": [
                    name for name, value in {
                        "report_card": report,
                        "profile": profile,
                        "enrollment": enrollment,
                        "class_breakdown": grades,
                    }.items() if not value
                ],
                "source_response_ids": {
                    name: details.get("response_id") for name, details in source.items()
                },
            },
        }
        schools.append(school)

    totals["schools"] = len(schools)
    document = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": totals,
        "schools": schools,
    }
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    db.close()
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/runtime/udise_data.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("data/output/schools_analysis.json"))
    args = parser.parse_args()
    print(json.dumps(export(args.database, args.output), indent=2))


if __name__ == "__main__":
    main()
