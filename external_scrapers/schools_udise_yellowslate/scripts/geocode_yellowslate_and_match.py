#!/usr/bin/env python3
"""Geocode YellowSlate locations with Nominatim and match to cleaned UDISE coords.

Inputs:
  data/output/schools_analysis_bangalore_cleaned.json
  data/output/yellowslate/yellowslate_schools_with_locations.json

Outputs:
  data/output/yellowslate/yellowslate_nominatim_geocoded.json
  data/output/yellowslate/yellowslate_nominatim_geocode_cache.json
  data/output/schools_analysis_bangalore_cleaned_with_yellowslate_geo_fees.json
  data/output/yellowslate/yellowslate_udise_geo_match_report.json
  data/output/yellowslate/yellowslate_udise_geo_match_audit.json

The geocoder is intentionally conservative and cached. It sends at most one
Nominatim request per second and reuses cached results on reruns.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
UDISE_INPUT = ROOT / "data/output/schools_analysis_bangalore_cleaned.json"
YELLOWSLATE_INPUT = ROOT / "data/output/yellowslate/yellowslate_schools_with_locations.json"
CACHE_PATH = ROOT / "data/output/yellowslate/yellowslate_nominatim_geocode_cache.json"
GEOCODED_OUTPUT = ROOT / "data/output/yellowslate/yellowslate_nominatim_geocoded.json"
OUTPUT = ROOT / "data/output/schools_analysis_bangalore_cleaned_with_yellowslate_geo_fees.json"
REPORT = ROOT / "data/output/yellowslate/yellowslate_udise_geo_match_report.json"
AUDIT = ROOT / "data/output/yellowslate/yellowslate_udise_geo_match_audit.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "school-extraction-research/1.0 (local matching; contact: local-user)"

GENERIC = {
    "school", "public", "english", "medium", "high", "higher", "primary", "secondary",
    "academy", "international", "education", "educational", "institution", "institutions",
    "vidyalaya", "vidya", "mandir", "the", "of", "and", "bangalore", "bengaluru",
    "kannada", "convent", "nursery", "lps", "hps", "hs", "eps", "college", "pu",
    "pre", "preschool", "kids", "kidzee", "little", "st", "sri", "shree", "new",
    "matric", "centre", "center", "learning", "residential", "global", "national",
    "state", "board",
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
    raw_tokens = re.findall(r"[a-z0-9]+", text)
    expanded: list[str] = []
    for token in raw_tokens:
        repl = REPLACEMENTS.get(token)
        expanded.extend(repl.split() if repl else [token])
    return " ".join(expanded)


def tokens(value: Any, *, keep_generic: bool = False) -> set[str]:
    words = normalize(value).split()
    if keep_generic:
        return {x for x in words if len(x) > 1}
    return {x for x in words if x not in GENERIC and len(x) > 1}


def name_similarity(left: Any, right: Any) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    token_sort = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()
    ta, tb = tokens(left), tokens(right)
    overlap = len(ta & tb) / max(1, len(ta | tb))
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(sequence, token_sort, 0.72 * containment + 0.28 * overlap)


def token_jaccard(left: Any, right: Any, *, keep_generic: bool = False) -> float:
    a, b = tokens(left, keep_generic=keep_generic), tokens(right, keep_generic=keep_generic)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def clean_pincode(value: Any) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b([1-9]\d{5})\b", str(value))
    return match.group(1) if match else None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distance_score(distance_km: float | None, source: str | None) -> float:
    if distance_km is None:
        return 0.0
    # Foursquare-derived UDISE coordinates are stronger than pincode centroids.
    if source == "foursquare":
        if distance_km <= 0.15:
            return 1.0
        if distance_km <= 0.5:
            return 0.9
        if distance_km <= 1.0:
            return 0.72
        if distance_km <= 2.0:
            return 0.45
        return 0.0
    if distance_km <= 0.5:
        return 0.95
    if distance_km <= 1.5:
        return 0.82
    if distance_km <= 3.0:
        return 0.66
    if distance_km <= 5.0:
        return 0.44
    if distance_km <= 8.0:
        return 0.2
    return 0.0


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
    boards |= board_tokens(dims.get("board_group"))
    boards |= board_tokens((school.get("board_classification") or {}).get("board_group"))
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


def y_location_text(y: dict[str, Any]) -> str:
    loc = y.get("school_location") or {}
    return " ".join(str(x or "") for x in (y.get("area"), loc.get("address"), loc.get("pincode")))


def geocode_query(y: dict[str, Any]) -> str | None:
    loc = y.get("school_location") or {}
    address = loc.get("address")
    if not address:
        return None
    # Avoid overloading the query with both duplicated country names and page chrome.
    address = re.sub(r"\s+", " ", str(address)).strip(" ,")
    if "india" not in address.lower():
        address = f"{address}, India"
    return address


def load_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")


def geocode_nominatim(query: str, timeout: int = 25) -> dict[str, Any]:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": "1",
        "countrycodes": "in",
        "addressdetails": "1",
    }
    url = f"{NOMINATIM_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - keep the error in the cache/report.
        return {"status": "error", "error": str(exc), "query": query}
    if not payload:
        return {"status": "not_found", "query": query}
    top = payload[0]
    return {
        "status": "ok",
        "query": query,
        "lat": float(top["lat"]),
        "lon": float(top["lon"]),
        "display_name": top.get("display_name"),
        "osm_type": top.get("osm_type"),
        "osm_id": top.get("osm_id"),
        "class": top.get("category") or top.get("class"),
        "type": top.get("type"),
        "importance": top.get("importance"),
        "boundingbox": top.get("boundingbox"),
    }


def geocode_yellowslate(y_schools: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    cache = load_cache()
    out = []
    last_request = 0.0
    geocodeable = [y for y in y_schools if geocode_query(y)]
    done = 0
    for idx, y in enumerate(y_schools, start=1):
        item = copy.deepcopy(y)
        query = geocode_query(y)
        result = None
        if query:
            cached = cache.get(query)
            retryable_cached_error = cached and cached.get("status") in {"error", "skipped"}
            if cached and (args.no_geocode or not retryable_cached_error):
                result = cache[query]
            elif not args.no_geocode:
                if args.max_geocode and done >= args.max_geocode:
                    result = {"status": "skipped", "query": query, "error": "max_geocode reached"}
                else:
                    elapsed = time.time() - last_request
                    if elapsed < args.delay:
                        time.sleep(args.delay - elapsed)
                    result = geocode_nominatim(query, timeout=args.timeout)
                    last_request = time.time()
                    cache[query] = result
                    done += 1
                    if done % args.save_every == 0:
                        save_cache(cache)
                    print(f"[{idx}/{len(y_schools)}] geocode {result.get('status')} {query[:100]}", flush=True)
            else:
                result = {"status": "skipped", "query": query, "error": "no_geocode enabled"}
        else:
            result = {"status": "no_address", "query": None}
        item["nominatim_geocode"] = result
        out.append(item)
    save_cache(cache)
    GEOCODED_OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"Geocoded/cached addresses: {len(cache)} / geocodeable YellowSlate records: {len(geocodeable)}", flush=True)
    return out


def prepare_udise(schools: list[dict[str, Any]]) -> dict[str, Any]:
    token_index: dict[str, set[int]] = defaultdict(set)
    pincode_index: dict[str, set[int]] = defaultdict(set)
    records = []
    for idx, school in enumerate(schools):
        meta = school.get("metadata") or {}
        loc = meta.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        name = meta.get("school_name")
        rec = {
            "name": name,
            "name_tokens": tokens(name),
            "location_text": school_location_text(school),
            "location_tokens": tokens(school_location_text(school), keep_generic=True),
            "boards": school_board_tokens(school),
            "lat": float(lat) if lat is not None else None,
            "lon": float(lon) if lon is not None else None,
            "coordinate_source": loc.get("coordinate_source"),
            "pins": {
                clean_pincode(meta.get("reported_pincode")),
                clean_pincode(meta.get("searched_pincode")),
            }
            - {None},
        }
        records.append(rec)
        for token in rec["name_tokens"]:
            token_index[token].add(idx)
        for pin in rec["pins"]:
            pincode_index[pin].add(idx)
    return {"records": records, "token_index": token_index, "pincode_index": pincode_index}


def candidate_indexes(y: dict[str, Any], bundle: dict[str, Any]) -> set[int]:
    records = bundle["records"]
    token_index = bundle["token_index"]
    pincode_index = bundle["pincode_index"]
    geocode = y.get("nominatim_geocode") or {}
    y_lat, y_lon = geocode.get("lat"), geocode.get("lon")
    y_pin = (y.get("school_location") or {}).get("pincode")
    candidates: set[int] = set()

    if y_pin:
        candidates |= pincode_index.get(y_pin, set())

    if y_lat is not None and y_lon is not None:
        for idx, rec in enumerate(records):
            if rec["lat"] is None or rec["lon"] is None:
                continue
            dist = haversine_km(float(y_lat), float(y_lon), rec["lat"], rec["lon"])
            if dist <= 6.0:
                candidates.add(idx)

    token_hits = [(token, token_index.get(token, set())) for token in tokens(y.get("school_name"))]
    token_hits = [(token, hits) for token, hits in token_hits if hits]
    token_hits.sort(key=lambda item: len(item[1]))
    for _, hits in token_hits[:5]:
        if len(hits) <= 1000:
            candidates |= hits
    if not candidates and token_hits:
        for _, hits in token_hits[:2]:
            candidates |= set(list(hits)[:800])
    return candidates


def evaluate(y: dict[str, Any], school: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    geocode = y.get("nominatim_geocode") or {}
    y_lat, y_lon = geocode.get("lat"), geocode.get("lon")
    distance = None
    if y_lat is not None and y_lon is not None and rec["lat"] is not None and rec["lon"] is not None:
        distance = haversine_km(float(y_lat), float(y_lon), rec["lat"], rec["lon"])
    dist_score = distance_score(distance, rec["coordinate_source"])
    y_pin = (y.get("school_location") or {}).get("pincode")
    pincode_match = bool(y_pin and y_pin in rec["pins"])
    pincode_conflict = bool(y_pin and rec["pins"] and not pincode_match)
    name_score = name_similarity(y.get("school_name"), rec["name"])
    area_score = max(
        name_similarity(y.get("area"), rec["location_text"]) if y.get("area") else 0.0,
        token_jaccard(y_location_text(y), rec["location_text"], keep_generic=True),
    )
    y_boards = board_tokens(y.get("board_text"))
    board_match = bool(y_boards and rec["boards"] and y_boards & rec["boards"])
    board_conflict = bool(y_boards and rec["boards"] and not (y_boards & rec["boards"]))
    shared = tokens(y.get("school_name")) & rec["name_tokens"]
    shared_count = len(shared)
    has_geo = geocode.get("status") == "ok"

    score = (
        0.42 * dist_score
        + 0.36 * name_score
        + 0.10 * int(pincode_match)
        + 0.06 * area_score
        + 0.04 * int(board_match)
        + 0.02 * min(1.0, shared_count / 2)
    )

    acceptable = False
    method = None
    if has_geo:
        if distance is not None and distance <= 0.35 and name_score >= 0.70 and shared_count >= 1:
            acceptable, method = True, "geo_near+name"
        elif distance is not None and distance <= 1.5 and name_score >= 0.82 and shared_count >= 1:
            acceptable, method = True, "geo_close+name"
        elif distance is not None and distance <= 4.0 and pincode_match and name_score >= 0.76 and shared_count >= 1:
            acceptable, method = True, "geo+pincode+name"
        elif distance is not None and distance <= 4.0 and name_score >= 0.84 and area_score >= 0.25 and shared_count >= 2:
            acceptable, method = True, "geo+name+area"
        elif distance is not None and distance <= 5.5 and pincode_match and name_score >= 0.72 and board_match and shared_count >= 1:
            acceptable, method = True, "geo+pincode+name+board"
    else:
        # Fallback for YellowSlate records with no geocoded address.
        if name_score >= 0.95:
            acceptable, method = True, "fallback:name_strong"
        elif name_score >= 0.90 and area_score >= 0.30 and shared_count >= 2:
            acceptable, method = True, "fallback:name+area"
        elif name_score >= 0.88 and area_score >= 0.25 and board_match and shared_count >= 2:
            acceptable, method = True, "fallback:name+area+board"

    if board_conflict and not pincode_match and name_score < 0.93:
        acceptable = False
        method = None
    if pincode_conflict and not pincode_match and shared_count < 2:
        acceptable = False
        method = None

    return {
        "score": score,
        "acceptable": acceptable,
        "method": method,
        "distance_km": distance,
        "distance_score": dist_score,
        "udise_coordinate_source": rec["coordinate_source"],
        "name_similarity": name_score,
        "area_similarity": area_score,
        "pincode_match": pincode_match,
        "pincode_conflict": pincode_conflict,
        "board_match": board_match,
        "board_conflict": board_conflict,
        "shared_distinctive_tokens": sorted(shared),
        "has_yellowslate_geocode": has_geo,
    }


def compact_edge(edge: dict[str, Any] | None) -> dict[str, Any] | None:
    if not edge:
        return None
    return {
        "school_index": edge["school_index"],
        "score": round(edge["score"], 4),
        "method": edge.get("method"),
        "distance_km": round(edge["distance_km"], 4) if edge.get("distance_km") is not None else None,
        "distance_score": round(edge["distance_score"], 4),
        "udise_coordinate_source": edge["udise_coordinate_source"],
        "name_similarity": round(edge["name_similarity"], 4),
        "area_similarity": round(edge["area_similarity"], 4),
        "pincode_match": edge["pincode_match"],
        "pincode_conflict": edge["pincode_conflict"],
        "board_match": edge["board_match"],
        "board_conflict": edge["board_conflict"],
        "shared_distinctive_tokens": edge["shared_distinctive_tokens"],
        "runner_up_delta": round(edge["runner_up_delta"], 4) if edge.get("runner_up_delta") is not None else None,
    }


def build_edges(y_schools: list[dict[str, Any]], schools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bundle = prepare_udise(schools)
    records = bundle["records"]
    edges = []
    diagnostics = []
    for y_idx, y in enumerate(y_schools):
        ranked = []
        for school_idx in candidate_indexes(y, bundle):
            metrics = evaluate(y, schools[school_idx], records[school_idx])
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
            diagnostics.append({"yellowslate_index": y_idx, "status": "no_candidate", "candidate_count": 0})
    return edges, diagnostics


def select_one_to_one(edges: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, str]]:
    by_y: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        by_y[edge["yellowslate_index"]].append(edge)
    eligible = []
    ambiguous_y: dict[int, str] = {}
    for y_idx, y_edges in by_y.items():
        y_edges.sort(key=lambda item: item["score"], reverse=True)
        best = y_edges[0]
        runner = y_edges[1] if len(y_edges) > 1 else None
        gap = 0.035 if best["has_yellowslate_geocode"] else 0.045
        if runner and best["score"] - runner["score"] < gap:
            ambiguous_y[y_idx] = "close competing UDISE candidates"
        else:
            eligible.append(best)

    eligible.sort(key=lambda item: item["score"], reverse=True)
    selected = []
    used_y: set[int] = set()
    used_school: set[int] = set()
    for edge in eligible:
        y_idx, school_idx = edge["yellowslate_index"], edge["school_index"]
        if y_idx in used_y:
            continue
        if school_idx in used_school:
            ambiguous_y[y_idx] = "UDISE target already claimed by stronger YellowSlate match"
            continue
        selected.append(edge)
        used_y.add(y_idx)
        used_school.add(school_idx)
    return selected, ambiguous_y


def pricing_band(fee: dict[str, Any]) -> dict[str, Any]:
    key = fee.get("assigned_bracket_key")
    label = fee.get("assigned_bracket_label")
    return {"pricing_band_key": key, "pricing_band_name": label, "pricing_band_rank": BRACKET_RANK.get(key)}


def fee_payload(y: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    fee = y.get("fee") or {}
    band = pricing_band(fee)
    loc = y.get("school_location") or {}
    geocode = y.get("nominatim_geocode") or {}
    return {
        "source": "YellowSlate",
        "school_name": y.get("school_name"),
        "school_url": y.get("school_url"),
        "board": y.get("board_text"),
        "area": y.get("area"),
        "location": {
            "address": loc.get("address"),
            "pincode": loc.get("pincode"),
            "nominatim": geocode,
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
        "match": {k: v for k, v in compact_edge(edge).items() if k != "school_index"},
    }


def run_match(udise_doc: dict[str, Any], y_schools: list[dict[str, Any]]) -> dict[str, Any]:
    schools = copy.deepcopy(udise_doc["schools"])
    edges, diagnostics = build_edges(y_schools, schools)
    selected, ambiguous_y = select_one_to_one(edges)
    matched_by_y = {e["yellowslate_index"]: e for e in selected}
    matched_students = 0
    audit_matches = []
    for edge in selected:
        y = y_schools[edge["yellowslate_index"]]
        school = schools[edge["school_index"]]
        school["yellowslate_fee"] = fee_payload(y, edge)
        matched_students += int((school.get("enrollment") or {}).get("total_students") or 0)
        audit_matches.append(
            {
                "udise_code": school.get("udise_code"),
                "udise_name": (school.get("metadata") or {}).get("school_name"),
                "udise_pincode": (school.get("metadata") or {}).get("reported_pincode"),
                "udise_location": (school.get("metadata") or {}).get("location"),
                "yellowslate_name": y.get("school_name"),
                "yellowslate_url": y.get("school_url"),
                "yellowslate_board": y.get("board_text"),
                "yellowslate_location": y.get("school_location") or {},
                "yellowslate_geocode": y.get("nominatim_geocode") or {},
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
            status, reason = "ambiguous", ambiguous_y[y_idx]
        else:
            status, reason = "unmatched", "no candidate passed thresholds"
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
                    "nominatim_geocode": y.get("nominatim_geocode") or {},
                    "fee": y.get("fee") or {},
                },
                "best_candidate": best,
            }
        )

    method_counts = Counter(e["method"] for e in selected)
    pricing_counts = Counter(
        s.get("yellowslate_fee", {}).get("pricing_band_key") for s in schools if s.get("yellowslate_fee")
    )
    geocode_counts = Counter((y.get("nominatim_geocode") or {}).get("status") or "missing" for y in y_schools)
    matched_geo = sum((y_schools[e["yellowslate_index"]].get("nominatim_geocode") or {}).get("status") == "ok" for e in selected)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "udise_schools": len(schools),
        "yellowslate_unique_schools": len(y_schools),
        "nominatim_status_counts": dict(geocode_counts.most_common()),
        "matched_schools": status_counts["matched"],
        "matched_from_geocoded_yellowslate": matched_geo,
        "match_coverage_of_udise_percent": round(status_counts["matched"] * 100 / len(schools), 2),
        "match_coverage_of_yellowslate_percent": round(status_counts["matched"] * 100 / len(y_schools), 2),
        "matched_students": matched_students,
        "total_students": udise_doc["summary"]["students"],
        "matched_student_coverage_percent": round(matched_students * 100 / udise_doc["summary"]["students"], 2),
        "unmatched_yellowslate_schools": status_counts["unmatched"],
        "ambiguous_yellowslate_schools": status_counts["ambiguous"],
        "match_methods": dict(method_counts.most_common()),
        "pricing_band_counts": {k: pricing_counts.get(k, 0) for k in sorted(BRACKET_RANK, key=BRACKET_RANK.get)},
    }
    out_doc = copy.deepcopy(udise_doc)
    out_doc["schools"] = schools
    out_doc["generated_at"] = report["generated_at"]
    out_doc["yellowslate_geo_fee_coverage"] = report
    OUTPUT.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    AUDIT.write_text(json.dumps({"report": report, "matches": audit_matches, "unmatched_or_ambiguous": unmatched_or_ambiguous}, ensure_ascii=False, indent=2) + "\n")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=1.1, help="Delay between Nominatim requests.")
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--save-every", type=int, default=25)
    parser.add_argument("--max-geocode", type=int, default=None, help="Limit new geocoding requests for testing.")
    parser.add_argument("--no-geocode", action="store_true", help="Use cache only; do not call Nominatim.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    udise_doc = json.loads(UDISE_INPUT.read_text())
    y_schools = json.loads(YELLOWSLATE_INPUT.read_text())
    y_geocoded = geocode_yellowslate(y_schools, args)
    report = run_match(udise_doc, y_geocoded)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
