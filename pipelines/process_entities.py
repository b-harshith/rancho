#!/usr/bin/env python3
"""
process_entities.py
───────────────────
Unified JSON/JSONL → CSV processing pipeline for:
  • Localities  → real_estate_localities_and_societies.csv  (same schema as Societies)
  • Offices     → offices_unified_all_cities.csv
  • Hospitals   → hospitals_unified_all_cities.csv  (ready; runs when data exists)

Usage:
  python3 pipelines/process_entities.py --entity localities
  python3 pipelines/process_entities.py --entity offices
  python3 pipelines/process_entities.py --entity hospitals
  python3 pipelines/process_entities.py --entity all          # run all three
  python3 pipelines/process_entities.py --entity all --dry-run

Design notes:
  - All ranking & quartile logic is centralised in assign_ranking().
  - Each entity has its own loader + field-normaliser; output is a flat dict
    matching the declared schema before ranking is applied.
  - pandas is used only for final sort / CSV serialisation so that the heavy
    per-record logic stays in plain Python (matching the style of merge.py /
    run_pipeline.py in this project).
  - Missing source files are warned about (not fatal) so the script remains
    runnable as more cities come online.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
#  Project Root & Output Paths
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]   # .../web_platform_vercel_exact_latest
DATA_DIR   = ROOT / "DATA"
SRC_DIR    = ROOT / "src" / "public" / "data"
OUTPUT_DIR = ROOT / "pipelines" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FOURSQUARE_DIR = ROOT / "external_scrapers" / "foursquare_offices"
HOSPITAL_DIR   = ROOT / "external_scrapers" / "school_data_legacy"

# ─────────────────────────────────────────────────────────────────────────────
#  City Registry
# ─────────────────────────────────────────────────────────────────────────────

# Canonical city IDs used throughout; order determines processing priority.
CITIES = [
    "bangalore",
    "delhi_ncr",
    "mumbai",
    "hyderabad",
    "chennai",
    "kolkata",
    "pune",
]

# Human-readable display labels for log messages.
CITY_LABELS: dict[str, str] = {
    "bangalore": "Bangalore",
    "delhi_ncr": "Delhi NCR",
    "mumbai":    "Mumbai",
    "hyderabad": "Hyderabad",
    "chennai":   "Chennai",
    "kolkata":   "Kolkata",
    "pune":      "Pune",
}

# ─────────────────────────────────────────────────────────────────────────────
#  Shared Utility Functions
# ─────────────────────────────────────────────────────────────────────────────

# Stop-words stripped during name normalisation (matches pipelines/schools/merge.py)
_NORM_STOP = {
    "the", "of", "and", "at", "in", "by", "a", "an",
    "india", "private", "limited", "ltd", "pvt",
}


def normalize_name(value: str | None) -> str:
    """
    Unicode-safe slug: NFKD -> ASCII -> lowercase -> alphanumeric tokens
    joined by spaces, stop-words removed.  Mirrors normalized_name() in
    pipelines/schools/merge.py so cross-entity deduplication stays consistent.
    """
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    return " ".join(t for t in tokens if t not in _NORM_STOP)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance in km.
    Same formula as in pipelines/schools/merge.py and foursquare/match_societies.py.
    """
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def latlon_to_h3(lat: float | None, lon: float | None, resolution: int = 7) -> str | None:
    """
    Convert lat/lon to H3 cell ID at the given resolution.
    Returns None when h3-py is not installed or coordinates are missing.
    """
    if lat is None or lon is None:
        return None
    try:
        import h3
        return h3.latlng_to_cell(lat, lon, resolution)
    except Exception:
        return None


def safe_float(value: Any) -> float | None:
    """Coerce a value to float, returning None on failure or non-finite result."""
    if value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    """Coerce a value to int via safe_float, returning None on failure."""
    f = safe_float(value)
    return int(f) if f is not None else None


def extract_pincode(text: str | None) -> str | None:
    """
    Pull a 6-digit Indian pincode from an address string.
    Matches the regex pattern used in schools/merge.py _pincode().
    """
    if not text:
        return None
    m = re.search(r"\b[1-9][0-9]{5}\b", str(text))
    return m.group(0) if m else None


def compute_data_completeness(record: dict, required_fields: list[str]) -> float:
    """
    Fraction of required_fields that are non-null and non-empty.
    Returns a value in [0.0, 1.0] rounded to 4 decimal places.
    """
    if not required_fields:
        return 1.0
    filled = sum(
        1 for f in required_fields
        if record.get(f) not in (None, "", "NA", "null")
    )
    return round(filled / len(required_fields), 4)


def stable_entity_id(prefix: str, *parts: Any) -> str:
    """
    Deterministic entity ID: SHA-256 of <prefix>:<part1>:<part2>:...
    Truncated to 16 hex chars to keep CSVs readable.
    Stable across runs given the same inputs.
    """
    payload = ":".join(str(p) for p in (prefix, *parts)).casefold()
    return prefix + "_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_jsonl(path: Path) -> list[dict]:
    """Read a newline-delimited JSON file; skip blank and malformed lines."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                print(f"  [WARN] {path.name}:{lineno} - JSON parse error: {exc}", file=sys.stderr)
    return records


def load_json(path: Path) -> Any:
    """Read a regular JSON file."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────────────────────
#  Universal Ranking & Quartile Assignment
#
#  Spec: Q4 (top 25%), Q3, Q2, Q1 (bottom 25%).
#        Q4 is further split into:
#          Q4-Sub-Q4  (Ultra Premium)
#          Q4-Sub-Q3  (Super Premium)
#          Q4-Sub-Q2  (Premium)
#          Q4-Sub-Q1  (Upper-Mid Premium)
#        All quartiles are computed WITHIN each city independently.
# ─────────────────────────────────────────────────────────────────────────────

_Q4_SUB_SEGMENTS: dict[str, str] = {
    "Q4-Sub-Q4": "Ultra Premium",
    "Q4-Sub-Q3": "Super Premium",
    "Q4-Sub-Q2": "Premium",
    "Q4-Sub-Q1": "Upper-Mid Premium",
}


def _linear_percentile(sorted_values: list[float], p: float) -> float:
    """
    Linear-interpolation percentile identical to numpy.percentile default.
    sorted_values must already be sorted ascending.
    """
    n = len(sorted_values)
    if n == 0:
        return 0.0
    pos = p / 100.0 * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    return sorted_values[lo] + (pos - lo) * (sorted_values[hi] - sorted_values[lo])


def assign_ranking(
    records: list[dict],
    score_field: str,
    city_field: str = "city",
) -> list[dict]:
    """
    Mutate each record in-place, adding:
      city_rank        - ordinal rank within city (1 = best)
      quartile         - Q1 / Q2 / Q3 / Q4
      q4_subquartile   - Q4-Sub-Q1 ... Q4-Sub-Q4 (None for non-Q4 records)
      segment          - human-readable label

    Records with no (or non-finite) score receive city_rank=None,
    quartile=None, segment="Unranked".
    """
    # Group record indices by city
    city_groups: dict[str, list[int]] = {}
    for idx, rec in enumerate(records):
        city_groups.setdefault(rec.get(city_field, "unknown"), []).append(idx)

    for city, indices in city_groups.items():
        # Partition into scoreable vs unscoreable
        valid: list[tuple[int, float]] = []
        for i in indices:
            s = records[i].get(score_field)
            try:
                fval = float(s)
                if math.isfinite(fval):
                    valid.append((i, fval))
                    continue
            except (TypeError, ValueError):
                pass
            # No valid score
            records[i].update({
                "city_rank":      None,
                "quartile":       None,
                "q4_subquartile": None,
                "segment":        "Unranked",
            })

        if not valid:
            continue

        # Assign city_rank (descending: highest score = rank 1)
        valid_sorted = sorted(valid, key=lambda x: x[1], reverse=True)
        for rank, (idx, _) in enumerate(valid_sorted, 1):
            records[idx]["city_rank"] = rank

        # Compute global quartile boundaries from sorted scores
        scores_sorted = sorted(s for _, s in valid)
        p25 = _linear_percentile(scores_sorted, 25)
        p50 = _linear_percentile(scores_sorted, 50)
        p75 = _linear_percentile(scores_sorted, 75)

        # Compute Q4 sub-quartile boundaries from scores in Q4 only
        q4_scores_sorted = sorted(s for s in scores_sorted if s >= p75)
        if len(q4_scores_sorted) > 1:
            q4_p25 = _linear_percentile(q4_scores_sorted, 25)
            q4_p50 = _linear_percentile(q4_scores_sorted, 50)
            q4_p75 = _linear_percentile(q4_scores_sorted, 75)
        else:
            # Only 1 Q4 record -> assign top sub-quartile
            q4_p25 = q4_p50 = q4_p75 = p75

        for i, score in valid:
            if score >= p75:
                q = "Q4"
                if score >= q4_p75:
                    sub = "Q4-Sub-Q4"
                elif score >= q4_p50:
                    sub = "Q4-Sub-Q3"
                elif score >= q4_p25:
                    sub = "Q4-Sub-Q2"
                else:
                    sub = "Q4-Sub-Q1"
                seg = _Q4_SUB_SEGMENTS[sub]
            elif score >= p50:
                q, sub, seg = "Q3", None, "Premium"
            elif score >= p25:
                q, sub, seg = "Q2", None, "Mid-Market"
            else:
                q, sub, seg = "Q1", None, "Economy"

            records[i].update({
                "quartile":       q,
                "q4_subquartile": sub,
                "segment":        seg,
            })

    return records


def _minmax_normalise(values: list[float]) -> list[float]:
    """
    Min-max normalise a list of floats to [0, 1].
    Returns 0.5 for all values when the range is zero.
    """
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# ─────────────────────────────────────────────────────────────────────────────
#  ENTITY 1 – LOCALITIES
#  Target CSV: real_estate_localities_and_societies.csv
#  entity_type field = "locality"  (shares schema with Societies)
#
#  Sources:
#    Bangalore : src/public/data/localities.json  (99acres-derived)
#    Others    : DATA/multicity/<city>/magicbricks_localities/checkpoints/details.json
#
#  Ranking metric (composite ranking_score):
#    55%  price_per_sqft_avg   (primary)
#    15%  listing count proxy  (data_completeness when explicit count unavailable)
#    12%  reviews count
#    10%  rating
#     8%  coordinate_confidence * data_completeness
# ─────────────────────────────────────────────────────────────────────────────

_LOC_W_PRICE    = 0.55
_LOC_W_LISTINGS = 0.15
_LOC_W_REVIEWS  = 0.12
_LOC_W_RATING   = 0.10
_LOC_W_CONF     = 0.08

_LOC_REQUIRED = ["name", "city", "latitude", "longitude", "price_per_sqft_avg", "zone"]

LOCALITY_SCHEMA = [
    "entity_id", "entity_type", "name", "normalized_name", "city", "source",
    "locality", "address", "pincode", "latitude", "longitude",
    "google_place_id", "h3_res7", "zone",
    "price_per_sqft_min", "price_per_sqft_avg", "price_per_sqft_max",
    "min_property_price", "max_property_price",
    "developer", "project_type", "construction_status", "possession_year",
    "total_units", "source_entity_id", "source_url", "scraped_at",
    "coordinate_source", "coordinate_confidence", "data_completeness",
    "dedupe_status",
    "city_rank", "quartile", "q4_subquartile", "segment",
    "ranking_metric", "ranking_score",
]


def _loc_blank() -> dict:
    """Return a record pre-filled with schema keys -> None."""
    return {k: None for k in LOCALITY_SCHEMA}


def _loc_from_99acres_bangalore(raw: dict) -> dict:
    """
    Parse one record from src/public/data/localities.json (99acres Bangalore).
    Raw schema: { name, lat, lon, price_sqft, budget_segment, hex_id, zone }
    """
    rec = _loc_blank()
    name = raw.get("name") or ""
    lat  = safe_float(raw.get("lat"))
    lon  = safe_float(raw.get("lon"))

    rec["entity_type"]          = "locality"
    rec["name"]                 = name
    rec["normalized_name"]      = normalize_name(name)
    rec["city"]                 = "bangalore"
    rec["source"]               = "99acres"
    rec["locality"]             = name
    rec["latitude"]             = lat
    rec["longitude"]            = lon
    rec["h3_res7"]              = raw.get("hex_id") or latlon_to_h3(lat, lon)
    rec["zone"]                 = raw.get("zone")
    rec["price_per_sqft_avg"]   = safe_float(raw.get("price_sqft"))
    rec["coordinate_source"]    = "source_embedded"
    rec["coordinate_confidence"]= 0.85   # 99acres lat/lon are generally reliable
    rec["scraped_at"]           = None   # not available in this static export

    rec["data_completeness"] = compute_data_completeness(rec, _LOC_REQUIRED)
    rec["entity_id"]         = stable_entity_id("loc", "bangalore", normalize_name(name))
    rec["dedupe_status"]     = "canonical"
    # Private helpers for composite score (stripped before CSV export)
    rec["_rating"]   = None
    rec["_reviews"]  = 0
    return rec


def _loc_from_magicbricks(raw: dict, city: str) -> dict:
    """
    Parse one record from DATA/multicity/<city>/magicbricks_localities/checkpoints/details.json.
    Raw schema: { budget_segment, canonical_city_id, challenge, latitude, longitude,
                  link_key, name, page_url, price_per_sqft_avg, price_per_sqft_max,
                  price_per_sqft_min, rank, rating, reviews, source_city_id,
                  source_city_name, source_entity_id, source_url, title }
    """
    rec = _loc_blank()
    name = raw.get("name") or raw.get("title") or ""
    lat  = safe_float(raw.get("latitude"))
    lon  = safe_float(raw.get("longitude"))

    rec["entity_type"]           = "locality"
    rec["name"]                  = name
    rec["normalized_name"]       = normalize_name(name)
    rec["city"]                  = city
    rec["source"]                = "magicbricks"
    rec["locality"]              = name
    rec["latitude"]              = lat
    rec["longitude"]             = lon
    rec["h3_res7"]               = latlon_to_h3(lat, lon)
    rec["price_per_sqft_min"]    = safe_float(raw.get("price_per_sqft_min"))
    rec["price_per_sqft_avg"]    = safe_float(raw.get("price_per_sqft_avg"))
    rec["price_per_sqft_max"]    = safe_float(raw.get("price_per_sqft_max"))
    rec["source_entity_id"]      = str(raw.get("source_entity_id") or "")
    rec["source_url"]            = raw.get("source_url") or raw.get("link_key")
    rec["coordinate_source"]     = "source_embedded"
    rec["coordinate_confidence"] = 0.80
    rec["scraped_at"]            = None   # checkpoint file has no per-record timestamp

    # Private helpers for composite score (stripped before CSV export)
    rec["_rating"]  = safe_float(raw.get("rating"))
    rec["_reviews"] = safe_int(raw.get("reviews")) or 0

    rec["data_completeness"] = compute_data_completeness(rec, _LOC_REQUIRED)
    rec["entity_id"]         = stable_entity_id("loc", city, normalize_name(name))
    rec["dedupe_status"]     = "canonical"
    return rec


def _loc_compute_ranking_scores(records: list[dict]) -> list[dict]:
    """
    Compute ranking_score for every locality record using min-max normalised
    sub-scores blended by the weights defined above.  Operates per-city.
    """
    city_groups: dict[str, list[int]] = {}
    for i, r in enumerate(records):
        city_groups.setdefault(r["city"], []).append(i)

    for city, indices in city_groups.items():
        def col(field: str) -> list[float]:
            return [safe_float(records[i].get(field)) or 0.0 for i in indices]

        n_price   = _minmax_normalise(col("price_per_sqft_avg"))
        n_listing = _minmax_normalise(col("data_completeness"))   # proxy for listing count
        n_reviews = _minmax_normalise(col("_reviews"))
        n_ratings = _minmax_normalise(col("_rating"))
        n_conf    = _minmax_normalise([
            (safe_float(records[i].get("coordinate_confidence")) or 0.5)
            * (safe_float(records[i].get("data_completeness"))   or 0.5)
            for i in indices
        ])

        for j, idx in enumerate(indices):
            score = (
                _LOC_W_PRICE    * n_price[j]
                + _LOC_W_LISTINGS * n_listing[j]
                + _LOC_W_REVIEWS  * n_reviews[j]
                + _LOC_W_RATING   * n_ratings[j]
                + _LOC_W_CONF     * n_conf[j]
            )
            records[idx]["ranking_score"]  = round(score, 6)
            records[idx]["ranking_metric"] = "composite_price_reviews_rating_confidence"

    return records


def process_localities() -> pd.DataFrame:
    """
    Load all locality sources, normalise, deduplicate, rank, and return
    a DataFrame with LOCALITY_SCHEMA columns.
    """
    print("\n" + "=" * 60)
    print("PROCESSING: LOCALITIES")
    print("=" * 60)
    records: list[dict] = []

    # ── Bangalore: 99acres ────────────────────────────────────────────────────
    blr_path = SRC_DIR / "localities.json"
    if blr_path.exists():
        raw_blr = load_json(blr_path)
        if isinstance(raw_blr, list):
            blr_recs = [_loc_from_99acres_bangalore(r) for r in raw_blr]
            print(f"  [Bangalore / 99acres]    Loaded {len(blr_recs):>5} localities.")
            records.extend(blr_recs)
        else:
            print(f"  [WARN] {blr_path}: not a list, skipped.", file=sys.stderr)
    else:
        print(f"  [WARN] Not found: {blr_path}", file=sys.stderr)

    # ── Other cities: MagicBricks checkpoints ─────────────────────────────────
    for city in [c for c in CITIES if c != "bangalore"]:
        cp_path = (
            DATA_DIR / "multicity" / city
            / "magicbricks_localities" / "checkpoints" / "details.json"
        )
        if not cp_path.exists():
            print(f"  [WARN] Not found (skip): {cp_path}", file=sys.stderr)
            continue
        payload  = load_json(cp_path)
        raw_list = payload if isinstance(payload, list) else payload.get("records", [])
        city_recs = [_loc_from_magicbricks(r, city) for r in raw_list if isinstance(r, dict)]
        print(f"  [{CITY_LABELS[city]} / MagicBricks]{'':<5} Loaded {len(city_recs):>5} localities.")
        records.extend(city_recs)

    if not records:
        print("  [ERROR] No locality records loaded.", file=sys.stderr)
        return pd.DataFrame(columns=LOCALITY_SCHEMA)

    # ── Deduplication: normalised_name + city ─────────────────────────────────
    # Within a city, the 99acres file takes priority (loaded first).
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in records:
        key = f"{r['city']}|{r['normalized_name']}"
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    n_dupes = len(records) - len(deduped)
    if n_dupes:
        print(f"  Deduplicated {n_dupes} duplicate locality entries.")

    # ── Composite ranking score, then quartile assignment ─────────────────────
    deduped = _loc_compute_ranking_scores(deduped)
    deduped = assign_ranking(deduped, score_field="ranking_score", city_field="city")

    # Strip private helper columns before export
    for r in deduped:
        r.pop("_rating", None)
        r.pop("_reviews", None)

    df = pd.DataFrame(deduped, columns=LOCALITY_SCHEMA)
    df.sort_values(["city", "city_rank"], inplace=True, ignore_index=True)

    print(f"\n  Localities total: {len(df):,} records across {df['city'].nunique()} cities.")
    for city, grp in df.groupby("city"):
        print(f"     {CITY_LABELS.get(city, city):<15} {len(grp):>5} records")
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  ENTITY 2 – OFFICES
#  Target CSV: offices_unified_all_cities.csv
#
#  Sources: foursquare categories/<city>_office_listings.json  (all 7 cities)
#
#  Ranking metric: company_prominence_score  (Tiers 1-4 already encoded).
#  Score is computed from available Foursquare signals since the raw files
#  do not carry a pre-computed score field.
# ─────────────────────────────────────────────────────────────────────────────

# Canonical Foursquare file prefixes per city
_OFFICE_FILE_PREFIXES: dict[str, str] = {
    "bangalore": "bangalore",
    "delhi_ncr": "delhi_ncr",
    "mumbai":    "mumbai",
    "hyderabad": "hyderabad",
    "chennai":   "chennai",
    "kolkata":   "kolkata",
    "pune":      "pune",
}

# Foursquare category IDs representing offices / corporate spaces
_OFFICE_CAT_IDS = {
    "4bf58dd8d48988d124941735",  # Office
    "4d954af4a243a5684965b473",  # Corporate Office
    "4bf58dd8d48988d100941735",  # Tech Startup
    "56aa371be4b08b9a8d573541",  # Coworking Space
    "4bf58dd8d48988d174941735",  # Government Building
}

# Prominence score -> tier boundaries (descending check)
_PROMINENCE_TIERS = [
    (75.0, "Tier-1"),  # >= 75: Global / National Corp
    (50.0, "Tier-2"),  # >= 50: Large Enterprise
    (25.0, "Tier-3"),  # >= 25: Mid-Market
    (0.0,  "Tier-4"),  # <  25: SMB / Generic Office
]

_OFFICE_REQUIRED = ["name", "city", "latitude", "longitude", "address"]

OFFICE_SCHEMA = [
    "office_id", "name", "normalized_name", "city",
    "address", "locality", "region", "pincode",
    "latitude", "longitude", "h3_res7", "zone",
    "category_ids", "category_labels",
    "company_type_proxy", "company_prominence_score",
    "company_prominence_tier", "ranking_reasons",
    "website", "phone", "email", "social_links",
    "date_created", "date_refreshed", "date_closed", "is_active",
    "unresolved_flags", "data_completeness", "dedupe_status",
    "city_rank", "quartile", "q4_subquartile", "segment",
]


def _derive_company_type(category_labels: str | None) -> str:
    """
    Map Foursquare category label string to a broad company type bucket.
    E.g. "Business and Professional Services > Office" -> "Corporate Office"
    """
    if not category_labels:
        return "Unknown"
    cl = category_labels.lower()
    if "startup" in cl or "coworking" in cl:
        return "Startup / Coworking"
    if "government" in cl:
        return "Government Office"
    if "tech" in cl or "software" in cl:
        return "Technology"
    if "finance" in cl or "bank" in cl or "insurance" in cl:
        return "Finance / Banking"
    if "legal" in cl or "law" in cl:
        return "Legal / Law Firm"
    if "media" in cl or "broadcast" in cl:
        return "Media / Broadcasting"
    if "real estate" in cl:
        return "Real Estate"
    if "healthcare" in cl or "pharma" in cl:
        return "Healthcare / Pharma"
    if "manufacturing" in cl or "industrial" in cl:
        return "Manufacturing / Industrial"
    return "Corporate Office"


def _compute_prominence_score(raw: dict) -> tuple[float, list[str]]:
    """
    Compute company_prominence_score in [0, 100] from Foursquare record signals.

    Scoring breakdown:
      website present          : +20 pts
      verified phone present   : +10 pts
      email present            : +10 pts
      recency of date_refreshed: up to +20 pts (linear from 2015 to 2026)
      strong office category   : +15 pts
      no unresolved flags      : +10 pts
      social links (fb/ig/tw)  : +5 pts each, capped at +15 pts total
    Maximum possible = 100 pts.
    """
    score: float = 0.0
    reasons: list[str] = []

    if raw.get("website"):
        score += 20
        reasons.append("has_website")

    if raw.get("tel") or raw.get("phone"):
        score += 10
        reasons.append("has_phone")

    if raw.get("email"):
        score += 10
        reasons.append("has_email")

    # Recency bonus
    refreshed = raw.get("date_refreshed") or raw.get("date_created")
    if refreshed:
        try:
            yr = int(str(refreshed)[:4])
            recency = max(0.0, min(1.0, (yr - 2015) / (2026 - 2015)))
            score += recency * 20
            if recency > 0.5:
                reasons.append("recently_refreshed")
        except (ValueError, TypeError):
            pass

    # Category specificity bonus
    cat_ids_str = raw.get("fsq_category_ids") or ""
    cat_ids = {c.strip() for c in cat_ids_str.split(",") if c.strip()}
    if cat_ids & _OFFICE_CAT_IDS:
        score += 15
        reasons.append("strong_office_category")

    # No unresolved flags bonus
    flags = str(raw.get("unresolved_flags") or "").strip()
    if flags in ("", "0", "[]"):
        score += 10
        reasons.append("no_unresolved_flags")

    # Social links bonus
    social_count = sum(1 for k in ("facebook_id", "instagram", "twitter") if raw.get(k))
    social_bonus = min(social_count * 5, 15)
    if social_bonus:
        score += social_bonus
        reasons.append(f"social_links_{social_count}")

    return round(min(score, 100.0), 2), reasons


def _prominence_tier(score: float) -> str:
    for threshold, label in _PROMINENCE_TIERS:
        if score >= threshold:
            return label
    return "Tier-4"


def _office_from_raw(raw: dict, city: str) -> dict:
    """Normalise a single Foursquare office listing record into OFFICE_SCHEMA."""
    rec: dict = {k: None for k in OFFICE_SCHEMA}

    name       = raw.get("name") or ""
    lat        = safe_float(raw.get("latitude"))
    lon        = safe_float(raw.get("longitude"))
    cat_ids    = raw.get("fsq_category_ids")    or ""
    cat_labels = raw.get("fsq_category_labels") or ""

    prom_score, reasons = _compute_prominence_score(raw)

    # Pack social links into a pipe-separated string (CSV-safe)
    social_parts = []
    for key, platform in (("facebook_id", "fb"), ("instagram", "ig"), ("twitter", "tw")):
        val = raw.get(key)
        if val:
            social_parts.append(f"{platform}:{val}")

    date_closed = raw.get("date_closed")
    is_active = date_closed is None or str(date_closed).strip() in ("", "null", "None")

    rec["office_id"]                = stable_entity_id(
                                         "off", city,
                                         raw.get("fsq_place_id") or normalize_name(name)
                                      )
    rec["name"]                     = name
    rec["normalized_name"]          = normalize_name(name)
    rec["city"]                     = city
    rec["address"]                  = raw.get("address")
    rec["locality"]                 = raw.get("locality")
    rec["region"]                   = raw.get("region") or raw.get("admin_region")
    rec["pincode"]                  = raw.get("postcode") or extract_pincode(raw.get("address"))
    rec["latitude"]                 = lat
    rec["longitude"]                = lon
    rec["h3_res7"]                  = latlon_to_h3(lat, lon)
    rec["zone"]                     = None   # Foursquare source has no zone; join later
    rec["category_ids"]             = cat_ids
    rec["category_labels"]          = cat_labels
    rec["company_type_proxy"]       = _derive_company_type(cat_labels)
    rec["company_prominence_score"] = prom_score
    rec["company_prominence_tier"]  = _prominence_tier(prom_score)
    rec["ranking_reasons"]          = "; ".join(reasons)
    rec["website"]                  = raw.get("website")
    rec["phone"]                    = raw.get("tel")
    rec["email"]                    = raw.get("email")
    rec["social_links"]             = " | ".join(social_parts) if social_parts else None
    rec["date_created"]             = raw.get("date_created")
    rec["date_refreshed"]           = raw.get("date_refreshed")
    rec["date_closed"]              = date_closed
    rec["is_active"]                = is_active
    rec["unresolved_flags"]         = raw.get("unresolved_flags")
    rec["data_completeness"]        = compute_data_completeness(rec, _OFFICE_REQUIRED)
    rec["dedupe_status"]            = "canonical"
    return rec


def process_offices() -> pd.DataFrame:
    """
    Load office listings for all 7 cities, normalise, deduplicate (primary:
    fsq_place_id; secondary: normalised name within city), rank by
    company_prominence_score, and return a DataFrame with OFFICE_SCHEMA columns.
    """
    print("\n" + "=" * 60)
    print("PROCESSING: OFFICES")
    print("=" * 60)

    all_records: list[dict] = []
    seen_fsq_ids: set[str] = set()   # cross-city exact-ID deduplication

    for city in CITIES:
        prefix = _OFFICE_FILE_PREFIXES.get(city, city)
        fp = FOURSQUARE_DIR / f"{prefix}_office_listings.json"
        if not fp.exists():
            print(f"  [WARN] Not found (skip): {fp}", file=sys.stderr)
            continue

        raw_list = load_json(fp)
        if not isinstance(raw_list, list):
            print(f"  [WARN] {fp.name}: not a JSON array, skipped.", file=sys.stderr)
            continue

        city_count = 0
        for raw in raw_list:
            fsq_id = raw.get("fsq_place_id") or ""
            if fsq_id and fsq_id in seen_fsq_ids:
                continue   # identical record already loaded from another city
            if fsq_id:
                seen_fsq_ids.add(fsq_id)
            if not (raw.get("name") or "").strip():
                continue   # skip nameless placeholders
            all_records.append(_office_from_raw(raw, city))
            city_count += 1

        print(f"  [{CITY_LABELS[city]:<12}] Loaded {city_count:>5} office records.")

    if not all_records:
        print("  [ERROR] No office records loaded.", file=sys.stderr)
        return pd.DataFrame(columns=OFFICE_SCHEMA)

    # Secondary deduplication: same normalised name within city
    seen_name_city: set[str] = set()
    deduped: list[dict] = []
    for r in all_records:
        key = f"{r['city']}|{r['normalized_name']}"
        if key not in seen_name_city:
            seen_name_city.add(key)
            deduped.append(r)

    n_dupes = len(all_records) - len(deduped)
    if n_dupes:
        print(f"  Deduplicated {n_dupes} near-duplicate office entries.")

    # Rank by company_prominence_score within each city
    deduped = assign_ranking(deduped, score_field="company_prominence_score", city_field="city")

    df = pd.DataFrame(deduped, columns=OFFICE_SCHEMA)
    df.sort_values(["city", "city_rank"], inplace=True, ignore_index=True)

    print(f"\n  Offices total: {len(df):,} records across {df['city'].nunique()} cities.")
    for city, grp in df.groupby("city"):
        print(f"     {CITY_LABELS.get(city, city):<15} {len(grp):>5} records")
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  ENTITY 3 – HOSPITALS
#  Target CSV: hospitals_unified_all_cities.csv
#
#  Sources:
#    Bangalore : School Data/data/practo_hospitals_bangalore.jsonl
#    Delhi NCR : School Data/scratch/data/practo_hospitals_delhi_ncr.jsonl
#
#  Deduplication (two passes):
#    Pass 1 – Practo hospital ID  (primary key)
#    Pass 2 – normalised_name + coordinates < 200 m  (same physical hospital)
#    Branches of the same chain with distinct coordinates are kept separate.
#
#  Ranking metric: composite hospital_score
#    35%  Bayesian-adjusted rating  (smoothed by city-wide mean, C=50 reviews)
#    25%  review volume
#    20%  doctors count
#    10%  speciality breadth
#    10%  multispeciality flag + establishment maturity (age)
# ─────────────────────────────────────────────────────────────────────────────

_HOSPITAL_SOURCES: list[tuple[str, Path]] = [
    ("bangalore", HOSPITAL_DIR / "data"          / "practo_hospitals_bangalore.jsonl"),
    ("delhi_ncr", HOSPITAL_DIR / "scratch" / "data" / "practo_hospitals_delhi_ncr.jsonl"),
]

_HOSP_W_RATING     = 0.35
_HOSP_W_REVIEWS    = 0.25
_HOSP_W_DOCTORS    = 0.20
_HOSP_W_SPECIALITY = 0.10
_HOSP_W_MATURITY   = 0.10

# Bayesian smoothing constant: number of pseudo-reviews assumed at the city mean
_BAYES_C = 50

_HOSP_REQUIRED = ["name", "city", "latitude", "longitude", "practice_type"]

HOSPITAL_SCHEMA = [
    "hospital_id", "name", "normalized_name", "city",
    "practice_type", "locality", "address",
    "latitude", "longitude", "h3_res7", "zone",
    "doctors_count", "speciality_count", "multispeciality",
    "other_centers_count",
    "consultation_fee_min", "consultation_fee_max",
    "rating", "reviews_count", "year_established",
    "phone", "profile_url", "image_url", "status",
    "source", "scraped_at",
    "data_completeness", "dedupe_status",
    "city_rank", "quartile", "q4_subquartile", "segment",
    "hospital_score",
]


def _parse_count_text(text: str | None, pattern: str) -> int | None:
    """
    Extract the leading integer from strings like "163 Doctors" or "46 Specialities".
    pattern example: r"(\\d+)\\s*Doctor"
    """
    if not text:
        return None
    m = re.search(pattern, str(text), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _hospital_from_raw(raw: dict, city: str) -> dict:
    """
    Normalise one Practo hospital card record into HOSPITAL_SCHEMA.

    Notable raw fields:
      id, name, slug, practice_type, locality, latitude, longitude,
      min_price, max_price, doctor_text, doctors_count, speciality_text,
      multispeciality_text, other_centers_text, vn_phone_number,
      rating, reviews_count, year_established, status,
      profile_url, image_url / enhanced_image_url
    """
    rec: dict = {k: None for k in HOSPITAL_SCHEMA}

    name      = raw.get("name") or ""
    lat       = safe_float(raw.get("latitude"))
    lon       = safe_float(raw.get("longitude"))
    practo_id = str(raw.get("id") or "")

    # Parse doctor / speciality counts from text when not explicitly provided
    doctors_count    = raw.get("doctors_count") \
                       or _parse_count_text(raw.get("doctor_text"),    r"(\d+)\s*Doctor")
    speciality_count = _parse_count_text(raw.get("speciality_text"),   r"(\d+)\s*Special")
    other_centers    = _parse_count_text(raw.get("other_centers_text"), r"(\d+)")

    multi_text  = (raw.get("multispeciality_text") or "").lower()
    multispec   = "multi" in multi_text

    # Phone is stored as {"number": "+91...", "extension": ""}
    phone_obj = raw.get("vn_phone_number") or {}
    phone = phone_obj.get("number") if isinstance(phone_obj, dict) else str(phone_obj or "")

    # Profile URL: relative paths need the base domain prepended
    profile_rel = raw.get("profile_url") or ""
    if profile_rel.startswith("/"):
        profile_url = f"https://www.practo.com{profile_rel}"
    else:
        profile_url = profile_rel or None

    rec["hospital_id"]          = stable_entity_id("hosp", city, practo_id or normalize_name(name))
    rec["name"]                 = name
    rec["normalized_name"]      = normalize_name(name)
    rec["city"]                 = city
    rec["practice_type"]        = raw.get("practice_type")
    rec["locality"]             = raw.get("locality")
    rec["address"]              = None   # Practo listing cards do not include full address
    rec["latitude"]             = lat
    rec["longitude"]            = lon
    rec["h3_res7"]              = latlon_to_h3(lat, lon)
    rec["zone"]                 = None   # to be joined via spatial lookup
    rec["doctors_count"]        = safe_int(doctors_count)
    rec["speciality_count"]     = safe_int(speciality_count)
    rec["multispeciality"]      = multispec
    rec["other_centers_count"]  = safe_int(other_centers)
    rec["consultation_fee_min"] = safe_float(raw.get("min_price"))
    rec["consultation_fee_max"] = safe_float(raw.get("max_price"))
    rec["rating"]               = safe_float(raw.get("rating"))
    rec["reviews_count"]        = safe_int(raw.get("reviews_count"))
    rec["year_established"]     = safe_int(raw.get("year_established"))
    rec["phone"]                = phone or None
    rec["profile_url"]          = profile_url
    rec["image_url"]            = raw.get("image_url") or raw.get("enhanced_image_url")
    rec["status"]               = raw.get("status") or "active"
    rec["source"]               = "practo"
    rec["scraped_at"]           = None   # not embedded in individual JSONL cards

    # Private field for deduplication pass 1 (stripped before export)
    rec["_practo_id"] = practo_id

    rec["data_completeness"] = compute_data_completeness(rec, _HOSP_REQUIRED)
    rec["dedupe_status"]     = "canonical"
    return rec


def _hospital_compute_scores(records: list[dict]) -> list[dict]:
    """
    Compute hospital_score for each record.  All sub-scores are min-max
    normalised within the city before blending.

    Bayesian rating adjustment:
        r_adj = (r * n + global_mean * C) / (n + C)
    where C = _BAYES_C (pseudo-review count anchored at city-wide mean).
    This shrinks unreliable ratings (few reviews) toward the city mean.
    """
    city_groups: dict[str, list[int]] = {}
    for i, r in enumerate(records):
        city_groups.setdefault(r["city"], []).append(i)

    for city, indices in city_groups.items():
        # City-wide mean rating for Bayesian smoothing
        raw_ratings = [safe_float(records[i].get("rating")) for i in indices]
        valid_rat   = [r for r in raw_ratings if r is not None]
        global_mean = sum(valid_rat) / len(valid_rat) if valid_rat else 3.5

        bayes_ratings: list[float] = []
        review_scores: list[float] = []
        doctor_scores: list[float] = []
        spec_scores:   list[float] = []
        maturity_scores: list[float] = []

        for i in indices:
            r = records[i]

            rating  = safe_float(r.get("rating")) or global_mean
            n_rev   = safe_int(r.get("reviews_count")) or 0
            r_adj   = (rating * n_rev + global_mean * _BAYES_C) / (n_rev + _BAYES_C)
            bayes_ratings.append(r_adj)

            review_scores.append(float(n_rev))
            doctor_scores.append(float(safe_int(r.get("doctors_count"))   or 0))
            spec_scores.append(float(  safe_int(r.get("speciality_count")) or 0))

            # Maturity = 50% multispeciality flag + 50% establishment age
            multi_flag = 1.0 if r.get("multispeciality") else 0.0
            yr_est     = safe_int(r.get("year_established"))
            age_score  = max(0.0, min(1.0, (2026 - yr_est) / 60.0)) if yr_est else 0.0
            maturity_scores.append(0.5 * multi_flag + 0.5 * age_score)

        n_bayes   = _minmax_normalise(bayes_ratings)
        n_reviews = _minmax_normalise(review_scores)
        n_docs    = _minmax_normalise(doctor_scores)
        n_spec    = _minmax_normalise(spec_scores)
        n_mat     = _minmax_normalise(maturity_scores)

        for j, idx in enumerate(indices):
            score = (
                _HOSP_W_RATING     * n_bayes[j]
                + _HOSP_W_REVIEWS  * n_reviews[j]
                + _HOSP_W_DOCTORS  * n_docs[j]
                + _HOSP_W_SPECIALITY * n_spec[j]
                + _HOSP_W_MATURITY * n_mat[j]
            )
            records[idx]["hospital_score"] = round(score, 6)

    return records


def process_hospitals() -> pd.DataFrame:
    """
    Load hospital JSONL sources, normalise, deduplicate (two-pass), compute
    composite hospital_score, rank within each city, and return a DataFrame
    with HOSPITAL_SCHEMA columns.

    If source files are missing the function returns an empty DataFrame and
    prints a reminder -- the script is ready to run once scraping completes.
    """
    print("\n" + "=" * 60)
    print("PROCESSING: HOSPITALS")
    print("=" * 60)

    all_records: list[dict] = []

    for city, fpath in _HOSPITAL_SOURCES:
        if not fpath.exists():
            print(f"  [WARN] Not found (skip): {fpath}", file=sys.stderr)
            continue
        raw_list  = load_jsonl(fpath)
        city_recs = [_hospital_from_raw(r, city) for r in raw_list if isinstance(r, dict)]
        print(f"  [{CITY_LABELS[city]:<12}] Loaded {len(city_recs):>5} hospital records.")
        all_records.extend(city_recs)

    if not all_records:
        print("  [WARN] No hospital data found. Returning empty DataFrame.", file=sys.stderr)
        print("         Re-run once Practo scraping completes.", file=sys.stderr)
        return pd.DataFrame(columns=HOSPITAL_SCHEMA)

    # ── Deduplication Pass 1: Practo hospital ID ──────────────────────────────
    seen_practo: set[str] = set()
    pass1: list[dict] = []
    for r in all_records:
        pid = r.get("_practo_id") or ""
        if pid and pid in seen_practo:
            r["dedupe_status"] = "duplicate_practo_id"
            continue
        if pid:
            seen_practo.add(pid)
        pass1.append(r)

    dup1 = len(all_records) - len(pass1)
    if dup1:
        print(f"  Pass 1 deduplication (Practo ID):         removed {dup1} records.")

    # ── Deduplication Pass 2: normalised name + coordinates < 200 m ──────────
    # Purpose: same physical hospital scraped under two different Practo slugs.
    # Branches of the same chain at different locations are intentionally kept.
    city_canonical: dict[str, list[dict]] = {}
    pass2: list[dict] = []

    for r in pass1:
        city  = r["city"]
        norm  = r["normalized_name"]
        lat   = safe_float(r.get("latitude"))
        lon   = safe_float(r.get("longitude"))
        canon = city_canonical.setdefault(city, [])

        is_dup = False
        for existing in canon:
            if existing["normalized_name"] != norm:
                continue
            e_lat = safe_float(existing.get("latitude"))
            e_lon = safe_float(existing.get("longitude"))
            if None in (e_lat, e_lon, lat, lon):
                continue
            if haversine_km(lat, lon, e_lat, e_lon) < 0.2:   # 200 m threshold
                is_dup = True
                break

        if is_dup:
            r["dedupe_status"] = "duplicate_name_coords"
            continue

        canon.append(r)
        pass2.append(r)

    dup2 = len(pass1) - len(pass2)
    if dup2:
        print(f"  Pass 2 deduplication (name + proximity):  removed {dup2} records.")

    # ── Composite hospital_score & ranking ────────────────────────────────────
    pass2 = _hospital_compute_scores(pass2)
    pass2 = assign_ranking(pass2, score_field="hospital_score", city_field="city")

    # Strip private deduplication helper field
    for r in pass2:
        r.pop("_practo_id", None)

    df = pd.DataFrame(pass2, columns=HOSPITAL_SCHEMA)
    df.sort_values(["city", "city_rank"], inplace=True, ignore_index=True)

    print(f"\n  Hospitals total: {len(df):,} records across {df['city'].nunique()} cities.")
    for city, grp in df.groupby("city"):
        print(f"     {CITY_LABELS.get(city, city):<15} {len(grp):>5} records")
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  Atomic CSV Export
#  Writes to a .tmp file first, then renames — matches the atomic_json()
#  pattern used throughout merge.py and rebuild.py.
# ─────────────────────────────────────────────────────────────────────────────

def export_csv(df: pd.DataFrame, output_path: Path) -> None:
    """Atomically write DataFrame to CSV (tmp -> rename)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.csv")
    try:
        df.to_csv(tmp_path, index=False, encoding="utf-8")
        tmp_path.rename(output_path)
        print(f"  -> Wrote: {output_path}  ({len(df):,} rows x {len(df.columns)} cols)")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


# ─────────────────────────────────────────────────────────────────────────────
#  CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────

_ENTITY_MAP: dict[str, tuple] = {
    "localities": (process_localities, OUTPUT_DIR / "real_estate_localities_and_societies.csv"),
    "offices":    (process_offices,    OUTPUT_DIR / "offices_unified_all_cities.csv"),
    "hospitals":  (process_hospitals,  OUTPUT_DIR / "hospitals_unified_all_cities.csv"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Process raw JSON/JSONL entity files into unified CSVs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 pipelines/process_entities.py --entity localities
  python3 pipelines/process_entities.py --entity offices
  python3 pipelines/process_entities.py --entity hospitals
  python3 pipelines/process_entities.py --entity all
  python3 pipelines/process_entities.py --entity all --dry-run
        """,
    )
    parser.add_argument(
        "--entity",
        choices=[*_ENTITY_MAP.keys(), "all"],
        required=True,
        help="Which entity type to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process data and print stats, but do not write output files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override default output directory (pipelines/output/).",
    )
    args = parser.parse_args(argv)

    # Allow CI / test override of the output directory
    if args.output_dir:
        out_root = args.output_dir.resolve()
        for key in _ENTITY_MAP:
            fn, old_path = _ENTITY_MAP[key]
            _ENTITY_MAP[key] = (fn, out_root / old_path.name)

    targets = list(_ENTITY_MAP.keys()) if args.entity == "all" else [args.entity]

    started = datetime.now(timezone.utc)
    print(f"\n{'=' * 60}")
    print(f"  BangaloreRancho — Entity CSV Pipeline")
    print(f"  Started : {started.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Targets : {', '.join(targets)}")
    print(f"  Dry run : {args.dry_run}")
    print(f"{'=' * 60}")

    errors: list[str] = []
    for entity in targets:
        process_fn, out_path = _ENTITY_MAP[entity]
        try:
            df = process_fn()
            if df.empty:
                print(f"\n  [SKIP] {entity}: no data to export.")
                continue
            if args.dry_run:
                print(f"\n  [DRY-RUN] Would write {len(df):,} rows -> {out_path}")
            else:
                export_csv(df, out_path)
        except Exception as exc:
            msg = f"[ERROR] {entity} failed: {exc}"
            print(f"\n  {msg}", file=sys.stderr)
            import traceback; traceback.print_exc()
            errors.append(msg)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"\n{'=' * 60}")
    if errors:
        print(f"  Finished with {len(errors)} error(s) in {elapsed:.1f}s")
        for e in errors:
            print(f"    {e}", file=sys.stderr)
        print(f"{'=' * 60}\n")
        return 1

    print(f"  All done in {elapsed:.1f}s")
    print(f"{'=' * 60}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
