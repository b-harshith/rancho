#!/usr/bin/env python3
"""Build final premium master with all-city UDISE rematch and city baseline reconciliation."""

import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
UNIFIED = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
UDISE_GEO = ROOT / "data/client_delivery/udise_private_unaided_with_google_geocoding.csv"
CURRENT_UDISE_PREDS = OUT / "fee_classification_predictions_all_udise.csv"
OLD_MASTER = OUT / "master_schools_all_28947.csv"
NON_UDISE_DEDUPED = OUT / "unmatched_non_udise_premium_schools_7_cities_deduped.json"

REMATCH_CSV = OUT / "all_city_non_udise_fee_gt1L_udise_rematch.csv"
FINAL_CSV = OUT / "final_master_premium_schools_after_all_city_rematch_city_baseline_fix.csv"
FINAL_XLSX = OUT / "final_master_premium_schools_after_all_city_rematch_city_baseline_fix.xlsx"

TARGET_7 = {"bengaluru", "chennai", "delhi_ncr", "hyderabad", "kolkata", "mumbai", "pune"}
OLD_CITY_MAP = {
    "bengaluru": "bengaluru",
    "chennai": "chennai",
    "delhi ncr": "delhi_ncr",
    "delhi_ncr": "delhi_ncr",
    "hyderabad": "hyderabad",
    "kolkata": "kolkata",
    "mumbai": "mumbai",
    "pune": "pune",
}


def clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v).strip()


def safe_float(v):
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def norm(text):
    text = clean(text).lower().replace("&amp;", " and ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    stop = {
        "school", "schools", "public", "senior", "secondary", "sr", "sec",
        "high", "higher", "english", "medium", "the", "pvt", "private",
        "primary", "international", "global", "academy",
    }
    return " ".join(t for t in text.split() if t not in stop)


def similarity(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    sort_seq = SequenceMatcher(None, " ".join(sorted(na.split())), " ".join(sorted(nb.split()))).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    contain = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    # Do not let one-token containment create false positives, e.g.
    # "American Public School" vs "Excelsior American School".
    containment_score = contain * 0.97 if min(len(ta), len(tb)) >= 2 else 0.0
    return max(seq, sort_seq, jac, containment_score)


def haversine_m(lat1, lon1, lat2, lon2):
    vals = [safe_float(x) for x in [lat1, lon1, lat2, lon2]]
    if any(x is None for x in vals):
        return None
    lat1, lon1, lat2, lon2 = vals
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fee_ref(row):
    return safe_float(row.get("fee_max")) or safe_float(row.get("fee")) or safe_float(row.get("fee_min"))


def parse_enrollment(enrollment_json):
    try:
        data = json.loads(enrollment_json or "{}").get("data", {})
        return safe_float(data.get("totalCount"))
    except Exception:
        return None


def delhi_ncr_filter(df):
    state = df["state_name"].fillna("").astype(str).str.upper()
    dist = df["district_name"].fillna("").astype(str).str.upper()
    delhi = state.str.contains("DELHI", na=False) | dist.str.contains("DELHI", na=False)
    haryana = state.str.contains("HARYANA", na=False) & dist.str.contains(
        "GURUGRAM|GURGAON|FARIDABAD|PALWAL|JHAJJAR|ROHTAK|SONIPAT|SONEPAT|PANIPAT",
        regex=True,
        na=False,
    )
    up = state.str.contains("UTTAR PRADESH", na=False) & dist.str.contains(
        "GAUTAM BUDDHA NAGAR|GHAZIABAD|HAPUR|BULANDSHAHR|MEERUT|BAGHPAT",
        regex=True,
        na=False,
    )
    return delhi | haryana | up


def best_udise_match(src, candidates):
    src_name = src["school_name"]
    src_pin = clean(src.get("pincode")).split(".")[0]
    src_lat, src_lon = src.get("latitude"), src.get("longitude")
    toks = norm(src_name).split()
    cand = candidates
    if toks:
        mask = False
        for t in toks[:2]:
            mask = mask | cand["norm_name"].str.contains(re.escape(t), na=False)
        narrowed = cand[mask]
        if len(narrowed):
            cand = narrowed

    scored = []
    for _, u in cand.iterrows():
        name_score = similarity(src_name, u["school_name"])
        if name_score < 0.50:
            continue
        dist = haversine_m(src_lat, src_lon, u.get("latitude"), u.get("longitude"))
        pin_match = bool(src_pin and clean(u.get("pincode")).split(".")[0] == src_pin)
        dist_score = 0
        if dist is not None:
            if dist <= 500:
                dist_score = 0.18
            elif dist <= 1500:
                dist_score = 0.12
            elif dist <= 5000:
                dist_score = 0.05
            elif dist > 25000:
                dist_score = -0.18
        score = name_score + (0.12 if pin_match else 0) + dist_score
        scored.append((score, name_score, dist, pin_match, u))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -1
    score, name_score, dist, pin_match, u = best
    gap = score - second_score

    accepted = False
    reason = "below_threshold"
    if name_score >= 0.995 and (pin_match or (dist is not None and dist <= 3000)) and gap >= 0.03:
        accepted, reason = True, "exact_or_near_exact_name_with_location"
    elif name_score >= 0.95 and dist is not None and dist <= 2500 and gap >= 0.06:
        accepted, reason = True, "strong_name_location_match"
    elif name_score >= 0.93 and pin_match and dist is not None and dist <= 3000 and gap >= 0.08:
        accepted, reason = True, "pincode_and_good_name_match"
    elif name_score >= 0.90 and dist is not None and dist <= 1000 and gap >= 0.08:
        accepted, reason = True, "nearby_good_name_match"

    return {
        "accepted": accepted,
        "reason": reason,
        "score": round(score, 4),
        "name_score": round(name_score, 4),
        "distance_m": round(dist, 1) if dist is not None else None,
        "pin_match": pin_match,
        "gap": round(gap, 4),
        "udise_code": u["udise_code"],
        "udise_school_name": u["school_name"],
        "udise_pincode": u.get("pincode"),
        "udise_district": u.get("district_name"),
        "udise_state": u.get("state_name"),
        "udise_enrollment_total": u.get("enrollment_total"),
        "udise_latitude": u.get("latitude"),
        "udise_longitude": u.get("longitude"),
    }


def build_all_city_rematch():
    src = pd.read_csv(UNIFIED, dtype={"udise_code": str})
    src["fee_reference"] = src.apply(fee_ref, axis=1)
    src = src[
        (src["city"].isin(TARGET_7))
        & (src["match_status"].fillna("").str.lower().eq("unmatched"))
        & (src["fee_reference"] > 100000)
    ].copy()

    ud = pd.read_csv(UDISE_GEO, dtype={"udise_code": str, "pincode": str})
    cur_city = pd.read_csv(CURRENT_UDISE_PREDS, dtype={"udise_code": str})[
        ["udise_code", "inferred_city"]
    ].drop_duplicates("udise_code")
    ud = ud.merge(cur_city, on="udise_code", how="left")
    ud = ud[ud["inferred_city"].isin(TARGET_7)].copy()
    ud["norm_name"] = ud["school_name"].apply(norm)
    ud["enrollment_total"] = ud["enrollment_json"].apply(parse_enrollment)
    ud["latitude"] = pd.to_numeric(ud["latitude"], errors="coerce")
    ud["longitude"] = pd.to_numeric(ud["longitude"], errors="coerce")

    rows = []
    for idx, row in src.iterrows():
        city_candidates = ud[ud["inferred_city"].eq(row.get("city"))]
        match = best_udise_match(row, city_candidates)
        base = {
            "source_index": idx,
            "city": row.get("city"),
            "school_name": row.get("school_name"),
            "area": row.get("area"),
            "pincode": row.get("pincode"),
            "fee_reference": row.get("fee_reference"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "google_place_id": row.get("google_place_id"),
            "primary_url": row.get("primary_url"),
            "source": row.get("source"),
        }
        if match:
            base.update(match)
        else:
            base.update({"accepted": False, "reason": "no_candidate"})
        rows.append(base)

    out = pd.DataFrame(rows)
    out.to_csv(REMATCH_CSV, index=False, encoding="utf-8-sig")
    return out


def load_non_udise_rows(accepted_rematches):
    data = json.loads(NON_UDISE_DEDUPED.read_text(encoding="utf-8"))
    accepted_names = {
        (clean(r["school_name"]).lower(), clean(r.get("google_place_id")).lower())
        for _, r in accepted_rematches[accepted_rematches["accepted"] == True].iterrows()
    }
    rows = []
    excluded = 0
    for s in data["schools"]:
        if not s.get("fee_above_1L"):
            continue
        key = (clean(s.get("name")).lower(), clean(s.get("google_place_id")).lower())
        if s.get("city") in TARGET_7 and key in accepted_names:
            excluded += 1
            continue
        urls = s.get("urls") or {}
        rows.append({
            "record_type": "NON_UDISE_FEE_ABOVE_1L",
            "premium_basis": "actual_fee_above_1L_non_udise_after_rematch",
            "udise_code": "",
            "school_name": s.get("name"),
            "city": s.get("city"),
            "state": "",
            "district": "",
            "area": s.get("area"),
            "address": s.get("address"),
            "pincode": s.get("pincode"),
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "board": s.get("boards"),
            "fee_reference": s.get("fee_reference"),
            "predicted_fee_class": ">1L",
            "confidence": "",
            "threshold_used": "actual_fee",
            "chain_detected": s.get("detected_premium_chain"),
            "enrollment_total": s.get("estimated_student_count"),
            "estimated_grade_2_9_student_count": s.get("estimated_grade_2_9_student_count"),
            "enrollment_source": "estimated_from_premium_benchmark",
            "google_place_id": s.get("google_place_id"),
            "source_dataset": s.get("source_dataset"),
            "source_url": urls.get("primary") or urls.get("yellowslate") or urls.get("ezyschooling"),
            "audit_note": "",
        })
    return pd.DataFrame(rows), excluded


def build_current_udise_rows():
    cur = pd.read_csv(CURRENT_UDISE_PREDS, dtype={"udise_code": str})
    cur = cur[(cur["likely_gt_1L"].astype(int) == 1) & (~cur["inferred_city"].eq("bengaluru"))].copy()
    return pd.DataFrame([{
        "record_type": "UDISE_PREDICTED_PREMIUM",
        "premium_basis": "model_likely_gt_1L_threshold_0.4",
        "udise_code": r["udise_code"],
        "school_name": r["school_name"],
        "city": r["inferred_city"],
        "state": r["state"],
        "district": r["district"],
        "area": "",
        "address": "",
        "pincode": "",
        "latitude": "",
        "longitude": "",
        "board": r["inferred_board"],
        "fee_reference": "",
        "predicted_fee_class": r["predicted_fee_class"],
        "confidence": r["confidence"],
        "threshold_used": r["market_threshold"],
        "chain_detected": r["chain_detected"],
        "enrollment_total": r["enrollment_total"],
        "estimated_grade_2_9_student_count": "",
        "enrollment_source": "UDISE_reported_total",
        "google_place_id": "",
        "source_dataset": "fee_classification_predictions_all_udise",
        "source_url": "",
        "audit_note": "",
    } for _, r in cur.iterrows()])


def build_old_city_baseline_rows():
    old = pd.read_csv(OLD_MASTER, dtype={"udise_code": str})
    old["city_norm"] = old["city"].fillna("").astype(str).str.lower().map(OLD_CITY_MAP)
    old = old[(old["city_norm"].isin(TARGET_7)) & (old["fee_band_calibrated"].eq(">1L"))].copy()
    return pd.DataFrame([{
        "record_type": "UDISE_OLD_CALIBRATED_PREMIUM_BASELINE",
        "premium_basis": "old_calibrated_gt1L_city_baseline_restore",
        "udise_code": r["udise_code"],
        "school_name": r["school_name"],
        "city": r["city_norm"],
        "state": r["state"],
        "district": r["district"],
        "area": "",
        "address": "",
        "pincode": "",
        "latitude": "",
        "longitude": "",
        "board": r["board"],
        "fee_reference": "",
        "predicted_fee_class": ">1L",
        "confidence": r["model_score"],
        "threshold_used": "old_calibrated_restore",
        "chain_detected": r["premium_chain"],
        "enrollment_total": r["k12_enrollment"],
        "estimated_grade_2_9_student_count": r.get("grade_2_9_enrollment_est", ""),
        "enrollment_source": "UDISE_reported_total",
        "google_place_id": "",
        "source_dataset": "master_schools_all_28947",
        "source_url": "",
        "audit_note": "Restored from previous calibrated premium baseline after city-level count drop audit.",
    } for _, r in old.iterrows()])


def build_rematched_rows(rematch, existing_udise_codes):
    accepted = rematch[rematch["accepted"] == True].copy()
    accepted = accepted[~accepted["udise_code"].astype(str).isin(existing_udise_codes)].copy()
    accepted = accepted.sort_values(["score", "name_score"], ascending=False).drop_duplicates("udise_code")
    return pd.DataFrame([{
        "record_type": "UDISE_REMATCHED_ACTUAL_FEE_PREMIUM",
        "premium_basis": "unmatched_fee_gt1L_rematched_to_udise",
        "udise_code": r["udise_code"],
        "school_name": r["udise_school_name"],
        "city": r["city"],
        "state": r["udise_state"],
        "district": r["udise_district"],
        "area": r.get("area", ""),
        "address": "",
        "pincode": r["udise_pincode"],
        "latitude": r["udise_latitude"],
        "longitude": r["udise_longitude"],
        "board": "",
        "fee_reference": r["fee_reference"],
        "predicted_fee_class": ">1L",
        "confidence": r["score"],
        "threshold_used": "actual_fee_rematch",
        "chain_detected": "",
        "enrollment_total": r["udise_enrollment_total"],
        "estimated_grade_2_9_student_count": "",
        "enrollment_source": "UDISE_reported_total_after_rematch",
        "google_place_id": r.get("google_place_id", ""),
        "source_dataset": "all_city_rematch",
        "source_url": r.get("primary_url", ""),
        "audit_note": f"Rematched from scraped name '{r['school_name']}' ({r['reason']}, name_score={r['name_score']}, distance_m={r['distance_m']}).",
    } for _, r in accepted.iterrows()])


def main():
    rematch = build_all_city_rematch()
    udise_base = build_current_udise_rows()
    old_baseline = build_old_city_baseline_rows()
    non_udise, excluded_non_udise = load_non_udise_rows(rematch)

    old_codes = set(old_baseline["udise_code"].dropna().astype(str))
    current_not_in_old = udise_base[~udise_base["udise_code"].astype(str).isin(old_codes)].copy()
    existing_codes = set(old_baseline["udise_code"].dropna().astype(str))
    rematched_rows = build_rematched_rows(rematch, existing_codes)
    master = pd.concat([old_baseline, rematched_rows, non_udise], ignore_index=True, sort=False)
    master = master[master["city"].isin(TARGET_7)].copy()
    master["enrollment_total"] = pd.to_numeric(master["enrollment_total"], errors="coerce").fillna(0)
    master.to_csv(FINAL_CSV, index=False, encoding="utf-8-sig")

    summary = pd.DataFrame([
        {"metric": "Old calibrated UDISE premium city baseline", "count": len(old_baseline)},
        {"metric": "Current UDISE premium at 0.4 not in old baseline (audit only, not added)", "count": len(current_not_in_old)},
        {"metric": "All-city rematches accepted", "count": int((rematch["accepted"] == True).sum())},
        {"metric": "All-city rematches added as UDISE rows not already present", "count": len(rematched_rows)},
        {"metric": "Non-UDISE additions excluded due to all-city rematch", "count": excluded_non_udise},
        {"metric": "Remaining non-UDISE fee >1L additions", "count": len(non_udise)},
        {"metric": "Final master rows", "count": len(master)},
        {"metric": "Final K-12 enrollment", "count": int(round(master["enrollment_total"].sum()))},
    ])
    city = master.groupby(["city", "record_type"], dropna=False).agg(
        schools=("school_name", "count"),
        k12_enrollment=("enrollment_total", "sum"),
    ).reset_index()
    city["k12_enrollment"] = city["k12_enrollment"].round().astype(int)
    city_total = master.groupby("city").agg(
        schools=("school_name", "count"),
        k12_enrollment=("enrollment_total", "sum"),
    ).reset_index().sort_values("k12_enrollment", ascending=False)
    city_total["k12_enrollment"] = city_total["k12_enrollment"].round().astype(int)

    with pd.ExcelWriter(FINAL_XLSX, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="summary")
        city_total.to_excel(writer, index=False, sheet_name="city_totals")
        city.to_excel(writer, index=False, sheet_name="city_by_source")
        rematch.to_excel(writer, index=False, sheet_name="all_city_rematch_audit")
        current_not_in_old.to_excel(writer, index=False, sheet_name="current_not_in_old_audit")
        master.to_excel(writer, index=False, sheet_name="final_master")

    print("final_csv", FINAL_CSV)
    print("final_xlsx", FINAL_XLSX)
    print(summary.to_string(index=False))
    print("\nCity totals")
    print(city_total.to_string(index=False))


if __name__ == "__main__":
    main()
