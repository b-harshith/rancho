#!/usr/bin/env python3
import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_fee_band_model import build_dataset, derive_guardrails

ITERATION_LOG = ROOT / "output/premium_optimizer_iterations.csv"
SUMMARY_JSON = ROOT / "output/premium_optimizer_summary.json"
SUMMARY_MD = ROOT / "output/premium_optimizer_summary.md"

TARGET_THRESHOLD = 100000

BASE_NUMERIC = {
    "lowest_class",
    "highest_class",
    "class_span",
    "entity_count",
    "log_students_total",
    "log_students_g29",
    "enrollment_missing_total",
    "enrollment_missing_g29",
    "suspicious_match",
    "board_cbse",
    "board_icse_cisce",
    "board_international",
    "board_state",
    "board_other",
    "latitude",
    "longitude",
}
BASE_CATEGORICAL = {"city", "pincode", "chain_key", "source_combo", "board_family"}

FEATURE_GROUPS = {
    "boards": {
        "numeric": {"board_cbse", "board_icse_cisce", "board_international", "board_state", "board_other"},
        "categorical": {"board_family"},
    },
    "enrollment": {
        "numeric": {"log_students_total", "log_students_g29", "enrollment_missing_total", "enrollment_missing_g29"},
        "categorical": set(),
    },
    "class_range": {
        "numeric": {"lowest_class", "highest_class", "class_span"},
        "categorical": set(),
    },
    "chain": {
        "numeric": {"entity_count"},
        "categorical": {"chain_key"},
    },
    "geo": {
        "numeric": {"latitude", "longitude"},
        "categorical": {"city", "pincode"},
    },
    "source": {
        "numeric": {"suspicious_match"},
        "categorical": {"source_combo"},
    },
}


def make_model(config, scale_pos_weight=1.0):
    model_name = config["model_name"]
    if model_name == "xgboost":
        from xgboost import XGBClassifier
        classifier = XGBClassifier(
            n_estimators=config["xgb_estimators"],
            max_depth=config["xgb_max_depth"],
            learning_rate=config["xgb_learning_rate"],
            scale_pos_weight=scale_pos_weight if config["class_weight"] == "balanced" else 1.0,
            random_state=42,
            n_jobs=1,
            eval_metric="logloss",
        )
    elif model_name == "extra_trees":
        classifier = ExtraTreesClassifier(
            n_estimators=config["n_estimators"],
            min_samples_leaf=config["min_samples_leaf"],
            max_depth=config["max_depth"],
            random_state=42,
            class_weight=config["class_weight"],
            n_jobs=1,
        )
    elif model_name == "random_forest":
        classifier = RandomForestClassifier(
            n_estimators=config["n_estimators"],
            min_samples_leaf=config["min_samples_leaf"],
            max_depth=config["max_depth"],
            random_state=42,
            class_weight=config["class_weight"],
            n_jobs=1,
        )
    else:
        classifier = LogisticRegression(
            max_iter=2500,
            C=config["logreg_c"],
            class_weight=config["class_weight"],
            solver="liblinear",
        )
    return classifier


def build_feature_lists(config):
    num_features = set(BASE_NUMERIC)
    cat_features = set(BASE_CATEGORICAL)
    for group_name, spec in FEATURE_GROUPS.items():
        if not config[f"use_{group_name}"]:
            num_features -= spec["numeric"]
            cat_features -= spec["categorical"]
    num_features = [x for x in sorted(num_features) if x in BASE_NUMERIC]
    cat_features = [x for x in sorted(cat_features) if x in BASE_CATEGORICAL]
    return num_features, cat_features


def build_pipeline(config, scale_pos_weight=1.0):
    num_features, cat_features = build_feature_lists(config)
    transformer_steps = []
    if num_features:
        transformer_steps.append(
            (
                "num",
                Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]),
                num_features,
            )
        )
    if cat_features:
        transformer_steps.append(
            (
                "cat",
                Pipeline(
                    [
                        ("imp", SimpleImputer(strategy="most_frequent")),
                        ("oh", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                cat_features,
            )
        )
    if config.get("use_name_tfidf", False):
        from sklearn.feature_extraction.text import TfidfVectorizer
        transformer_steps.append(
            (
                "tfidf",
                TfidfVectorizer(max_features=config.get("tfidf_max_features", 100)),
                "name_norm",
            )
        )
    preprocessor = ColumnTransformer(transformer_steps)
    features = list(num_features) + list(cat_features)
    if config.get("use_name_tfidf", False):
        features.append("name_norm")
    return Pipeline([("pre", preprocessor), ("clf", make_model(config, scale_pos_weight))]), features


def premium_rule_mask(frame, premium_chain_150, premium_pin_150):
    international = frame["board_international"] == 1
    return international & (
        frame["chain_key"].isin(premium_chain_150) | frame["pincode"].isin(premium_pin_150)
    )


def evaluate_config(df, config):
    y = (df["fee_max"] >= TARGET_THRESHOLD).astype(int)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    all_actual = []
    all_pred = []
    for train_idx, test_idx in skf.split(df, y):
        train_df = df.iloc[train_idx].copy().reset_index(drop=True)
        test_df = df.iloc[test_idx].copy().reset_index(drop=True)
        
        y_train = (train_df["fee_max"] >= TARGET_THRESHOLD).astype(int)
        num_neg = sum(y_train == 0)
        num_pos = sum(y_train == 1)
        scale_pos_weight = num_neg / num_pos if num_pos > 0 else 1.0
        
        pipeline, features = build_pipeline(config, scale_pos_weight)
        pipeline.fit(train_df[features], y_train)
        probabilities = pd.Series(
            pipeline.predict_proba(test_df[features])[:, 1],
            index=test_df.index,
            dtype=float,
        )
        predicted = probabilities >= config["threshold"]
        if config["use_premium_rule"]:
            _, premium_chain_150, _, premium_pin_150 = derive_guardrails(train_df)
            predicted = predicted | premium_rule_mask(test_df, premium_chain_150, premium_pin_150)
        all_actual.extend((test_df["fee_max"] >= TARGET_THRESHOLD).astype(int).tolist())
        all_pred.extend(predicted.astype(int).tolist())
    precision = precision_score(all_actual, all_pred, zero_division=0)
    recall = recall_score(all_actual, all_pred, zero_division=0)
    f1 = f1_score(all_actual, all_pred, zero_division=0)
    accuracy = accuracy_score(all_actual, all_pred)
    predicted_positive = int(sum(all_pred))
    actual_positive = int(sum(all_actual))
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "predicted_positive": predicted_positive,
        "actual_positive": actual_positive,
    }


PARAMETER_SPACE = {
    "model_name": ["extra_trees", "random_forest", "logistic"],
    "n_estimators": [80, 120, 150, 200],
    "min_samples_leaf": [1, 2, 4, 6],
    "max_depth": ["None", "8", "12", "16", "24"],
    "class_weight": ["balanced", "balanced_subsample", "None"],
    "logreg_c": [0.25, 0.5, 1.0, 2.0, 4.0],
    "threshold": [x / 100 for x in range(50, 91, 2)],
    "use_premium_rule": [False, True],
    "use_enrollment": [False, True],
    "use_class_range": [False, True],
    "use_chain": [False, True],
    "use_source": [False, True],
}


class AdaptiveSampler:
    def __init__(self, alpha=0.3, beta=0.2, min_weight=0.05):
        self.alpha = alpha
        self.beta = beta
        self.min_weight = min_weight
        self.weights = {}
        for param, choices in PARAMETER_SPACE.items():
            self.weights[param] = {choice: 1.0 for choice in choices}

    def sample(self, rng):
        config = {}
        for param, choice_weights in self.weights.items():
            population = list(choice_weights.keys())
            weights_list = list(choice_weights.values())
            config[param] = rng.choices(population, weights=weights_list, k=1)[0]
        
        # Parse and handle type dependencies
        if config["max_depth"] == "None":
            max_depth_val = None
        else:
            max_depth_val = int(config["max_depth"])
            
        if config["class_weight"] == "None":
            class_weight_val = None
        else:
            class_weight_val = config["class_weight"]
            
        model_name = config["model_name"]
        if model_name == "logistic":
            if class_weight_val not in ["balanced", None]:
                class_weight_val = rng.choice(["balanced", None])
        elif model_name == "extra_trees":
            class_weight_val = "balanced"
            
        return {
            "model_name": model_name,
            "n_estimators": config["n_estimators"],
            "min_samples_leaf": config["min_samples_leaf"],
            "max_depth": max_depth_val,
            "class_weight": class_weight_val,
            "logreg_c": config["logreg_c"],
            "threshold": config["threshold"],
            "use_premium_rule": config["use_premium_rule"],
            "use_boards": True,
            "use_geo": True,
            "use_enrollment": config["use_enrollment"],
            "use_class_range": config["use_class_range"],
            "use_chain": config["use_chain"],
            "use_source": config["use_source"],
        }

    def update(self, config, metrics, min_predictions, metric_name):
        meets_constraint = metrics["predicted_positive"] >= min_predictions
        metric_value = metrics[metric_name]
        
        max_depth_key = "None" if config["max_depth"] is None else str(config["max_depth"])
        class_weight_key = "None" if config["class_weight"] is None else config["class_weight"]
        
        active_choices = {
            "model_name": config["model_name"],
            "n_estimators": config["n_estimators"],
            "min_samples_leaf": config["min_samples_leaf"],
            "max_depth": max_depth_key,
            "class_weight": class_weight_key,
            "logreg_c": config["logreg_c"],
            "threshold": config["threshold"],
            "use_premium_rule": config["use_premium_rule"],
            "use_enrollment": config["use_enrollment"],
            "use_class_range": config["use_class_range"],
            "use_chain": config["use_chain"],
            "use_source": config["use_source"],
        }
        
        for param, val in active_choices.items():
            if param not in self.weights or val not in self.weights[param]:
                continue
            old_w = self.weights[param][val]
            if meets_constraint:
                new_w = old_w * (1.0 + self.alpha * metric_value)
            else:
                new_w = old_w * (1.0 - self.beta)
            self.weights[param][val] = max(self.min_weight, new_w)



def score_row(row, metric_name, min_predictions=0):
    meets_constraint = int(row["predicted_positive"] >= min_predictions)
    primary = row[metric_name]
    return (
        meets_constraint,
        primary,
        row["precision"],
        row["recall"],
        row["f1"],
        row["accuracy"],
        row["predicted_positive"],
    )



def summarize_effects(results_df, metric_name):
    rows = []
    for field in sorted(
        [x for x in results_df.columns if x.startswith("use_")]
        + ["model_name", "class_weight", "threshold", "min_samples_leaf", "max_depth", "n_estimators"]
    ):
        if field not in results_df.columns:
            continue
        grouped = results_df.groupby(field)[metric_name].agg(["mean", "count"]).reset_index()
        for record in grouped.to_dict(orient="records"):
            rows.append(
                {
                    "factor": field,
                    "value": str(record[field]),
                    "mean_metric": record["mean"],
                    "runs": int(record["count"]),
                }
            )
    return pd.DataFrame(rows).sort_values(["factor", "mean_metric"], ascending=[True, False])


def markdown_table(frame):
    if frame.empty:
        return "_No rows_"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for record in frame.to_dict(orient="records"):
        lines.append("| " + " | ".join(str(record.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--metric", choices=["precision", "recall", "f1", "accuracy"], default="precision")
    parser.add_argument("--target", type=float, default=0.80)
    parser.add_argument("--min-predictions", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    df = build_dataset().copy().reset_index(drop=True)

    sampler = AdaptiveSampler()

    results = []
    best = None
    for iteration in range(1, args.iterations + 1):
        config = sampler.sample(rng)
        metrics = evaluate_config(df, config)
        row = {
            "iteration": iteration,
            "meets_constraint": metrics["predicted_positive"] >= args.min_predictions,
            **config,
            **metrics
        }
        results.append(row)
        if best is None or score_row(row, args.metric, args.min_predictions) > score_row(best, args.metric, args.min_predictions):
            best = row
        print(
            f"iter {iteration:02d} | metric={args.metric} {metrics[args.metric]:.4f} | "
            f"precision={metrics['precision']:.4f} recall={metrics['recall']:.4f} "
            f"pred={metrics['predicted_positive']} constraint={row['meets_constraint']}",
            flush=True,
        )
        sampler.update(config, metrics, args.min_predictions, args.metric)
        if metrics[args.metric] >= args.target and metrics["predicted_positive"] >= args.min_predictions:
            print(f"Target hit at iteration {iteration}.", flush=True)
            break

    results_df = pd.DataFrame(results).sort_values(
        by=["meets_constraint", args.metric, "precision", "recall", "f1", "accuracy", "predicted_positive"],
        ascending=[False, False, False, False, False, False, False],
    )
    factor_df = summarize_effects(results_df, args.metric)

    ITERATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(ITERATION_LOG, index=False)
    factor_df.to_csv(ROOT / "output/premium_optimizer_factor_effects.csv", index=False)

    summary = {
        "rows": len(df),
        "target_metric": args.metric,
        "target_value": args.target,
        "min_predictions": args.min_predictions,
        "iterations_ran": len(results),
        "best_result": best,
        "target_hit": bool(best and best[args.metric] >= args.target and best["predicted_positive"] >= args.min_predictions),
        "top_5": results_df.head(5).to_dict(orient="records"),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with SUMMARY_MD.open("w", encoding="utf-8") as handle:
        handle.write(f"# Premium blind-search summary\n\n")
        handle.write(f"- Dataset rows: {len(df):,}\n")
        handle.write(f"- Optimized metric: `{args.metric}`\n")
        handle.write(f"- Target: `{args.target:.2f}`\n")
        handle.write(f"- Min predictions required: `{args.min_predictions}`\n")
        handle.write(f"- Iterations run: {len(results)}\n")
        handle.write(f"- Target hit: `{summary['target_hit']}`\n\n")
        if best:
            handle.write("## Best configuration\n\n")
            for key in [
                "model_name",
                "threshold",
                "precision",
                "recall",
                "f1",
                "accuracy",
                "predicted_positive",
                "actual_positive",
                "meets_constraint",
                "use_premium_rule",
                "use_boards",
                "use_enrollment",
                "use_class_range",
                "use_chain",
                "use_geo",
                "use_source",
            ]:
                if key in best:
                    handle.write(f"- {key}: {best[key]}\n")
            handle.write("\n## Top 5 runs\n\n")
            handle.write(markdown_table(results_df.head(5)))
            handle.write("\n\n## Factor effects\n\n")
            handle.write(markdown_table(factor_df.head(40)))
            handle.write("\n\n## Learned parameter weights\n\n")
            for param, choice_weights in sorted(sampler.weights.items()):
                handle.write(f"### `{param}`\n\n")
                sorted_choices = sorted(choice_weights.items(), key=lambda x: x[1], reverse=True)
                handle.write("| Choice | Weight |\n| --- | --- |\n")
                for choice, weight in sorted_choices:
                    handle.write(f"| {choice} | {weight:.4f} |\n")
                handle.write("\n")

    print(f"Iteration log: {ITERATION_LOG}")
    print(f"Factor effects: {ROOT / 'output/premium_optimizer_factor_effects.csv'}")
    print(f"Summary JSON: {SUMMARY_JSON}")
    print(f"Summary MD: {SUMMARY_MD}")


if __name__ == "__main__":
    main()
