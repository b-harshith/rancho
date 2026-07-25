#!/usr/bin/env python3
"""
Per-City Threshold Calibration — Post-Processing Step
=======================================================
The global model uses a single 0.50 threshold for all cities.
This script re-applies city-specific thresholds derived from the
actual labeled fee data's >1L rate per city.

Strategy:
  - For each city, compute the true >1L rate from fee data
  - Set the city threshold so that the predicted rate matches
    the true rate (percentile-based calibration)
  - This corrects the systematic under/over-prediction per city
"""

import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"

# ─────────────────── Load existing predictions ───────────────────
print("Loading predictions CSV...")
pred = pd.read_csv(OUTPUT_DIR / "fee_classification_predictions_all_udise.csv")
print(f"  Total schools: {len(pred):,}")
print(f"  Current >1L (global 0.50): {(pred['predicted_fee_class'] == '>1L').sum():,}")

# ─────────────────── Load actual fee data ───────────────────
print("\nLoading fee data to derive true city rates...")
with gzip.open(ROOT / "data/client_export/ezy_yellowslate_unified_all_cities.csv.gz", "rt") as f:
    fee = pd.read_csv(f, dtype={"udise_code": str})
fee["fee"] = pd.to_numeric(fee["fee"], errors="coerce")
fee = fee[fee["fee"].notna() & (fee["fee"] > 0)]

# Compute true >1L rate per city from labeled data
city_true_rates = {}
print("\n=== Actual >1L rates from fee data ===")
for city, grp in fee.groupby("city"):
    total = len(grp)
    above = (grp["fee"] > 100_000).sum()
    rate = above / total
    city_true_rates[city] = rate
    print(f"  {city:12s}: {above:4d}/{total:5d} = {rate:.1%}")

# Ahmedabad not in fee data — use conservative estimate from market context
city_true_rates["ahmedabad"] = 0.07   # conservative, no labeled data
city_true_rates["unknown"]   = 0.04   # low prior for unmapped schools

print(f"\n  ahmedabad   : estimated = 7.0% (no labeled data)")
print(f"  unknown     : estimated = 4.0% (no labeled data)")

# ─────────────────── Current model rates per city ───────────────────
print("\n=== Current model >1L rates vs target ===")
print(f"  {'City':12s} | {'Model%':>8s} | {'Target%':>8s} | {'Action':>10s}")
print(f"  {'-'*12}-+-{'-'*8}-+-{'-'*8}-+-{'-'*10}")

city_model_rates = {}
for city, grp in pred.groupby("inferred_city"):
    model_rate = (grp["predicted_fee_class"] == ">1L").sum() / len(grp)
    city_model_rates[city] = model_rate
    target = city_true_rates.get(city, 0.08)
    direction = "↑ boost" if model_rate < target - 0.01 else ("↓ reduce" if model_rate > target + 0.01 else "✓ ok")
    print(f"  {city:12s} | {model_rate:>7.1%} | {target:>7.1%} | {direction:>10s}")

# ─────────────────── Compute per-city thresholds ───────────────────
# For each city, find the probability threshold that gives ~target rate
# i.e., set threshold = (1 - target_rate) percentile of confidences

print("\n=== Computing per-city calibrated thresholds ===")
city_thresholds = {}
for city, grp in pred.groupby("inferred_city"):
    target_rate = city_true_rates.get(city, 0.08)
    confidences = grp["confidence"].values
    # We want top `target_rate` fraction to be >1L
    # So threshold = (1 - target_rate) quantile of confidences
    thresh = np.quantile(confidences, 1.0 - target_rate)
    # Clamp: don't go below 0.25 (avoid noise) or above 0.70
    thresh = float(np.clip(thresh, 0.25, 0.70))
    city_thresholds[city] = thresh
    print(f"  {city:12s}: target={target_rate:.1%}  threshold={thresh:.3f}")

# Global fallback threshold for any city not in the map
global_thresh = 0.50

# ─────────────────── Apply calibrated thresholds ───────────────────
print("\nApplying calibrated thresholds...")
pred["city_threshold"] = pred["inferred_city"].map(city_thresholds).fillna(global_thresh)
pred["predicted_fee_class_calibrated"] = np.where(
    pred["confidence"] >= pred["city_threshold"], ">1L", "≤1L"
)

# ─────────────────── Summary comparison ───────────────────
print("\n=== Before vs After Calibration ===")
print(f"  {'City':12s} | {'Before >1L':>10s} | {'After >1L':>9s} | {'Change':>8s} | {'Target':>8s}")
print(f"  {'-'*12}-+-{'-'*10}-+-{'-'*9}-+-{'-'*8}-+-{'-'*8}")

total_before = 0
total_after  = 0
for city in sorted(pred["inferred_city"].unique()):
    grp = pred[pred["inferred_city"] == city]
    before = (grp["predicted_fee_class"] == ">1L").sum()
    after  = (grp["predicted_fee_class_calibrated"] == ">1L").sum()
    n      = len(grp)
    target = city_true_rates.get(city, 0.08)
    delta  = after - before
    total_before += before
    total_after  += after
    sign   = "+" if delta >= 0 else ""
    print(f"  {city:12s} | {before:5d} ({before/n:.1%}) | {after:4d} ({after/n:.1%}) | {sign}{delta:>5d}    | {target:.1%}")

print(f"  {'─'*12}-+-{'─'*10}-+-{'─'*9}-+-{'─'*8}-+-{'─'*8}")
delta_total = total_after - total_before
print(f"  {'TOTAL':12s} | {total_before:>10,} | {total_after:>9,} | +{delta_total:>6,} |")

# ─────────────────── Validate against labeled data ───────────────────
print("\n=== Cross-validation: Bengaluru confirmed >1L schools ===")
udise = pd.read_csv(
    ROOT / "data/client_delivery/udise_private_unaided_with_enrollment.csv",
    encoding="utf-8-sig", dtype={"udise_code": str}
)
beng_districts = ["BENGALURU U SOUTH", "BENGALURU U NORTH", "BENGALURU RURAL"]
beng_codes = set(udise[udise["district_name"].isin(beng_districts)]["udise_code"].tolist())

# Load bengaluru fee data
with gzip.open(ROOT / "data/client_export/ezy_yellowslate_unified_all_cities.csv.gz", "rt") as f:
    fee_all = pd.read_csv(f, dtype={"udise_code": str})
fee_all["fee"] = pd.to_numeric(fee_all["fee"], errors="coerce")
beng_actual = fee_all[
    (fee_all["city"] == "bengaluru") &
    (fee_all["fee"] > 100_000) &
    fee_all["udise_code"].notna()
]
confirmed_codes = set(beng_actual["udise_code"].dropna().unique())

beng_pred = pred[pred["udise_code"].astype(str).isin(beng_codes)]
matched = beng_pred[beng_pred["udise_code"].astype(str).isin(confirmed_codes)]

before_tp = (matched["predicted_fee_class"] == ">1L").sum()
after_tp  = (matched["predicted_fee_class_calibrated"] == ">1L").sum()
total_confirmed = len(matched)

print(f"  Confirmed >1L Bengaluru schools (with UDISE): {len(confirmed_codes)}")
print(f"  Matched in predictions: {total_confirmed}")
print(f"  True Positives BEFORE calibration: {before_tp}/{total_confirmed} ({before_tp/total_confirmed:.1%})")
print(f"  True Positives AFTER  calibration: {after_tp}/{total_confirmed}  ({after_tp/total_confirmed:.1%})")

# ─────────────────── Save outputs ───────────────────
# Main calibrated predictions CSV
out = pred.drop(columns=["city_threshold"]).copy()
out.rename(columns={
    "predicted_fee_class": "predicted_fee_class_global",
    "predicted_fee_class_calibrated": "predicted_fee_class",
}, inplace=True)

out.to_csv(OUTPUT_DIR / "fee_classification_predictions_calibrated.csv", index=False)
print(f"\n  Saved: {OUTPUT_DIR / 'fee_classification_predictions_calibrated.csv'}")

# City threshold lookup table
thresh_df = pd.DataFrame([
    {"city": city, "true_rate_pct": round(city_true_rates.get(city, 0.08) * 100, 1),
     "model_rate_before_pct": round(city_model_rates.get(city, 0) * 100, 1),
     "calibrated_threshold": round(city_thresholds.get(city, global_thresh), 3)}
    for city in sorted(pred["inferred_city"].unique())
])
thresh_df.to_csv(OUTPUT_DIR / "city_calibrated_thresholds.csv", index=False)
print(f"  Saved: {OUTPUT_DIR / 'city_calibrated_thresholds.csv'}")

print(f"\n{'═'*65}")
print(f"  CALIBRATION COMPLETE")
print(f"  Global threshold (0.50): {total_before:,} schools >1L")
print(f"  City-calibrated:         {total_after:,} schools >1L (+{delta_total:,})")
print(f"{'═'*65}")
