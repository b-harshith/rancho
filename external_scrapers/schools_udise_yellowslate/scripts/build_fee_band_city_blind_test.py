#!/usr/bin/env python3
from pathlib import Path
import sys

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_fee_band_model import (
    THRESHOLDS,
    apply_guardrails,
    assign_band,
    build_dataset,
    derive_guardrails,
    fit_models,
    choose_thresholds,
)


CITY_BAND_OUTPUT = ROOT / "output/fee_band_city_blind_test_accuracy.csv"
CITY_OVERALL_OUTPUT = ROOT / "output/fee_band_city_blind_test_overall_accuracy.csv"
CITY_BAND_MD = ROOT / "output/fee_band_city_blind_test_accuracy.md"

BANDS = ["below_75k", "75k_to_100k", "100k_to_150k", "150k_plus"]


def actual_band_from_fee(fee_max):
    if fee_max >= THRESHOLDS["above_150k"]:
        return "150k_plus"
    if fee_max >= THRESHOLDS["above_100k"]:
        return "100k_to_150k"
    if fee_max >= THRESHOLDS["above_75k"]:
        return "75k_to_100k"
    return "below_75k"


def predict_fold(train_df, test_df):
    premium_chain_100, premium_chain_150, premium_pin_100, premium_pin_150 = derive_guardrails(train_df)
    train_X, trained = fit_models(train_df)

    train_probs = pd.DataFrame(index=train_df.index)
    test_probs = pd.DataFrame(index=test_df.index)
    for label, payload in trained.items():
        train_probs[label] = payload["model"].predict_proba(train_X)[:, 1]
        test_probs[label] = payload["model"].predict_proba(test_df[train_X.columns.tolist()])[:, 1]

    guarded_train = apply_guardrails(
        train_df,
        train_probs,
        premium_chain_100,
        premium_chain_150,
        premium_pin_100,
        premium_pin_150,
    )
    thresholds, _ = choose_thresholds(train_df, guarded_train)

    guarded_test = apply_guardrails(
        test_df,
        test_probs,
        premium_chain_100,
        premium_chain_150,
        premium_pin_100,
        premium_pin_150,
    )
    return assign_band(test_df, guarded_test, thresholds)


def main():
    df = build_dataset().copy().reset_index(drop=True)
    df["actual_band"] = df["fee_max"].apply(actual_band_from_fee)

    y = df["actual_band"]
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    fold_predictions = []
    for fold, (train_idx, test_idx) in enumerate(skf.split(df, y), start=1):
        train_df = df.iloc[train_idx].copy().reset_index(drop=True)
        test_df = df.iloc[test_idx].copy().reset_index(drop=True)
        scored = predict_fold(train_df, test_df)
        scored["fold"] = fold
        fold_predictions.append(scored)
        print(f"Completed fold {fold}/5 with {len(test_df):,} test schools.", flush=True)

    blind = pd.concat(fold_predictions, ignore_index=True)

    city_band_rows = []
    city_overall_rows = []
    for city, city_df in blind.groupby("city", dropna=False):
        city_label = city or "unknown"
        overall_accuracy = accuracy_score(city_df["actual_band"], city_df["pred_band"])
        city_overall_rows.append(
            {
                "city": city_label,
                "schools_in_blind_test": len(city_df),
                "overall_exact_band_accuracy": overall_accuracy,
            }
        )
        for band in BANDS:
            actual_mask = city_df["actual_band"] == band
            pred_mask = city_df["pred_band"] == band
            correct = int((actual_mask & pred_mask).sum())
            actual_count = int(actual_mask.sum())
            predicted_count = int(pred_mask.sum())
            precision = precision_score(actual_mask, pred_mask, zero_division=0)
            recall = recall_score(actual_mask, pred_mask, zero_division=0)
            f1 = f1_score(actual_mask, pred_mask, zero_division=0)
            city_band_rows.append(
                {
                    "city": city_label,
                    "fee_band": band,
                    "actual_schools": actual_count,
                    "predicted_schools": predicted_count,
                    "correct_predictions": correct,
                    "precision": precision,
                    "recall": recall,
                    "f1": f1,
                }
            )

    city_band_df = pd.DataFrame(city_band_rows).sort_values(["city", "fee_band"])
    city_overall_df = pd.DataFrame(city_overall_rows).sort_values("city")

    CITY_BAND_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    city_band_df.to_csv(CITY_BAND_OUTPUT, index=False)
    city_overall_df.to_csv(CITY_OVERALL_OUTPUT, index=False)

    with CITY_BAND_MD.open("w", encoding="utf-8") as handle:
        handle.write("| City | Fee band | Actual schools | Predicted schools | Correct | Precision | Recall | F1 |\n")
        handle.write("|---|---|---:|---:|---:|---:|---:|---:|\n")
        for row in city_band_df.itertuples(index=False):
            handle.write(
                f"| {row.city} | {row.fee_band} | {row.actual_schools} | {row.predicted_schools} | {row.correct_predictions} | "
                f"{row.precision:.3f} | {row.recall:.3f} | {row.f1:.3f} |\n"
            )

    print(f"City-band blind-test accuracy: {CITY_BAND_OUTPUT}")
    print(f"City overall blind-test accuracy: {CITY_OVERALL_OUTPUT}")
    print(f"Markdown summary: {CITY_BAND_MD}")


if __name__ == "__main__":
    main()
