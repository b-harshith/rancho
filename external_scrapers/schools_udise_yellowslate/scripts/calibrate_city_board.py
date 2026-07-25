#!/usr/bin/env python3
"""
City-Board Calibrated Thresholding
==================================
Applies a strict 0.50 threshold to State Board schools across all cities (reducing false positives),
while dynamically adjusting thresholds for CBSE, ICSE, and International boards in each city 
to align with the target premium school distribution.
"""

import gzip
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"

print("Loading predictions CSV...")
pred = pd.read_csv(OUTPUT_DIR / "fee_classification_predictions_all_udise.csv")

print("\nLoading fee data to get true city rates...")
with gzip.open(ROOT / "data/client_export/ezy_yellowslate_unified_all_cities.csv.gz", "rt") as f:
    fee = pd.read_csv(f, dtype={"udise_code": str})
fee["fee"] = pd.to_numeric(fee["fee"], errors="coerce")
fee = fee[fee["fee"].notna() & (fee["fee"] > 0)]

city_true_rates = {}
for city, grp in fee.groupby("city"):
    city_true_rates[city] = len(grp[grp["fee"] > 100000]) / len(grp)

city_true_rates["ahmedabad"] = 0.07
city_true_rates["unknown"] = 0.04

# Apply thresholds:
# 1. State Board: Always use strict 0.50
# 2. Other boards: Calibrate per city to hit the true target rate overall

calibrated_preds = []
city_board_thresholds = {}

for city, grp in pred.groupby("inferred_city"):
    target_rate = city_true_rates.get(city, 0.08)
    expected_premium_count = int(round(len(grp) * target_rate))
    
    # State board schools in this city
    state_mask = grp["inferred_board"] == "state"
    other_mask = grp["inferred_board"] != "state"
    
    # Pre-allocate State board premium predictions with strict 0.50 threshold
    state_grp = grp[state_mask].copy()
    state_grp["predicted_fee_class"] = np.where(state_grp["confidence"] >= 0.50, ">1L", "≤1L")
    state_premium_count = (state_grp["predicted_fee_class"] == ">1L").sum()
    
    # The remainder of the target premium count is allocated to CBSE/ICSE/Intl boards
    remaining_target = max(0, expected_premium_count - state_premium_count)
    other_grp = grp[other_mask].copy()
    
    if len(other_grp) > 0:
        other_confs = other_grp["confidence"].values
        target_fraction_other = min(1.0, remaining_target / len(other_grp))
        
        # Determine calibrated threshold for other boards
        thresh_other = float(np.quantile(other_confs, 1.0 - target_fraction_other))
        
        # Dynamic floor: never go below the 25th percentile of this city's non-state confidence
        # (i.e. don't classify schools in the bottom quartile as premium)
        p25_floor = float(np.percentile(other_confs, 25))
        min_thresh = max(0.22, p25_floor)  # absolute floor is 0.22
        thresh_other = float(np.clip(thresh_other, min_thresh, 0.55))
        
        other_grp["predicted_fee_class"] = np.where(other_grp["confidence"] >= thresh_other, ">1L", "≤1L")
        city_board_thresholds[city] = {"state": 0.50, "others": round(thresh_other, 3)}
    else:
        city_board_thresholds[city] = {"state": 0.50, "others": 0.50}
        
    calibrated_preds.append(pd.concat([state_grp, other_grp]))

calibrated_df = pd.concat(calibrated_preds).sort_index()

print("\n=== City & Board Calibrated Thresholds Used ===")
for city, th in city_board_thresholds.items():
    print(f"  {city:12s}: State Board Thresh = {th['state']:.2f} | CBSE/ICSE/Intl Thresh = {th['others']:.3f}")

print("\n=== Before vs After City-Board Calibration ===")
print(f"  {'City':12s} | {'Before >1L':>10s} | {'After >1L':>9s} | {'Target':>8s}")
print(f"  {'-'*12}-+-{'-'*10}-+-{'-'*9}-+-{'-'*8}")

total_before = 0
total_after = 0
for city in sorted(calibrated_df["inferred_city"].unique()):
    c_grp = calibrated_df[calibrated_df["inferred_city"] == city]
    before = (pred[pred["inferred_city"] == city]["predicted_fee_class"] == ">1L").sum()
    after = (c_grp["predicted_fee_class"] == ">1L").sum()
    n = len(c_grp)
    target = city_true_rates.get(city, 0.08)
    total_before += before
    total_after += after
    print(f"  {city:12s} | {before:5d} ({before/n:.1%}) | {after:4d} ({after/n:.1%}) | {target:.1%}")

print(f"  {'-'*12}-+-{'-'*10}-+-{'-'*9}-+-{'-'*8}")
print(f"  {'TOTAL':12s} | {total_before:>10,} | {total_after:>9,} |")

# Save outputs
calibrated_df.to_csv(OUTPUT_DIR / "fee_classification_predictions_calibrated.csv", index=False)
print(f"\nSaved calibrated predictions: {OUTPUT_DIR / 'fee_classification_predictions_calibrated.csv'}")
