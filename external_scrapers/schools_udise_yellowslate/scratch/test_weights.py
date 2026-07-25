import pandas as pd
import numpy as np
import json
import math
import sys
from pathlib import Path

# Add script directory to path
sys.path.append('scripts')
from fee_classification_udise import (
    build_training_dataset,
    build_preprocessor,
    make_ensemble,
    ALL_FEATURES,
    CATEGORICAL_FEATURES
)

# Load training dataset
df, udise_df, token_freq = build_training_dataset()

X = df[ALL_FEATURES].copy()
y_true = df['target'].values
for col in CATEGORICAL_FEATURES:
    X[col] = X[col].astype(str).fillna('missing')

# True rates from labeled fee data
city_true_rates = {
    'bengaluru': 0.175,
    'chennai': 0.136,
    'delhi_ncr': 0.219,
    'hyderabad': 0.247,
    'kolkata': 0.190,
    'mumbai': 0.267,
    'pune': 0.199,
    'ahmedabad': 0.070,
    'unknown': 0.040
}

# Calculate city-based sample weights
# We want the weighted sum of target=1 in each city to equal city_true_rate * city_total
weights = np.ones(len(df))
for city, grp in df.groupby('city'):
    indices = grp.index
    y_city = y_true[indices]
    n_total = len(grp)
    n_pos = y_city.sum()
    n_neg = n_total - n_pos
    
    target_rate = city_true_rates.get(city, 0.08)
    expected_pos = n_total * target_rate
    expected_neg = n_total * (1 - target_rate)
    
    # Calculate weights to adjust positive/negative ratio in this city to match target rate
    w_pos = expected_pos / n_pos if n_pos > 0 else 1.0
    w_neg = expected_neg / n_neg if n_neg > 0 else 1.0
    
    # Assign weights
    weights[indices] = np.where(y_city == 1, w_pos, w_neg)

print('\nSample weights statistics:')
print(f'Mean weight: {weights.mean():.4f}, Min: {weights.min():.4f}, Max: {weights.max():.4f}')

# Stratified K-Fold CV with Sample Weights
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
probs = np.zeros(len(df))

# Standard scale pos weight for XGB
n_neg, n_pos = (y_true == 0).sum(), (y_true == 1).sum()
spw = n_neg / n_pos

for fold, (train_idx, test_idx) in enumerate(skf.split(X, y_true), 1):
    X_train, X_test = X.iloc[train_idx].copy(), X.iloc[test_idx].copy()
    y_train = y_true[train_idx]
    w_train = weights[train_idx]
    
    pre = build_preprocessor()
    X_tr = pre.fit_transform(X_train)
    X_te = pre.transform(X_test)
    
    ens = make_ensemble(spw)
    # Fit with sample weights
    ens.fit(X_tr, y_train, sample_weight=w_train)
    probs[test_idx] = ens.predict_proba(X_te)[:, 1]

df['confidence'] = probs
df['pred_weighted'] = (df['confidence'] >= 0.50).astype(int)

# Calculate Metrics
acc = accuracy_score(y_true, df['pred_weighted'])
prec = precision_score(y_true, df['pred_weighted'])
rec = recall_score(y_true, df['pred_weighted'])
f1 = f1_score(y_true, df['pred_weighted'])

print('\n=== EVALUATION WITH CITY-BASED SAMPLE WEIGHTS (Threshold 0.50) ===')
print(f'Accuracy:  {acc*100:.2f}%')
print(f'Precision: {prec*100:.2f}%')
print(f'Recall:    {rec*100:.2f}%')
print(f'F1-score:  {f1*100:.2f}%')

print('\nConfusion Matrix:')
cm = confusion_matrix(y_true, df['pred_weighted'])
print(f'               Pred ≤1L   Pred >1L')
print(f'  Actual ≤1L:  {cm[0][0]:>7,}    {cm[0][1]:>7,}')
print(f'  Actual >1L:  {cm[1][0]:>7,}    {cm[1][1]:>7,}')

# Check city rates predicted at 0.50 threshold
print('\n=== Predicted vs Target Rates by City (Threshold 0.50) ===')
for city, grp in df.groupby('city'):
    sub = df[df['city'] == city]
    pred_rate = (sub['pred_weighted'] == 1).sum() / len(sub)
    target = city_true_rates.get(city, 0.08)
    c_acc = accuracy_score(sub['target'], sub['pred_weighted'])
    print(f'  {city:12s}: Pred Rate = {pred_rate:5.1%} | Target = {target:5.1%} | Accuracy = {c_acc*100:5.1f}%')
