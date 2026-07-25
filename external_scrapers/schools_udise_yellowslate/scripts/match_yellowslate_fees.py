#!/usr/bin/env python3
"""Match YellowSlate fee brackets to the classified UDISE school JSON.

Adds a separate `yellowslate_fee` object to matched schools. It intentionally
does not overwrite existing `fee_information`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHOOLS_INPUT = ROOT / "data/output/schools_analysis_classified.json"
YELLOWSLATE_INPUT = ROOT / "data/output/yellowslate/yellowslate_browser_fee_schools_highest_bracket.json"
OUTPUT = ROOT / "data/output/schools_analysis_classified_with_yellowslate_fees.json"
REPORT = ROOT / "data/output/yellowslate/yellowslate_udise_match_report.json"
AUDIT = ROOT / "data/output/yellowslate/yellowslate_udise_match_audit.json"


GENERIC = {
    "school", "public", "english", "medium", "high", "higher", "primary", "secondary",
    "academy", "international", "education", "educational", "institution", "institutions",
    "vidyalaya", "vidya", "mandir", "the", "of", "and", "bangalore", "bengaluru",
    "kannada", "convent", "nursery", "lps", "hps", "hs", "eps", "college", "pu",
    "pre", "preschool", "kids", "kidzee", "little", "st", "sri", "shree", "new",
}
REPLACEMENTS = {
    "sch": "school",
    "ps": "public school",
    "pub": "public",
    "hps": "higher primary school",
    "lps": "lower primary school",
    "hs": "high school",
    "intl": "international",
    "jnr": "junior",
    "mont": "montessori",
    "nps": "national public school",
    "dps": "delhi public school",
}
BRACKET_RANK = {
    "under_30k": 1,
    "30k_50k": 2,
    "50k_70k": 3,
    "70k_1l": 4,
    "1l_2l": 5,
    "above_2l": 6,
}


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", text)
    expanded: list[str] = []
    for token in tokens:
        repl = REPLACEMENTS.get(token)
        if repl:
            expanded.extend(repl.split())
        else:
            expanded.append(token)
    return " ".join(expanded)


def meaningful_tokens(value: Any) -> set[str]:
    return {x for x in normalize(value).split() if x not in GENERIC and len(x) > 1}


def name_similarity(left: Any, right: Any) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    sort_a, sort_b = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    token_sort = SequenceMatcher(None, sort_a, sort_b).ratio()
    ta, tb = meaningful_tokens(left), meaningful_tokens(right)
    overlap = len(ta & tb) / max(1, len(ta | tb))
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(sequence, token_sort, 0.68 * containment + 0.32 * overlap)


def area_similarity(y_area: Any, school: dict[str, Any]) -> float:
    if not y_area:
        return 0.0
    meta = school["metadata"]
    loc = meta.get("location") or {}
    haystack = " ".join(
        str(x or "")
        for x in (
            meta.get("address"),
            loc.get("village_or_ward"),
            loc.get("cluster"),
            loc.get("block"),
            loc.get("district"),
        )
    )
    return name_similarity(y_area, haystack)


def board_tokens(value: Any) -> set[str]:
    text = normalize(value)
    out = set()
    if "cbse" in text:
        out.add("CBSE")
    if "icse" in text or "cisce" in text or "isc" in text:
        out.add("CISCE")
    if "igcse" in text or "cambridge" in text:
        out.add("International")
    if re.search(r"\bib\b", text):
        out.add("International")
    if "state" in text:
        out.add("State Board")
    return out


def school_board_tokens(school: dict[str, Any]) -> set[str]:
    dims = school.get("analysis_dimensions") or {}
    boards = set(dims.get("boards_present") or [])
    aff = school["metadata"].get("board_affiliation") or {}
    boards |= board_tokens(" ".join(str(x or "") for x in aff.values()))
    return boards


def pricing_band(fee: dict[str, Any]) -> dict[str, Any]:
    key = fee.get("assigned_bracket_key")
    label = fee.get("assigned_bracket_label")
    return {
        "pricing_band_key": key,
        "pricing_band_name": label,
        "pricing_band_rank": BRACKET_RANK.get(key),
    }


def prepare_schools(schools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, set[int]]]:
    token_index: dict[str, set[int]] = defaultdict(set)
    prepared = []
    for idx, school in enumerate(schools):
        name = school["metadata"].get("school_name")
        tokens = meaningful_tokens(name)
        prepared.append({"name": name, "norm": normalize(name), "tokens": tokens})
        for token in tokens:
            token_index[token].add(idx)
    return prepared, token_index


def candidate_indexes(y_school: dict[str, Any], prepared: list[dict[str, Any]], token_index: dict[str, set[int]]) -> set[int]:
    tokens = meaningful_tokens(y_school.get("school_name"))
    if not tokens:
        return set()

    # Prefer rarer/distinctive shared tokens. Very broad tokens like "national"
    # can otherwise drag in thousands of schools and make fuzzy matching slow.
    token_hits = [(token, token_index.get(token, set())) for token in tokens]
    token_hits = [(token, hits) for token, hits in token_hits if hits]
    token_hits.sort(key=lambda item: len(item[1]))
    candidates: set[int] = set()
    for token, hits in token_hits[:5]:
        if len(hits) <= 900:
            candidates |= hits

    # If every token was broad, use the two least-broad tokens anyway, but cap.
    if not candidates and token_hits:
        for _, hits in token_hits[:2]:
            candidates |= set(list(hits)[:900])
    return candidates


def match_yellowslate(y_schools: list[dict[str, Any]], schools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared, token_index = prepare_schools(schools)
    decisions = []
    used_school_indexes: set[int] = set()

    for y_idx, y in enumerate(y_schools):
        candidates = candidate_indexes(y, prepared, token_index)
        ranked = []
        y_name = y.get("school_name")
        y_area = y.get("area")
        y_boards = board_tokens(y.get("board_text"))
        y_tokens = meaningful_tokens(y_name)

        for school_idx in candidates:
            school = schools[school_idx]
            prep = prepared[school_idx]
            similarity = name_similarity(y_name, prep["name"])
            shared = y_tokens & prep["tokens"]
            area_score = area_similarity(y_area, school)
            school_boards = school_board_tokens(school)
            board_match = bool(y_boards and school_boards and y_boards & school_boards)
            score = 0.78 * similarity + 0.12 * area_score + 0.07 * int(board_match) + 0.03 * min(1, len(shared) / 2)

            acceptable = (
                similarity >= 0.93
                or (similarity >= 0.86 and bool(shared))
                or (similarity >= 0.80 and area_score >= 0.45 and bool(shared))
                or (similarity >= 0.76 and area_score >= 0.60 and board_match and bool(shared))
            )
            if acceptable:
                ranked.append((score, similarity, area_score, board_match, len(shared), school_idx))

        ranked.sort(reverse=True, key=lambda x: x[0])
        best = ranked[0] if ranked else None
        runner = ranked[1] if len(ranked) > 1 else None
        ambiguous = bool(best and runner and best[0] - runner[0] < 0.035)
        duplicate = bool(best and best[5] in used_school_indexes)

        if best and not ambiguous and not duplicate:
            used_school_indexes.add(best[5])
            decisions.append(
                {
                    "status": "matched",
                    "yellowslate_index": y_idx,
                    "school_index": best[5],
                    "confidence": round(best[0], 4),
                    "name_similarity": round(best[1], 4),
                    "area_similarity": round(best[2], 4),
                    "board_match": best[3],
                    "shared_distinctive_tokens": best[4],
                    "method": "name+area+board" if best[2] >= 0.45 and best[3] else "name+area" if best[2] >= 0.45 else "name",
                    "runner_up_delta": round(best[0] - runner[0], 4) if runner else None,
                }
            )
        else:
            decisions.append(
                {
                    "status": "ambiguous" if ambiguous or duplicate else "unmatched",
                    "yellowslate_index": y_idx,
                    "school_index": None,
                    "reason": "close competing match" if ambiguous else "duplicate UDISE target" if duplicate else "no candidate passed thresholds",
                    "best_candidate": {
                        "school_index": best[5],
                        "confidence": round(best[0], 4),
                        "name_similarity": round(best[1], 4),
                        "area_similarity": round(best[2], 4),
                        "board_match": best[3],
                    } if best else None,
                }
            )
    return decisions


def main() -> None:
    school_doc = json.loads(SCHOOLS_INPUT.read_text())
    schools = school_doc["schools"]
    y_schools = json.loads(YELLOWSLATE_INPUT.read_text())

    decisions = match_yellowslate(y_schools, schools)
    status_counts = Counter(d["status"] for d in decisions)
    method_counts = Counter(d.get("method") for d in decisions if d["status"] == "matched")
    matched_students = 0

    audit_matches = []
    for decision in decisions:
        if decision["status"] != "matched":
            continue
        y = y_schools[decision["yellowslate_index"]]
        school = schools[decision["school_index"]]
        fee = y.get("fee") or {}
        band = pricing_band(fee)
        ys_fee = {
            "source": "YellowSlate",
            "school_name": y.get("school_name"),
            "school_url": y.get("school_url"),
            "board": y.get("board_text"),
            "area": y.get("area"),
            "fee_text": fee.get("fee_text"),
            "min_fee": fee.get("min_fee"),
            "max_fee": fee.get("max_fee"),
            "fee_category_key": fee.get("assigned_bracket_key"),
            "fee_category_label": fee.get("assigned_bracket_label"),
            "pricing_band_key": band["pricing_band_key"],
            "pricing_band_name": band["pricing_band_name"],
            "pricing_band_rank": band["pricing_band_rank"],
            "observed_fee_brackets": y.get("observed_fee_brackets") or [],
            "observed_bracket_keys": y.get("observed_bracket_keys") or [],
            "multi_bracket_observation": y.get("multi_bracket_observation"),
            "match": {k: v for k, v in decision.items() if k not in {"yellowslate_index", "school_index", "status"}},
        }
        school["yellowslate_fee"] = ys_fee
        matched_students += int((school.get("enrollment") or {}).get("total_students") or 0)
        audit_matches.append(
            {
                "udise_code": school.get("udise_code"),
                "udise_name": school["metadata"].get("school_name"),
                "yellowslate_name": y.get("school_name"),
                "yellowslate_url": y.get("school_url"),
                "assigned_fee_category": fee.get("assigned_bracket_label"),
                "confidence": decision["confidence"],
                "method": decision["method"],
            }
        )

    pricing_counts = Counter(
        school.get("yellowslate_fee", {}).get("pricing_band_key")
        for school in schools
        if school.get("yellowslate_fee")
    )
    board_counts = Counter(
        school.get("yellowslate_fee", {}).get("board") or "Unknown"
        for school in schools
        if school.get("yellowslate_fee")
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "udise_schools": len(schools),
        "yellowslate_unique_schools": len(y_schools),
        "matched_schools": status_counts["matched"],
        "match_coverage_of_udise_percent": round(status_counts["matched"] * 100 / len(schools), 2),
        "match_coverage_of_yellowslate_percent": round(status_counts["matched"] * 100 / len(y_schools), 2),
        "matched_students": matched_students,
        "total_students": school_doc["summary"]["students"],
        "matched_student_coverage_percent": round(matched_students * 100 / school_doc["summary"]["students"], 2),
        "unmatched_yellowslate_schools": status_counts["unmatched"],
        "ambiguous_yellowslate_schools": status_counts["ambiguous"],
        "match_methods": dict(method_counts),
        "pricing_band_counts": {k: pricing_counts.get(k, 0) for k in sorted(BRACKET_RANK, key=BRACKET_RANK.get)},
        "yellowslate_board_counts": dict(board_counts.most_common()),
    }

    school_doc["generated_at"] = report["generated_at"]
    school_doc["yellowslate_fee_coverage"] = report
    OUTPUT.write_text(json.dumps(school_doc, ensure_ascii=False, indent=2) + "\n")
    AUDIT.write_text(
        json.dumps(
            {
                "report": report,
                "matches": audit_matches,
                "unmatched_or_ambiguous": [
                    {
                        "status": d["status"],
                        "reason": d.get("reason"),
                        "yellowslate": {
                            "school_name": y_schools[d["yellowslate_index"]].get("school_name"),
                            "school_url": y_schools[d["yellowslate_index"]].get("school_url"),
                            "area": y_schools[d["yellowslate_index"]].get("area"),
                            "board": y_schools[d["yellowslate_index"]].get("board_text"),
                        },
                        "best_candidate": d.get("best_candidate"),
                    }
                    for d in decisions
                    if d["status"] != "matched"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
