#!/usr/bin/env python3
"""
Income Bracket Distribution Estimator for Bangalore Localities
===============================================================
Estimates: out of 100 residents, how many fall into each earning bracket?

Income Brackets (Indian context):
  Low          : < ₹3L/yr  (< ₹25K/mo)
  Lower Middle : ₹3–7.5L/yr (₹25K–62.5K/mo)
  Middle       : ₹7.5–15L/yr (₹62.5K–1.25L/mo)
  Upper Middle : ₹15–30L/yr (₹1.25L–2.5L/mo)
  High         : > ₹30L/yr (> ₹2.5L/mo)

Phase 1: Rule-based mapping from propCount rental + resale price buckets.
Phase 2: Multi-output regression on features for localities without bucket data.
"""

import json
import numpy as np
from pathlib import Path
from collections import Counter

from sklearn.multioutput import MultiOutputRegressor
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import cross_val_score, KFold

# ─── Constants ─────────────────────────────────────────────────────────────────

BRACKETS = ['low', 'lower_middle', 'middle', 'upper_middle', 'high']

# Rental bucket → direct bracket index (indices into BRACKETS list)
# Rule: rent ≈ 30-40% monthly income
RENTAL_TO_BRACKET = {
    '0-10,000/mo':     'low',           # implied monthly income < ₹33K
    '10,000-15,000/mo':'lower_middle',  # implied ₹33K–50K/mo
    '15,000-25,000/mo':'middle',        # implied ₹50K–83K/mo
    '>25,000/mo':      'upper_middle',  # implied > ₹83K/mo (blend upper_middle/high)
    '>35,000/mo':      'upper_middle',
    '25,000-35,000/mo':'upper_middle',
    '35,000-50,000/mo':'upper_middle',
    '>50,000/mo':      'high',
}

# Resale bucket → bracket index
# Rule: property value ≈ 5× annual income
RESALE_TO_BRACKET = {
    '0-50Lacs':    'lower_middle',  # implied < ₹10L/yr
    '50Lacs-1Cr':  'middle',        # implied ₹10–20L/yr
    '1Cr-1_5Cr':   'upper_middle',  # implied ₹20–30L/yr
    '1_5Cr-2Cr':   'high',          # implied ₹30–40L/yr
    '>2Cr':        'high',          # implied > ₹40L/yr
}

# Budget range → approximate income blend for localities with no bucket data
BUDGET_PRIOR = {
    'Affordable':   np.array([20, 40, 30,  8,  2], dtype=float),
    'Mid-Segment':  np.array([ 5, 20, 45, 25,  5], dtype=float),
    'Premium':      np.array([ 1,  5, 20, 45, 29], dtype=float),
}

ZONES = ['Bangalore North', 'Bangalore South', 'Bangalore East',
         'Bangalore West', 'Bangalore Central']

# ─── Helpers ───────────────────────────────────────────────────────────────────

def safe_get(d, *keys):
    for k in keys:
        if not isinstance(d, dict): return None
        d = d.get(k)
    return d

def parse_int(s):
    if s is None: return np.nan
    try: return float(str(s).replace(',', '').strip())
    except: return np.nan

def parse_reviews(s):
    if not s: return 0.0
    import re; m = re.search(r'\d+', str(s))
    return float(m.group()) if m else 0.0

def parse_price(s):
    if not s: return np.nan
    import re; m = re.search(r'[\d]+', str(s).replace(',', ''))
    return float(m.group()) if m else np.nan

# ─── Phase 1: Rule-based from price buckets ────────────────────────────────────

def buckets_to_distribution(bucket_dict, mapping):
    """Convert a {bucket_label: count} dict to a distribution over 5 brackets."""
    dist = np.zeros(5)
    for label, val in bucket_dict.items():
        try:
            count = float(val.get('count', 0))
        except (AttributeError, TypeError):
            count = 0.0
        bracket = mapping.get(label)
        if bracket and count > 0:
            idx = BRACKETS.index(bracket)
            dist[idx] += count

            # '>25,000/mo' → split 60% upper_middle / 40% high
            if label == '>25,000/mo':
                dist[idx] -= count * 0.4
                dist[BRACKETS.index('high')] += count * 0.4

    total = dist.sum()
    return dist / total if total > 0 else None

def estimate_from_buckets(rec):
    """
    Returns (distribution_array, source_tag) or (None, None) if no bucket data.
    distribution_array sums to 1.0.
    """
    pc = rec.get('propCount') or {}

    rental_pb = safe_get(pc, 'R', 'bhk', '0', 'priceBucket') or {}
    resale_pb = safe_get(pc, 'S', 'bhk', '0', 'priceBucket') or {}

    rental_dist = buckets_to_distribution(rental_pb, RENTAL_TO_BRACKET)
    resale_dist = buckets_to_distribution(resale_pb, RESALE_TO_BRACKET)

    rental_total = sum(float(v.get('count', 0)) for v in rental_pb.values()) if rental_pb else 0
    resale_total = sum(float(v.get('count', 0)) for v in resale_pb.values()) if resale_pb else 0

    if rental_dist is None and resale_dist is None:
        return None, None

    # Weight: owners ~60%, renters ~40% (typical Indian metro mix)
    if rental_dist is not None and resale_dist is not None:
        combined = 0.4 * rental_dist + 0.6 * resale_dist
    elif rental_dist is not None:
        combined = rental_dist
    else:
        combined = resale_dist

    return combined, 'price_buckets'

# ─── Feature extraction for Phase 2 regression ────────────────────────────────

def extract_features(rec):
    budget_enc = {'Affordable': 0, 'Mid-Segment': 1, 'Premium': 2}
    zone_feats = [1.0 if rec.get('zoneName') == z else 0.0 for z in ZONES]
    resale_rank = parse_int(safe_get(rec.get('reiStatus') or {}, 'resaleRank'))
    rental_rank = parse_int(safe_get(rec.get('reiStatus') or {}, 'rentalRank'))

    return [
        float(rec.get('rating') or 0),
        parse_reviews(rec.get('reviewsCount')),
        float(budget_enc.get(rec.get('budgetRange', ''), 1)),
        parse_int(rec.get('marketPrice')),
        parse_int(rec.get('registryCount')),
        resale_rank,
        rental_rank,
        float(safe_get(rec.get('propCount') or {}, 'S', 'count') or 0),
        float(safe_get(rec.get('propCount') or {}, 'R', 'count') or 0),
    ] + zone_feats

# ─── Main logic ────────────────────────────────────────────────────────────────

data = json.load(open('data/raw/99acres_bangalore_localities.json'))
print(f"Total localities: {len(data)}")

phase1_records, phase1_dists = [], []
phase2_records = []

for rec in data:
    dist, source = estimate_from_buckets(rec)
    if dist is not None:
        phase1_records.append(rec)
        phase1_dists.append(dist)
    else:
        phase2_records.append(rec)

print(f"Phase 1 (price buckets) : {len(phase1_records)} localities")
print(f"Phase 2 (regression)    : {len(phase2_records)} localities")
print()

# ─── Phase 2: Train regressor on Phase 1 data to fill Phase 2 ─────────────────

X_train = np.array([extract_features(r) for r in phase1_records], dtype=float)
Y_train = np.array(phase1_dists, dtype=float)

imputer = SimpleImputer(strategy='median')
X_train = imputer.fit_transform(X_train)

# Multi-output regression (one GBM per bracket)
base_model = GradientBoostingRegressor(
    n_estimators=200, learning_rate=0.05, max_depth=4,
    min_samples_leaf=5, subsample=0.8, random_state=42
)
multi_reg = MultiOutputRegressor(base_model, n_jobs=-1)
multi_reg.fit(X_train, Y_train)

# CV evaluation on phase-1 data
kf = KFold(n_splits=5, shuffle=True, random_state=42)
cv_r2 = []
for train_idx, val_idx in kf.split(X_train):
    multi_reg.fit(X_train[train_idx], Y_train[train_idx])
    y_pred = multi_reg.predict(X_train[val_idx])
    # Clip and normalize
    y_pred = np.clip(y_pred, 0, 1)
    y_pred = y_pred / y_pred.sum(axis=1, keepdims=True)
    # Mean Absolute Error across brackets
    mae = np.abs(y_pred - Y_train[val_idx]).mean()
    cv_r2.append(mae)

multi_reg.fit(X_train, Y_train)  # Refit on all phase 1
print(f"Phase-2 regression CV (5-fold Mean Absolute Error): {np.mean(cv_r2):.4f} ± {np.std(cv_r2):.4f}")
print(f"(MAE of 0.05 means off by ~5 percentage points per bracket on average)")
print()

# Predict phase-2 localities
if phase2_records:
    X_pred = np.array([extract_features(r) for r in phase2_records], dtype=float)
    X_pred = imputer.transform(X_pred)
    Y_pred = multi_reg.predict(X_pred)
    # Clip negatives and re-normalize
    Y_pred = np.clip(Y_pred, 0, None)
    row_sums = Y_pred.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    Y_pred /= row_sums

# ─── Write results back to JSON ────────────────────────────────────────────────

def to_income_dict(dist_array):
    """Convert distribution array to rounded percentages summing to 100."""
    pct = (dist_array * 100).round(1)
    # Adjust rounding so sum == 100
    diff = 100.0 - pct.sum()
    pct[pct.argmax()] += diff
    return {b: round(float(pct[i]), 1) for i, b in enumerate(BRACKETS)}

def dominant_bracket(dist_dict):
    return max(dist_dict, key=dist_dict.get)

# Apply phase 1
for rec, dist in zip(phase1_records, phase1_dists):
    d = to_income_dict(dist)
    rec['income_distribution'] = d
    rec['dominant_income_bracket'] = dominant_bracket(d)
    rec['income_dist_source'] = 'price_buckets'

# Apply phase 2
for i, rec in enumerate(phase2_records):
    d = to_income_dict(Y_pred[i])
    rec['income_distribution'] = d
    rec['dominant_income_bracket'] = dominant_bracket(d)
    rec['income_dist_source'] = 'ml_regression'

# Save
data.sort(key=lambda x: int(x.get('id', '0').split('_')[0]))
with open('data/raw/99acres_bangalore_localities.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("✅ Saved income_distribution to all 1164 localities.")
print()

# ─── Summary statistics ────────────────────────────────────────────────────────

print("=== Income Distribution Summary by Budget Range ===")
for br in ['Affordable', 'Mid-Segment', 'Premium']:
    subset = [x for x in data if x.get('budgetRange') == br]
    if not subset: continue
    avg = {b: np.mean([x['income_distribution'][b] for x in subset]) for b in BRACKETS}
    print(f"\n  {br} ({len(subset)} localities):")
    for b in BRACKETS:
        bar = '█' * int(avg[b] / 2)
        print(f"    {b:<15}: {avg[b]:>5.1f}%  {bar}")

print()
print("=== Dominant Income Bracket Distribution ===")
dom_counts = Counter(x.get('dominant_income_bracket') for x in data)
for b, cnt in dom_counts.most_common():
    bar = '█' * (cnt // 5)
    print(f"  {b:<15}: {cnt:>4} localities  {bar}")

print()
print("=== Sample Predictions ===")
samples = [x for x in data if x.get('income_dist_source') == 'price_buckets'][:3]
for s in samples:
    print(f"\n  {s['localityName']} ({s['budgetRange']}, {s.get('zoneName')})")
    for b, pct in s['income_distribution'].items():
        bar = '█' * int(pct / 3)
        print(f"    {b:<15}: {pct:>5.1f}%  {bar}")
