#!/usr/bin/env python3
import csv
import hashlib
import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
MODEL_SUMMARY = ROOT / "output/fee_premium_model_summary.csv"
FALSE_NEGATIVES = ROOT / "output/fee_above_150k_false_negatives.csv"

GENERIC = {
    "school", "public", "international", "academy", "high", "higher", "secondary",
    "senior", "sr", "sec", "primary", "nursery", "convent", "vidyalaya", "vidya",
    "mandir", "matriculation", "matric", "global", "world", "the", "and", "of",
    "english", "medium", "residential", "campus", "boys", "girls", "coed", "co",
    "ed", "learning", "college", "junior", "day", "boarding", "model", "sch",
    "group",
}

PLAYSCHOOL_PATTERN = re.compile(
    r"eurokids|play|nursery|kinder|preschool|playway|montessori|firstep",
    re.I,
)


def stable_id(prefix, *parts):
    value = "|".join(str(part or "").strip().lower() for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:14]}"


def number(value):
    try:
        return float(value) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


def norm(text):
    text = (text or "").lower().replace("&amp;", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def name_similarity(left, right):
    left_norm, right_norm = norm(left), norm(right)
    return SequenceMatcher(None, left_norm, right_norm).ratio() if left_norm and right_norm else 0.0


def name_tokens(text):
    return [token for token in norm(text).split() if token and token not in GENERIC and len(token) > 1]


def board_flags(board_text):
    text = (board_text or "").lower()
    has_known = any(
        marker in text for marker in ("cbse", "icse", "cisce", "isc", "ib", "cambridge", "igcse", "international", "state")
    )
    return {
        "board_cbse": int("cbse" in text),
        "board_icse_cisce": int(any(marker in text for marker in ("icse", "cisce", "isc"))),
        "board_international": int(any(marker in text for marker in ("ib", "cambridge", "igcse", "international"))),
        "board_state": int("state" in text),
        "board_other": int(not has_known),
    }


def build_dataset():
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    entities = []
    for row in rows:
        lat, lon = number(row.get("latitude")), number(row.get("longitude"))
        if lat is None or lon is None:
            continue
        entity_id = stable_id(
            "school",
            row.get("udise_code") or row.get("normalized_name"),
            row.get("city"),
            row.get("pincode"),
            row.get("area"),
        )
        entities.append((row, lat, lon, entity_id))

    groups = defaultdict(list)
    for row, lat, lon, entity_id in entities:
        place_id = (row.get("google_place_id") or "").strip()
        key = ("place", place_id) if place_id else ("coordinate", round(lat, 4), round(lon, 4), row.get("normalized_name", ""))
        groups[key].append((row, lat, lon, entity_id))

    token_frequency = Counter()
    for row, *_ in entities:
        token_frequency.update(set(name_tokens(row.get("school_name"))))

    records = []
    for members in groups.values():
        def enrollment_rank(member):
            row = member[0]
            is_udise = (row.get("enrollment_source") or "").strip().lower() == "udise"
            return is_udise, number(row.get("student_enrollment_grades_2_9")) or 0

        row, _, _, _ = max(members, key=enrollment_rank)
        fee_max = max(number(row.get("fee_max")) or 0, number(row.get("fee_min")) or 0, number(row.get("fee")) or 0)
        if fee_max <= 0:
            continue

        boards = []
        lowest_classes = []
        highest_classes = []
        pincodes = []
        sources = []
        for member_row, *_ in members:
            board_text = member_row.get("boards") or ""
            if board_text:
                boards.extend(part.strip() for part in re.split(r"[|,/]", board_text) if part.strip())
            low = number(member_row.get("lowest_class"))
            high = number(member_row.get("highest_class"))
            if low is not None:
                lowest_classes.append(low)
            if high is not None:
                highest_classes.append(high)
            if (member_row.get("pincode") or "").strip():
                pincodes.append((member_row.get("pincode") or "").strip())
            if (member_row.get("source") or "").strip():
                sources.append((member_row.get("source") or "").strip().lower())

        tokens = name_tokens(row.get("school_name"))
        chain_tokens = [token for token in tokens if token_frequency[token] >= 3][:2]
        chain_key = " ".join(chain_tokens) if chain_tokens else "independent"

        record = {
            "name": row.get("school_name"),
            "city": (row.get("city") or "").strip().lower(),
            "pincode": pincodes[0] if pincodes else "missing",
            "chain_key": chain_key,
            "fee_max": fee_max,
            "students_total": number(row.get("student_enrollment")),
            "students_g29": number(row.get("student_enrollment_grades_2_9")),
            "enrollment_missing_total": int(not number(row.get("student_enrollment"))),
            "enrollment_missing_g29": int(not number(row.get("student_enrollment_grades_2_9"))),
            "lowest_class": min(lowest_classes) if lowest_classes else None,
            "highest_class": max(highest_classes) if highest_classes else None,
            "class_span": (max(highest_classes) - min(lowest_classes) + 1) if lowest_classes and highest_classes else None,
            "entity_count": len(members),
            "source_combo": "+".join(sorted(set(sources))) if sources else "unknown",
            "suspicious_match": int(
                (row.get("enrollment_source") or "").strip().lower() == "udise"
                and name_similarity(row.get("school_name"), row.get("udise_school_name")) < 0.55
            ),
            "primary_url": row.get("primary_url"),
            **board_flags("|".join(sorted(set(board.lower() for board in boards)))),
        }
        records.append(record)

    df = pd.DataFrame(records)
    for column in ("students_total", "students_g29"):
        df[f"log_{column}"] = df[column].apply(lambda value: math.log1p(value) if pd.notnull(value) and value >= 0 else None)

    return df[~df["chain_key"].str.contains(PLAYSCHOOL_PATTERN, na=False)].copy()


def build_preprocessor():
    num_features = [
        "lowest_class", "highest_class", "class_span", "entity_count",
        "log_students_total", "log_students_g29",
        "enrollment_missing_total", "enrollment_missing_g29", "suspicious_match",
        "board_cbse", "board_icse_cisce", "board_international", "board_state", "board_other",
    ]
    cat_features = ["city", "pincode", "chain_key", "source_combo"]
    return ColumnTransformer(
        [
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), num_features),
            ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")), ("oh", OneHotEncoder(handle_unknown="ignore"))]), cat_features),
        ]
    )


def evaluate_models(df):
    features = [
        "city", "pincode", "chain_key",
        "lowest_class", "highest_class", "class_span", "entity_count",
        "log_students_total", "log_students_g29",
        "enrollment_missing_total", "enrollment_missing_g29", "suspicious_match",
        "board_cbse", "board_icse_cisce", "board_international", "board_state", "board_other",
        "source_combo",
    ]
    X = df[features]
    y = (df["fee_max"] >= 150000).astype(int)

    pre = build_preprocessor()
    models = {
        "logistic": LogisticRegression(max_iter=3000, class_weight="balanced"),
        "decision_tree": DecisionTreeClassifier(random_state=42, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            min_samples_leaf=1,
            random_state=42,
            class_weight="balanced_subsample",
            n_jobs=1,
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=400,
            min_samples_leaf=1,
            random_state=42,
            class_weight="balanced",
            n_jobs=1,
        ),
    }

    summary_rows = []
    fitted_models = {}
    for name, classifier in models.items():
        pipeline = Pipeline([("pre", pre), ("clf", classifier)])
        pipeline.fit(X, y)
        predictions = pipeline.predict(X)
        tn, fp, fn, tp = confusion_matrix(y, predictions).ravel()
        summary_rows.append(
            {
                "model": name,
                "accuracy": accuracy_score(y, predictions),
                "precision": precision_score(y, predictions, zero_division=0),
                "recall": recall_score(y, predictions, zero_division=0),
                "f1": f1_score(y, predictions, zero_division=0),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
            }
        )
        fitted_models[name] = pipeline

    summary = pd.DataFrame(summary_rows).sort_values(["accuracy", "recall"], ascending=False)
    return X, y, summary, fitted_models


def export_false_negatives(df, X, y, model):
    probabilities = model.predict_proba(X)[:, 1]
    threshold_rows = []
    for threshold in (0.50, 0.45, 0.40, 0.35, 0.30):
        predictions = (probabilities >= threshold).astype(int)
        tn, fp, fn, tp = confusion_matrix(y, predictions).ravel()
        threshold_rows.append(
            {
                "threshold": threshold,
                "accuracy": accuracy_score(y, predictions),
                "precision": precision_score(y, predictions, zero_division=0),
                "recall": recall_score(y, predictions, zero_division=0),
                "f1": f1_score(y, predictions, zero_division=0),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
            }
        )

    best_threshold = 0.40
    predictions = (probabilities >= best_threshold).astype(int)
    false_negatives = df[(y == 1) & (predictions == 0)].copy()
    false_negatives["predicted_probability_above_150k"] = probabilities[(y == 1) & (predictions == 0)]
    false_negatives.sort_values("predicted_probability_above_150k").to_csv(FALSE_NEGATIVES, index=False)
    return pd.DataFrame(threshold_rows)


def main():
    df = build_dataset()
    X, y, model_summary, models = evaluate_models(df)
    threshold_summary = export_false_negatives(df, X, y, models["random_forest"])

    MODEL_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with MODEL_SUMMARY.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset_rows", len(df)])
        writer.writerow(["positive_above_150k", int(y.sum())])
        writer.writerow([])
        writer.writerow(model_summary.columns.tolist())
        for row in model_summary.itertuples(index=False):
            writer.writerow(row)
        writer.writerow([])
        writer.writerow(["threshold_tuning_for_random_forest"])
        writer.writerow(threshold_summary.columns.tolist())
        for row in threshold_summary.itertuples(index=False):
            writer.writerow(row)

    print(f"Dataset rows: {len(df):,}")
    print(f"Premium schools (fee_max >= 150000): {int(y.sum()):,}")
    print(f"Model summary: {MODEL_SUMMARY}")
    print(f"False negatives: {FALSE_NEGATIVES}")


if __name__ == "__main__":
    main()
