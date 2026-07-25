#!/usr/bin/env python3
"""Match YellowSlate schools with extracted branch locations to UDISE schools.

This is a second-pass matcher after `scrape_yellowslate_locations.py`.

It prefers branch-level evidence:
  1. YellowSlate location pincode/address + school-name similarity.
  2. YellowSlate area/address tokens + school-name similarity.
  3. For YellowSlate records without a location, stricter name + board/area
     fallback matching.

Outputs a classified UDISE JSON with `yellowslate_fee` appended to matched
schools, plus a report and a detailed audit.
"""

from __future__ import annotations

import copy
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
YELLOWSLATE_INPUT = ROOT / "data/output/yellowslate/yellowslate_schools_with_locations.json"
OUTPUT = ROOT / "data/output/schools_analysis_classified_with_yellowslate_location_fees.json"
REPORT = ROOT / "data/output/yellowslate/yellowslate_udise_location_match_report.json"
AUDIT = ROOT / "data/output/yellowslate/yellowslate_udise_location_match_audit.json"


GENERIC = {
    "school", "public", "english", "medium", "high", "higher", "primary", "secondary",
    "academy", "international", "education", "educational", "institution", "institutions",
    "vidyalaya", "vidya", "mandir", "the", "of", "and", "bangalore", "bengaluru",
    "kannada", "convent", "nursery", "lps", "hps", "hs", "eps", "college", "pu",
    "pre", "preschool", "kids", "kidzee", "little", "st", "sri", "shree", "new",
    "matric", "schooling", "centre", "center", "learning", "residential", "global",
    "national", "state", "board",
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
    "rvk": "rashtrotthana vidya kendra",
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


def tokens(value: Any, *, keep_generic: bool = False) -> set[str]:
    words = normalize(value).split()
    if keep_generic:
        return {x for x in words if len(x) > 1}
    return {x for x in words if x not in GENERIC and len(x) > 1}


def token_jaccard(left: Any, right: Any, *, keep_generic: bool = False) -> float:
    a, b = tokens(left, keep_generic=keep_generic), tokens(right, keep_generic=keep_generic)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def name_similarity(left: Any, right: Any) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    sort_a, sort_b = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    token_sort = SequenceMatcher(None, sort_a, sort_b).ratio()
    ta, tb = tokens(left), tokens(right)
    overlap = len(ta & tb) / max(1, len(ta | tb))
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(sequence, token_sort, 0.72 * containment + 0.28 * overlap)


def clean_pincode(value: Any) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b([1-9]\d{5})\b", str(value))
    return match.group(1) if match else None


def board_tokens(value: Any) -> set[str]:
    text = normalize(value)
    out = set()
    if "cbse" in text:
        out.add("CBSE")
    if "icse" in text or "cisce" in text or "isc" in text:
        out.add("CISCE")
    if "igcse" in text or "cambridge" in text or "caie" in text:
        out.add("International")
    if re.search(r"\bib\b", text):
        out.add("International")
    if "state" in text or "kseeb" in text or "sslc" in text:
        out.add("State Board")
    return out


def school_board_tokens(school: dict[str, Any]) -> set[str]:
    dims = school.get("analysis_dimensions") or {}
    boards = set(dims.get("boards_present") or [])
    group = dims.get("board_group") or (school.get("board_classification") or {}).get("board_group")
    boards |= board_tokens(group)
    aff = (school.get("metadata") or {}).get("board_affiliation") or {}
    boards |= board_tokens(" ".join(str(x or "") for x in aff.values()))
    return boards


def school_location_text(school: dict[str, Any]) -> str:
    meta = school.get("metadata") or {}
    loc = meta.get("location") or {}
    return " ".join(
        str(x or "")
        for x in (
            meta.get("address"),
            meta.get("reported_pincode"),
            meta.get("searched_pincode"),
            loc.get("village_or_ward"),
            loc.get("cluster"),
            loc.get("block"),
            loc.get("district"),
            loc.get("state"),
        )
    )


def yellowslate_location_text(y: dict[str, Any]) -> str:
    loc = y.get("school_location") or {}
    return " ".join(str(x or "") for x in (y.get("area"), loc.get("address")))


def pincode_match(y_pin: str | None, school: dict[str, Any]) -> tuple[bool, str | None]:
    meta = school.get("metadata") or {}
    reported = clean_pincode(meta.get("reported_pincode"))
    searched = clean_pincode(meta.get("searched_pincode"))
    if y_pin and reported and y_pin == reported:
        return True, "reported_pincode"
    if y_pin and searched and y_pin == searched:
        return True, "searched_pincode"
    return False, None


def prepare_schools(schools: list[dict[str, Any]]) -> dict[str, Any]:
    token_index: dict[str, set[int]] = defaultdict(set)
    pincode_index: dict[str, set[int]] = defaultdict(set)
    prepared = []
    for idx, school in enumerate(schools):
        meta = school.get("metadata") or {}
        name = meta.get("school_name")
        name_tokens = tokens(name)
        loc_text = school_location_text(school)
        record = {
            "name": name,
            "name_tokens": name_tokens,
            "location_text": loc_text,
            "location_tokens": tokens(loc_text, keep_generic=True),
            "boards": school_board_tokens(school),
        }
        prepared.append(record)
        for token in name_tokens:
            token_index[token].add(idx)
        for pin in {clean_pincode(meta.get("reported_pincode")), clean_pincode(meta.get("searched_pincode"))}:
            if pin:
                pincode_index[pin].add(idx)
    return {"records": prepared, "token_index": token_index, "pincode_index": pincode_index}


def candidate_indexes(y: dict[str, Any], prepared_bundle: dict[str, Any]) -> set[int]:
    token_index: dict[str, set[int]] = prepared_bundle["token_index"]
    pincode_index: dict[str, set[int]] = prepared_bundle["pincode_index"]
    y_name_tokens = tokens(y.get("school_name"))
    y_pin = (y.get("school_location") or {}).get("pincode")

    candidates: set[int] = set()
    if y_pin:
        candidates |= pincode_index.get(y_pin, set())

    token_hits = [(token, token_index.get(token, set())) for token in y_name_tokens]
    token_hits = [(token, hits) for token, hits in token_hits if hits]
    token_hits.sort(key=lambda item: len(item[1]))

    # Add rarer-token name candidates. For pincode records this catches cases
    # where UDISE has a wrong/missing pincode; for no-location records this is
    # the main candidate source.
    cap = 1200 if not y_pin else 500
    for _, hits in token_hits[:6]:
        if len(hits) <= cap:
            candidates |= hits
    if not candidates and token_hits:
        for _, hits in token_hits[:2]:
            candidates |= set(list(hits)[:cap])
    return candidates


def evaluate_pair(y: dict[str, Any], school: dict[str, Any], prep: dict[str, Any]) -> dict[str, Any]:
    y_name = y.get("school_name")
    y_loc = y.get("school_location") or {}
    y_pin = y_loc.get("pincode")
    y_location_text = yellowslate_location_text(y)
    y_boards = board_tokens(y.get("board_text"))
    name_score = name_similarity(y_name, prep["name"])
    area_score = max(
        name_similarity(y.get("area"), prep["location_text"]) if y.get("area") else 0.0,
        token_jaccard(y_location_text, prep["location_text"], keep_generic=True),
    )
    pin_ok, pin_field = pincode_match(y_pin, school)
    meta = school.get("metadata") or {}
    school_pins = {clean_pincode(meta.get("reported_pincode")), clean_pincode(meta.get("searched_pincode"))}
    school_pins.discard(None)
    pincode_conflict = bool(y_pin and school_pins and not pin_ok)
    board_match = bool(y_boards and prep["boards"] and y_boards & prep["boards"])
    board_conflict = bool(y_boards and prep["boards"] and not (y_boards & prep["boards"]))
    shared = tokens(y_name) & prep["name_tokens"]
    shared_count = len(shared)
    has_location = bool(y_loc.get("address"))

    if has_location:
        score = (
            0.62 * name_score
            + 0.17 * int(pin_ok)
            + 0.13 * area_score
            + 0.05 * int(board_match)
            + 0.03 * min(1.0, len(shared) / 2)
        )
    else:
        score = (
            0.78 * name_score
            + 0.10 * area_score
            + 0.08 * int(board_match)
            + 0.04 * min(1.0, len(shared) / 2)
        )

    acceptable = False
    method = None
    if has_location:
        if pin_ok and name_score >= 0.88 and (shared_count >= 1 or name_score >= 0.94):
            acceptable, method = True, f"name+pincode:{pin_field}"
        elif pin_ok and name_score >= 0.78 and area_score >= 0.16 and shared_count >= 1:
            acceptable, method = True, f"name+pincode+address:{pin_field}"
        elif pin_ok and name_score >= 0.74 and area_score >= 0.25 and board_match and shared_count >= 1:
            acceptable, method = True, f"name+pincode+address+board:{pin_field}"
        elif name_score >= 0.88 and area_score >= 0.38 and shared_count >= 2:
            acceptable, method = True, "name+address"
        elif name_score >= 0.84 and area_score >= 0.42 and board_match and shared_count >= 2:
            acceptable, method = True, "name+address+board"
    else:
        if name_score >= 0.95:
            acceptable, method = True, "fallback:name_strong"
        elif name_score >= 0.90 and area_score >= 0.30 and shared_count >= 2:
            acceptable, method = True, "fallback:name+area"
        elif name_score >= 0.88 and area_score >= 0.25 and board_match and shared_count >= 2:
            acceptable, method = True, "fallback:name+area+board"
        elif name_score >= 0.91 and board_match and shared_count >= 2:
            acceptable, method = True, "fallback:name+board"

    if board_conflict and not pin_ok and name_score < 0.93:
        acceptable = False
        method = None
    if pincode_conflict and not pin_ok and shared_count < 2:
        acceptable = False
        method = None

    return {
        "score": score,
        "acceptable": acceptable,
        "method": method,
        "name_similarity": name_score,
        "area_similarity": area_score,
        "pincode_match": pin_ok,
        "pincode_match_field": pin_field,
        "pincode_conflict": pincode_conflict,
        "board_match": board_match,
        "board_conflict": board_conflict,
        "shared_distinctive_tokens": sorted(shared),
        "has_yellowslate_location": has_location,
    }


def build_edges(y_schools: list[dict[str, Any]], schools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bundle = prepare_schools(schools)
    prepared = bundle["records"]
    edges = []
    diagnostics = []

    for y_idx, y in enumerate(y_schools):
        candidates = candidate_indexes(y, bundle)
        ranked = []
        for school_idx in candidates:
            metrics = evaluate_pair(y, schools[school_idx], prepared[school_idx])
            if metrics["acceptable"]:
                ranked.append({"yellowslate_index": y_idx, "school_index": school_idx, **metrics})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        if ranked:
            best = ranked[0]
            runner = ranked[1] if len(ranked) > 1 else None
            best["runner_up_delta"] = best["score"] - runner["score"] if runner else None
            edges.append(best)
            diagnostics.append(
                {
                    "yellowslate_index": y_idx,
                    "status": "candidate_found",
                    "candidate_count": len(ranked),
                    "best": compact_edge(best),
                    "runner_up": compact_edge(runner) if runner else None,
                }
            )
        else:
            diagnostics.append(
                {
                    "yellowslate_index": y_idx,
                    "status": "no_candidate",
                    "candidate_count": 0,
                    "reason": "no candidate passed thresholds",
                }
            )
    return edges, diagnostics


def compact_edge(edge: dict[str, Any] | None) -> dict[str, Any] | None:
    if not edge:
        return None
    return {
        "school_index": edge["school_index"],
        "score": round(edge["score"], 4),
        "method": edge.get("method"),
        "name_similarity": round(edge["name_similarity"], 4),
        "area_similarity": round(edge["area_similarity"], 4),
        "pincode_match": edge["pincode_match"],
        "pincode_match_field": edge["pincode_match_field"],
        "board_match": edge["board_match"],
        "board_conflict": edge["board_conflict"],
        "shared_distinctive_tokens": edge["shared_distinctive_tokens"],
        "runner_up_delta": round(edge["runner_up_delta"], 4) if edge.get("runner_up_delta") is not None else None,
    }


def select_one_to_one(edges: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, str]]:
    # Mark very tight per-YellowSlate races as ambiguous before global greedy.
    best_by_y: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        best_by_y[edge["yellowslate_index"]].append(edge)

    ambiguous_y: dict[int, str] = {}
    eligible = []
    for y_idx, y_edges in best_by_y.items():
        y_edges.sort(key=lambda item: item["score"], reverse=True)
        best = y_edges[0]
        runner = y_edges[1] if len(y_edges) > 1 else None
        ambiguous_gap = 0.025 if best["has_yellowslate_location"] else 0.04
        if runner and best["score"] - runner["score"] < ambiguous_gap:
            ambiguous_y[y_idx] = "close competing UDISE candidates"
        else:
            eligible.append(best)

    eligible.sort(key=lambda item: item["score"], reverse=True)
    used_y: set[int] = set()
    used_school: set[int] = set()
    selected = []
    for edge in eligible:
        y_idx, school_idx = edge["yellowslate_index"], edge["school_index"]
        if y_idx in used_y:
            continue
        if school_idx in used_school:
            ambiguous_y[y_idx] = "UDISE target already claimed by stronger YellowSlate match"
            continue
        used_y.add(y_idx)
        used_school.add(school_idx)
        selected.append(edge)
    return selected, ambiguous_y


def pricing_band(fee: dict[str, Any]) -> dict[str, Any]:
    key = fee.get("assigned_bracket_key")
    label = fee.get("assigned_bracket_label")
    return {
        "pricing_band_key": key,
        "pricing_band_name": label,
        "pricing_band_rank": BRACKET_RANK.get(key),
    }


def matched_fee_payload(y: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    fee = y.get("fee") or {}
    band = pricing_band(fee)
    loc = y.get("school_location") or {}
    return {
        "source": "YellowSlate",
        "school_name": y.get("school_name"),
        "school_url": y.get("school_url"),
        "board": y.get("board_text"),
        "area": y.get("area"),
        "location": {
            "address": loc.get("address"),
            "pincode": loc.get("pincode"),
            "extraction_method": loc.get("extraction_method"),
        },
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
        "match": {
            "confidence": round(edge["score"], 4),
            "method": edge["method"],
            "name_similarity": round(edge["name_similarity"], 4),
            "area_similarity": round(edge["area_similarity"], 4),
            "pincode_match": edge["pincode_match"],
            "pincode_match_field": edge["pincode_match_field"],
            "board_match": edge["board_match"],
            "board_conflict": edge["board_conflict"],
            "shared_distinctive_tokens": edge["shared_distinctive_tokens"],
            "runner_up_delta": round(edge["runner_up_delta"], 4) if edge.get("runner_up_delta") is not None else None,
        },
    }


def main() -> None:
    school_doc = json.loads(SCHOOLS_INPUT.read_text())
    schools = copy.deepcopy(school_doc["schools"])
    y_schools = json.loads(YELLOWSLATE_INPUT.read_text())

    edges, diagnostics = build_edges(y_schools, schools)
    selected, ambiguous_y = select_one_to_one(edges)
    matched_by_y = {edge["yellowslate_index"]: edge for edge in selected}

    matched_students = 0
    audit_matches = []
    for edge in selected:
        y = y_schools[edge["yellowslate_index"]]
        school = schools[edge["school_index"]]
        school["yellowslate_fee"] = matched_fee_payload(y, edge)
        matched_students += int((school.get("enrollment") or {}).get("total_students") or 0)
        audit_matches.append(
            {
                "udise_code": school.get("udise_code"),
                "udise_name": (school.get("metadata") or {}).get("school_name"),
                "udise_pincode": (school.get("metadata") or {}).get("reported_pincode"),
                "udise_location": school_location_text(school),
                "yellowslate_name": y.get("school_name"),
                "yellowslate_url": y.get("school_url"),
                "yellowslate_board": y.get("board_text"),
                "yellowslate_location": y.get("school_location") or {},
                "assigned_fee_category": (y.get("fee") or {}).get("assigned_bracket_label"),
                **compact_edge(edge),
            }
        )

    status_counts = Counter()
    unmatched_or_ambiguous = []
    for y_idx, y in enumerate(y_schools):
        if y_idx in matched_by_y:
            status_counts["matched"] += 1
            continue
        if y_idx in ambiguous_y:
            status = "ambiguous"
            reason = ambiguous_y[y_idx]
        else:
            diag = diagnostics[y_idx]
            status = "unmatched"
            reason = diag.get("reason") or "not selected"
        status_counts[status] += 1
        diag = diagnostics[y_idx]
        best = diag.get("best")
        if best and best.get("school_index") is not None:
            school = schools[best["school_index"]]
            best = {
                **best,
                "udise_code": school.get("udise_code"),
                "udise_name": (school.get("metadata") or {}).get("school_name"),
                "udise_pincode": (school.get("metadata") or {}).get("reported_pincode"),
            }
        unmatched_or_ambiguous.append(
            {
                "status": status,
                "reason": reason,
                "yellowslate": {
                    "school_name": y.get("school_name"),
                    "school_url": y.get("school_url"),
                    "area": y.get("area"),
                    "board": y.get("board_text"),
                    "school_location": y.get("school_location") or {},
                    "fee": y.get("fee") or {},
                },
                "best_candidate": best,
            }
        )

    method_counts = Counter(edge["method"] for edge in selected)
    pricing_counts = Counter(
        school.get("yellowslate_fee", {}).get("pricing_band_key")
        for school in schools
        if school.get("yellowslate_fee")
    )
    y_with_location = sum(bool((y.get("school_location") or {}).get("address")) for y in y_schools)
    y_with_pincode = sum(bool((y.get("school_location") or {}).get("pincode")) for y in y_schools)
    matched_with_location = sum(
        bool((y_schools[edge["yellowslate_index"]].get("school_location") or {}).get("address"))
        for edge in selected
    )
    matched_without_location = len(selected) - matched_with_location

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "udise_schools": len(schools),
        "yellowslate_unique_schools": len(y_schools),
        "yellowslate_with_location": y_with_location,
        "yellowslate_with_pincode": y_with_pincode,
        "matched_schools": status_counts["matched"],
        "matched_from_yellowslate_with_location": matched_with_location,
        "matched_from_yellowslate_without_location": matched_without_location,
        "match_coverage_of_udise_percent": round(status_counts["matched"] * 100 / len(schools), 2),
        "match_coverage_of_yellowslate_percent": round(status_counts["matched"] * 100 / len(y_schools), 2),
        "matched_students": matched_students,
        "total_students": school_doc["summary"]["students"],
        "matched_student_coverage_percent": round(matched_students * 100 / school_doc["summary"]["students"], 2),
        "unmatched_yellowslate_schools": status_counts["unmatched"],
        "ambiguous_yellowslate_schools": status_counts["ambiguous"],
        "match_methods": dict(method_counts.most_common()),
        "pricing_band_counts": {k: pricing_counts.get(k, 0) for k in sorted(BRACKET_RANK, key=BRACKET_RANK.get)},
    }

    out_doc = copy.deepcopy(school_doc)
    out_doc["schools"] = schools
    out_doc["generated_at"] = report["generated_at"]
    out_doc["yellowslate_fee_coverage"] = report
    OUTPUT.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    AUDIT.write_text(
        json.dumps(
            {
                "report": report,
                "matches": audit_matches,
                "unmatched_or_ambiguous": unmatched_or_ambiguous,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
