#!/usr/bin/env python3
"""Build JSON of non-UDISE schools/campuses in the 7 cities with enrollment estimates."""

import ast
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fee_classification_udise import PLAYSCHOOL_RE  # noqa: E402


UNIFIED_PATH = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
BANGALORE_PATH = Path(
    "/Users/malleswararao/Desktop/BangaloreRancho/"
    "web_platform_vercel_exact_latest/src/public/data/schools.json"
)
CLASSIFIER_PATH = ROOT / "scripts/fee_classification_udise.py"
OUTPUT_PATH = ROOT / "output/unmatched_non_udise_premium_schools_7_cities.json"

TARGET_CITIES = ["bengaluru", "chennai", "delhi_ncr", "hyderabad", "kolkata", "mumbai", "pune"]
TOP_TOP_FEE_THRESHOLD = 150_000
ABOVE_1L_THRESHOLD = 100_000


def safe_float(value):
    try:
        if value is None:
            return None
        val = float(value)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    except (TypeError, ValueError):
        return None


def safe_int(value):
    val = safe_float(value)
    if val is None:
        return None
    return int(round(val))


def clean_str(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def norm(text):
    text = str(text or "").lower().replace("&amp;", "and").replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def record_id(row):
    base = "|".join(
        str(row.get(k) or "")
        for k in ["city", "school_name", "area", "pincode", "latitude", "longitude", "google_place_id"]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def extract_regexes():
    tree = ast.parse(CLASSIFIER_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PREMIUM_REGEXES":
                    rows = []
                    for key_node, val_node in zip(node.value.keys, node.value.values):
                        key = ast.literal_eval(key_node)
                        pattern = ast.literal_eval(val_node.args[0])
                        rows.append({"chain": key, "pattern": pattern, "regex": re.compile(pattern, re.I)})
                    return rows
    raise RuntimeError("PREMIUM_REGEXES not found")


def load_unified():
    df = pd.read_csv(UNIFIED_PATH, dtype={"udise_code": str, "pincode": str})
    df["source_dataset"] = "ezy_yellowslate_unified_all_cities_geocoded"
    return df


def load_bengaluru():
    if not BANGALORE_PATH.exists():
        return pd.DataFrame()
    data = json.loads(BANGALORE_PATH.read_text(encoding="utf-8"))
    rows = []
    for item in data:
        rows.append({
            "school_name": item.get("name"),
            "normalized_name": norm(item.get("name")),
            "city": "bengaluru",
            "area": item.get("area") or item.get("google_locality"),
            "address": item.get("address") or item.get("google_formatted_address"),
            "pincode": item.get("pincode") or item.get("google_postal_code"),
            "latitude": item.get("lat"),
            "longitude": item.get("lon"),
            "coordinate_source": item.get("google_geocode_source") or item.get("source"),
            "boards": item.get("board"),
            "fee": item.get("fee"),
            "fee_min": item.get("fee_min"),
            "fee_max": item.get("fee_max"),
            "fee_text": item.get("fee_text"),
            "lowest_class": None,
            "highest_class": None,
            "offered_classes": None,
            "structural_category": item.get("structural_category"),
            "student_enrollment": item.get("students_total") or item.get("students"),
            "student_enrollment_grades_2_9": item.get("students_grades_2_9"),
            "enrollment_source": item.get("enrollment_source"),
            "udise_code": item.get("udise_code"),
            "udise_school_name": None,
            "match_status": item.get("match_status"),
            "ezyschooling_url": None,
            "yellowslate_url": item.get("url"),
            "primary_url": item.get("url"),
            "source": item.get("source"),
            "category": item.get("category"),
            "zone": item.get("zone"),
            "google_formatted_address": item.get("google_formatted_address"),
            "google_place_id": item.get("google_place_id"),
            "google_location_type": None,
            "google_partial_match": None,
            "google_result_types": "|".join(item.get("google_types") or []),
            "google_geocode_query": item.get("google_geocode_query"),
            "google_geocode_status": None,
            "google_used_fallback_query": None,
            "geocode_confidence": item.get("google_geocode_confidence"),
            "source_dataset": "bangalore_schools_json",
        })
    return pd.DataFrame(rows)


def grade_band(row):
    hi = safe_float(row.get("highest_class"))
    lo = safe_float(row.get("lowest_class"))
    structural = str(row.get("structural_category") or "").lower()
    classes = str(row.get("offered_classes") or "").lower()
    text = f"{structural} {classes}"

    if hi is not None:
        if hi >= 12:
            return "k12"
        if hi >= 10:
            return "k10"
        if hi >= 8:
            return "upto8"
        return "primary_or_below"

    if "k-12" in text or "senior secondary" in text or "higher secondary" in text:
        return "k12"
    if "k-10" in text or "secondary" in text:
        return "k10"
    if "middle" in text or "k-8" in text:
        return "upto8"
    if lo is not None and lo >= 6:
        return "middle_or_secondary"
    return "unknown"


def fee_ref(row):
    return safe_float(row.get("fee_max")) or safe_float(row.get("fee")) or safe_float(row.get("fee_min"))


def is_udise_unmatched(df):
    code = df["udise_code"].fillna("").astype(str).str.strip()
    no_code = code.eq("") | code.str.lower().isin({"nan", "none", "null"})
    status = df["match_status"].fillna("").astype(str).str.lower()
    weak_or_unmatched = status.str.contains("unmatched|no_match|no match|weak|not_found|not found", regex=True)
    return no_code | weak_or_unmatched


def detect_chain(name, regex_rows):
    for rank, row in enumerate(regex_rows, start=1):
        if row["regex"].search(str(name or "")):
            return row["chain"], rank
    return "independent", None


def build_chain_ranking(regex_rows, all_df):
    chain_fees = {r["chain"]: [] for r in regex_rows}
    for _, row in all_df.iterrows():
        fee = fee_ref(row)
        if not fee:
            continue
        name = row.get("school_name")
        for rx in regex_rows:
            if rx["regex"].search(str(name or "")):
                chain_fees[rx["chain"]].append(float(fee))
                break

    ranked = []
    for rx in regex_rows:
        fees = pd.Series(chain_fees[rx["chain"]], dtype=float)
        if len(fees):
            ranked.append({
                "chain": rx["chain"],
                "fee_n": int(len(fees)),
                "p90_fee": float(fees.quantile(0.9)),
                "max_fee": float(fees.max()),
                "median_fee": float(fees.median()),
            })
        else:
            ranked.append({"chain": rx["chain"], "fee_n": 0, "p90_fee": 0.0, "max_fee": 0.0, "median_fee": 0.0})

    ranked.sort(key=lambda r: (r["fee_n"] > 0, r["p90_fee"], r["max_fee"], r["median_fee"]), reverse=True)
    return {row["chain"]: i for i, row in enumerate(ranked, start=1)}, ranked[:150]


def trimmed_average(series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    s = s[(s >= 50) & (s <= 6000)]
    if s.empty:
        return None
    if len(s) >= 10:
        low, high = s.quantile(0.05), s.quantile(0.95)
        s = s[(s >= low) & (s <= high)]
    return float(s.mean()) if len(s) else None


def build_enrollment_benchmarks(all_df):
    df = all_df.copy()
    df["fee_ref"] = df.apply(fee_ref, axis=1)
    df["grade_band"] = df.apply(grade_band, axis=1)
    df["student_enrollment"] = pd.to_numeric(df["student_enrollment"], errors="coerce")
    df["student_enrollment_grades_2_9"] = pd.to_numeric(df["student_enrollment_grades_2_9"], errors="coerce")

    basis = df[
        (df["fee_ref"] >= TOP_TOP_FEE_THRESHOLD)
        & df["student_enrollment"].notna()
        & (df["student_enrollment"] >= 100)
        & ~df["school_name"].fillna("").str.contains(PLAYSCHOOL_RE)
    ].copy()

    benchmarks = {}
    for band, grp in basis.groupby("grade_band"):
        avg_total = trimmed_average(grp["student_enrollment"])
        avg_g29 = trimmed_average(grp["student_enrollment_grades_2_9"])
        if avg_total is None:
            continue
        if avg_g29 is None:
            ratio = {"k12": 0.70, "k10": 0.77, "upto8": 0.82, "primary_or_below": 0.60}.get(band, 0.73)
            avg_g29 = avg_total * ratio
        benchmarks[band] = {
            "sample_count": int(len(grp)),
            "avg_total_students": int(round(avg_total)),
            "avg_grade_2_9_students": int(round(avg_g29)),
        }

    overall_total = trimmed_average(basis["student_enrollment"])
    overall_g29 = trimmed_average(basis["student_enrollment_grades_2_9"])
    benchmarks["fallback"] = {
        "sample_count": int(len(basis)),
        "avg_total_students": int(round(overall_total or 750)),
        "avg_grade_2_9_students": int(round(overall_g29 or (overall_total or 750) * 0.73)),
    }
    return benchmarks


def estimate_enrollment(row, benchmarks):
    band = grade_band(row)
    bench = benchmarks.get(band) or benchmarks["fallback"]
    return int(bench["avg_total_students"]), int(bench["avg_grade_2_9_students"]), band, bench


def main():
    unified = load_unified()
    bengaluru = load_bengaluru()
    all_df = pd.concat([unified, bengaluru], ignore_index=True, sort=False)
    all_df["city"] = all_df["city"].fillna("").astype(str).str.strip().str.lower()

    regex_rows_original = extract_regexes()
    chain_rank, top150_rows = build_chain_ranking(regex_rows_original, all_df)
    regex_rows = sorted(regex_rows_original, key=lambda r: chain_rank.get(r["chain"], 10_000))
    top150_chains = {r["chain"] for r in top150_rows}

    benchmarks = build_enrollment_benchmarks(all_df)

    candidates = all_df[
        all_df["city"].isin(TARGET_CITIES)
        & is_udise_unmatched(all_df)
        & ~all_df["school_name"].fillna("").str.contains(PLAYSCHOOL_RE)
    ].copy()

    candidates["lat_num"] = pd.to_numeric(candidates["latitude"], errors="coerce")
    candidates["lon_num"] = pd.to_numeric(candidates["longitude"], errors="coerce")
    candidates = candidates[candidates["lat_num"].notna() & candidates["lon_num"].notna()].copy()
    candidates["dedupe_key"] = candidates.apply(
        lambda r: clean_str(r.get("google_place_id"))
        or f"{r.get('city')}|{norm(r.get('school_name'))}|{round(float(r.get('lat_num')), 5)}|{round(float(r.get('lon_num')), 5)}",
        axis=1,
    )
    candidates = candidates.sort_values(["city", "school_name"]).drop_duplicates("dedupe_key").copy()

    schools = []
    for _, row in candidates.iterrows():
        name = clean_str(row.get("school_name"))
        chain, _ = detect_chain(name, regex_rows)
        rank = chain_rank.get(chain) if chain != "independent" else None
        fee_value = fee_ref(row)
        estimated_total, estimated_g29, band, bench = estimate_enrollment(row, benchmarks)
        above_1l = bool(fee_value is not None and fee_value > ABOVE_1L_THRESHOLD)
        top150_tag = bool(above_1l and chain in top150_chains)

        tags = ["not_in_udise", "student_count_estimated_from_premium_benchmark"]
        if above_1l:
            tags.append("fee_above_1L")
        if top150_tag:
            tags.append("top_150_premium_chain_above_1L")

        schools.append({
            "id": record_id(row),
            "name": name,
            "city": clean_str(row.get("city")),
            "area": clean_str(row.get("area")),
            "address": clean_str(row.get("address")) or clean_str(row.get("google_formatted_address")),
            "pincode": clean_str(row.get("pincode")),
            "latitude": safe_float(row.get("latitude")),
            "longitude": safe_float(row.get("longitude")),
            "coordinate_source": clean_str(row.get("coordinate_source")),
            "geocode_confidence": clean_str(row.get("geocode_confidence")),
            "google_place_id": clean_str(row.get("google_place_id")),
            "boards": clean_str(row.get("boards")),
            "fee": safe_float(row.get("fee")),
            "fee_min": safe_float(row.get("fee_min")),
            "fee_max": safe_float(row.get("fee_max")),
            "fee_reference": fee_value,
            "fee_text": clean_str(row.get("fee_text")),
            "fee_above_1L": above_1l,
            "lowest_class": safe_int(row.get("lowest_class")),
            "highest_class": safe_int(row.get("highest_class")),
            "offered_classes": clean_str(row.get("offered_classes")),
            "structural_category": clean_str(row.get("structural_category")),
            "grade_band_for_estimate": band,
            "original_student_count": safe_int(row.get("student_enrollment")),
            "original_grade_2_9_student_count": safe_int(row.get("student_enrollment_grades_2_9")),
            "original_enrollment_source": clean_str(row.get("enrollment_source")),
            "estimated_student_count": estimated_total,
            "estimated_grade_2_9_student_count": estimated_g29,
            "estimation_basis": {
                "method": "trimmed_average_of_top_top_fee_schools_by_grade_band",
                "top_top_fee_threshold": TOP_TOP_FEE_THRESHOLD,
                "benchmark_grade_band": band if band in benchmarks else "fallback",
                **bench,
            },
            "udise_status": "not_in_udise",
            "match_status": clean_str(row.get("match_status")),
            "udise_code": None,
            "udise_school_name": clean_str(row.get("udise_school_name")),
            "detected_premium_chain": chain,
            "premium_chain_rank_by_fee": rank,
            "top_150_premium_chain_above_1L": top150_tag,
            "tags": tags,
            "category": clean_str(row.get("category")),
            "zone": clean_str(row.get("zone")),
            "source": clean_str(row.get("source")),
            "source_dataset": clean_str(row.get("source_dataset")),
            "urls": {
                "primary": clean_str(row.get("primary_url")),
                "yellowslate": clean_str(row.get("yellowslate_url")),
                "ezyschooling": clean_str(row.get("ezyschooling_url")),
            },
        })

    schools.sort(key=lambda s: (
        s["city"] or "",
        not s["top_150_premium_chain_above_1L"],
        -(s["fee_reference"] or 0),
        s["name"] or "",
    ))

    output = {
        "metadata": {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "cities": TARGET_CITIES,
            "source_files": [
                str(UNIFIED_PATH.relative_to(ROOT)),
                str(BANGALORE_PATH),
            ],
            "definition_not_in_udise": "No UDISE code or match_status indicating unmatched/weak/no match.",
            "student_estimation_method": (
                "For every non-UDISE school, estimated total and grade 2-9 enrollment are assigned from "
                "trimmed average enrollment of top-top fee schools (fee >= Rs 1.5L) with known student counts, "
                "grouped by grade span. This is intentionally an estimate for premium/professional schools "
                "that may not disclose enrollment."
            ),
            "top_150_tag_definition": (
                "top_150_premium_chain_above_1L is true only when fee_reference > Rs 1L and the detected "
                "PREMIUM_REGEXES chain is inside the top 150 chains ranked by observed fee premiumness."
            ),
            "enrollment_benchmarks": benchmarks,
            "counts": {
                "schools": len(schools),
                "fee_above_1L": int(sum(1 for s in schools if s["fee_above_1L"])),
                "top_150_premium_chain_above_1L": int(sum(1 for s in schools if s["top_150_premium_chain_above_1L"])),
                "by_city": pd.Series([s["city"] for s in schools]).value_counts().to_dict(),
            },
        },
        "schools": schools,
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(OUTPUT_PATH)
    print(json.dumps(output["metadata"]["counts"], indent=2))


if __name__ == "__main__":
    main()
