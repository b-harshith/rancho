#!/usr/bin/env python3
"""
99acres Budget Range Classifier
=================================
Trains a Gradient Boosting classifier on the 320 labeled localities to predict
budgetRange (Affordable / Mid-Segment / Premium) for the 844 unlabeled ones.

Features used:
  - rating         (always present)
  - reviewsCount   (always present, parsed as integer)
  - propCount_S    (resale listing count, from propCount dict)
  - propCount_R    (rental listing count, from propCount dict)
  - marketPrice    (numeric sqft price, present for ~36% of unlabeled)
  - registryCount  (numeric, present for many)
  - zoneName       (one-hot encoded: N/S/E/W/Central)

Output:
  - data/raw/99acres_bangalore_localities.json  (with budgetRange filled in)
  - data/raw/99acres_budget_model_report.txt
"""

import json
import re
import numpy as np
from pathlib import Path
from collections import Counter

from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report
from sklearn.impute import SimpleImputer

# ─── Feature extraction ────────────────────────────────────────────────────────

def parse_reviews(s):
    if not s: return 0
    m = re.search(r'\d+', str(s))
    return int(m.group()) if m else 0

def parse_registry(s):
    if not s: return np.nan
    m = re.search(r'\d+', str(s))
    return float(m.group()) if m else np.nan

def get_prop_counts(propcount):
    """Extract total resale (S) and rental (R) listing counts."""
    if not propcount or not isinstance(propcount, dict):
        return np.nan, np.nan
    s_count = propcount.get('S', {}).get('count', np.nan)
    r_count = propcount.get('R', {}).get('count', np.nan)
    return (float(s_count) if s_count else np.nan,
            float(r_count) if r_count else np.nan)

ZONES = ['Bangalore North', 'Bangalore South', 'Bangalore East',
         'Bangalore West', 'Bangalore Central']

def extract_features(rec):
    """Return a feature vector for one locality record."""
    rating       = float(rec.get('rating') or 0)
    reviews      = float(parse_reviews(rec.get('reviewsCount')))
    market_price = float(rec.get('marketPrice')) if rec.get('marketPrice') else np.nan
    registry     = parse_registry(rec.get('registryCount'))
    s_cnt, r_cnt = get_prop_counts(rec.get('propCount'))
    zone         = rec.get('zoneName', '')

    # Zone one-hot (5 zones)
    zone_feats = [1.0 if zone == z else 0.0 for z in ZONES]

    return [rating, reviews, market_price, registry, s_cnt, r_cnt] + zone_feats

FEATURE_NAMES = [
    'rating', 'reviewsCount', 'marketPrice', 'registryCount',
    'propCount_S', 'propCount_R',
    'zone_North', 'zone_South', 'zone_East', 'zone_West', 'zone_Central'
]

# ─── Load data ─────────────────────────────────────────────────────────────────

DATA_FILE = Path('data/raw/99acres_bangalore_localities.json')
data      = json.load(open(DATA_FILE))

labeled   = [x for x in data if x.get('budgetRange')]
unlabeled = [x for x in data if not x.get('budgetRange')]

print(f"Labeled   : {len(labeled)}")
print(f"Unlabeled : {len(unlabeled)}")
print(f"Classes   : {Counter(x['budgetRange'] for x in labeled)}")
print()

# ─── Build feature matrices ────────────────────────────────────────────────────

X_train_raw = np.array([extract_features(x) for x in labeled],   dtype=float)
X_pred_raw  = np.array([extract_features(x) for x in unlabeled], dtype=float)

y_labels    = [x['budgetRange'] for x in labeled]
le          = LabelEncoder()
y_train     = le.fit_transform(y_labels)

print(f"Feature matrix shape (train): {X_train_raw.shape}")
print(f"Feature matrix shape (pred) : {X_pred_raw.shape}")
print()

# Impute missing values with median
imputer = SimpleImputer(strategy='median')
X_train = imputer.fit_transform(X_train_raw)
X_pred  = imputer.transform(X_pred_raw)

# ─── Model training & cross-validation ────────────────────────────────────────

gb_model = GradientBoostingClassifier(
    n_estimators=300,
    learning_rate=0.05,
    max_depth=4,
    min_samples_leaf=5,
    subsample=0.8,
    random_state=42,
)

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_scores = cross_val_score(gb_model, X_train, y_train, cv=cv, scoring='accuracy')
print(f"5-Fold CV Accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
print(f"Per-fold scores   : {[f'{s:.3f}' for s in cv_scores]}")
print()

# Full training on all labeled data
gb_model.fit(X_train, y_train)

# Feature importances
importances = gb_model.feature_importances_
print("Feature importances:")
for name, imp in sorted(zip(FEATURE_NAMES, importances), key=lambda x: -x[1]):
    bar = '█' * int(imp * 40)
    print(f"  {name:<20} {imp:.4f}  {bar}")
print()

# Detailed CV report
from sklearn.model_selection import cross_val_predict
y_pred_cv = cross_val_predict(gb_model, X_train, y_train, cv=cv)
print("Classification report (cross-validated):")
print(classification_report(y_train, y_pred_cv, target_names=le.classes_))

# ─── Predict unlabeled ─────────────────────────────────────────────────────────

y_pred_proba = gb_model.predict_proba(X_pred)
y_pred_class = gb_model.predict(X_pred)
y_pred_labels = le.inverse_transform(y_pred_class)
confidences  = y_pred_proba.max(axis=1)

pred_dist = Counter(y_pred_labels)
print(f"\nPredicted distribution for {len(unlabeled)} unlabeled localities:")
for label, count in pred_dist.most_common():
    print(f"  {label:<15}: {count} ({count/len(unlabeled)*100:.1f}%)")
print()
print(f"Avg confidence : {confidences.mean():.3f}")
print(f"High confidence (>0.7): {(confidences > 0.7).sum()} ({(confidences > 0.7).mean()*100:.1f}%)")
print(f"Med  confidence (0.5-0.7): {((confidences >= 0.5) & (confidences <= 0.7)).sum()}")
print(f"Low  confidence (<0.5): {(confidences < 0.5).sum()}")

# ─── Write predictions back to JSON ────────────────────────────────────────────

# Build a lookup by id
pred_lookup = {}
for rec, label, conf, proba in zip(unlabeled, y_pred_labels, confidences, y_pred_proba):
    pred_lookup[rec['id']] = {
        'predicted_budgetRange': label,
        'prediction_confidence': round(float(conf), 4),
        'prediction_proba': {
            cls: round(float(p), 4)
            for cls, p in zip(le.classes_, proba)
        }
    }

# Update data
for rec in data:
    rid = rec.get('id')
    if rid in pred_lookup:
        p = pred_lookup[rid]
        rec['budgetRange']           = p['predicted_budgetRange']
        rec['budgetRange_source']    = 'ml_predicted'
        rec['budgetRange_confidence']= p['prediction_confidence']
        rec['budgetRange_proba']     = p['prediction_proba']
    else:
        rec['budgetRange_source']    = 'original'
        rec['budgetRange_confidence']= 1.0

# Sort by id
data.sort(key=lambda x: int(x.get('id','0').split('_')[0]))

with open(DATA_FILE, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"\nSaved updated JSON → {DATA_FILE}")

# Final distribution
final_dist = Counter(x['budgetRange'] for x in data)
print("\nFinal budgetRange distribution (all 1164 localities):")
for label, count in final_dist.most_common():
    bar = '█' * (count // 10)
    print(f"  {label:<15}: {count:>4}  {bar}")
