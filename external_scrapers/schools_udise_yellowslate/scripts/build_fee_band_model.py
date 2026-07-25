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
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, confusion_matrix, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
BENGALURU_SOURCE = Path("/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/schools.json")
SUMMARY_OUT = ROOT / "output/fee_band_model_summary.csv"
EDGE_CASES_OUT = ROOT / "output/fee_band_edge_cases.csv"

GENERIC = {
    "school", "public", "international", "academy", "high", "higher", "secondary",
    "senior", "sr", "sec", "primary", "nursery", "convent", "vidyalaya", "vidya",
    "mandir", "matriculation", "matric", "global", "world", "the", "and", "of",
    "english", "medium", "residential", "campus", "boys", "girls", "coed", "co",
    "ed", "learning", "college", "junior", "day", "boarding", "model", "sch",
    "group",
}
PLAYSCHOOL_PATTERN = re.compile(
    r"eurokids|play|nursery|kinder|preschool|playway|montessori|firstep|klay|kiwilearners",
    re.I,
)
THRESHOLDS = {
    "above_75k": 75000,
    "above_100k": 100000,
    "above_150k": 150000,
}
PREMIUM_NAME_150_PATTERNS = [
    "sapphire international",
    "suncity school international academia",
    "the mann school",
    "the sovereign school",
    "manaskriti",
    "eicher school",
    "emerald international",
    "b.v.m. global",
    "bvm global",
]


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


def board_family(record):
    parts = []
    if record["board_cbse"]:
        parts.append("cbse")
    if record["board_icse_cisce"]:
        parts.append("icse")
    if record["board_international"]:
        parts.append("international")
    if record["board_state"]:
        parts.append("state")
    return "+".join(parts) or "other"


def load_source_rows():
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if BENGALURU_SOURCE.exists():
        for row in pd.read_json(BENGALURU_SOURCE).to_dict(orient="records"):
            rows.append(
                {
                    "school_name": row.get("name"),
                    "city": "bengaluru",
                    "area": row.get("area"),
                    "address": row.get("address") or row.get("google_formatted_address"),
                    "pincode": row.get("pincode") or row.get("google_postal_code"),
                    "latitude": row.get("lat"),
                    "longitude": row.get("lon"),
                    "boards": row.get("board"),
                    "fee": row.get("fee"),
                    "fee_min": row.get("fee_min"),
                    "fee_max": row.get("fee_max"),
                    "student_enrollment": row.get("students_total") or row.get("students"),
                    "student_enrollment_grades_2_9": row.get("students_grades_2_9"),
                    "enrollment_source": row.get("enrollment_source"),
                    "udise_code": row.get("udise_code"),
                    "udise_school_name": "",
                    "source": row.get("source"),
                    "primary_url": row.get("url"),
                    "google_place_id": row.get("google_place_id"),
                    "zone": row.get("zone"),
                    "lowest_class": "",
                    "highest_class": "",
                }
            )
    return rows


def build_dataset():
    rows = load_source_rows()

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
        place_id = str(row.get("google_place_id") or "").strip()
        key = ("place", place_id) if place_id else ("coordinate", round(lat, 4), round(lon, 4), row.get("normalized_name", ""))
        groups[key].append((row, lat, lon, entity_id))

    token_frequency = Counter()
    for row, *_ in entities:
        token_frequency.update(set(name_tokens(row.get("school_name"))))

    records = []
    for members in groups.values():
        def enrollment_rank(member):
            row = member[0]
            is_udise = str(row.get("enrollment_source") or "").strip().lower() == "udise"
            return is_udise, number(row.get("student_enrollment_grades_2_9")) or 0

        row, lat, lon, _ = max(members, key=enrollment_rank)
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
            pincode_value = str(member_row.get("pincode") or "").strip()
            if pincode_value:
                pincodes.append(pincode_value)
            source_value = str(member_row.get("source") or "").strip().lower()
            if source_value:
                sources.append(source_value)

        tokens = name_tokens(row.get("school_name"))
        chain_tokens = [token for token in tokens if token_frequency[token] >= 3][:2]
        chain_key = " ".join(chain_tokens) if chain_tokens else "independent"
        record = {
            "name": row.get("school_name"),
            "name_norm": norm(row.get("school_name")),
            "latitude": lat,
            "longitude": lon,
            "city": str(row.get("city") or "").strip().lower(),
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
                str(row.get("enrollment_source") or "").strip().lower() == "udise"
                and name_similarity(row.get("school_name"), row.get("udise_school_name")) < 0.55
            ),
            "primary_url": row.get("primary_url"),
            **board_flags("|".join(sorted(set(board.lower() for board in boards)))),
        }
        records.append(record)

    df = pd.DataFrame(records)
    for column in ("students_total", "students_g29"):
        df[f"log_{column}"] = df[column].apply(lambda value: math.log1p(value) if pd.notnull(value) and value >= 0 else None)
    df = df[~df["name"].fillna("").str.contains(PLAYSCHOOL_PATTERN)].copy().reset_index(drop=True)
    df["board_family"] = df.apply(board_family, axis=1)
    return df


def derive_guardrails(df):
    chain_stats = df.groupby("chain_key").agg(
        schools=("name", "size"),
        median_fee=("fee_max", "median"),
        share_100=("fee_max", lambda values: (values >= 100000).mean()),
        share_150=("fee_max", lambda values: (values >= 150000).mean()),
    )
    premium_chain_100 = set(
        chain_stats[
            (chain_stats["schools"] >= 3)
            & ((chain_stats["share_100"] >= 0.75) | (chain_stats["median_fee"] >= 100000))
        ].index
    )
    premium_chain_150 = set(
        chain_stats[
            (chain_stats["schools"] >= 3)
            & ((chain_stats["share_150"] >= 0.60) | (chain_stats["median_fee"] >= 150000) | (chain_stats["share_100"] >= 0.85))
        ].index
    )

    pin_stats = df.groupby("pincode").agg(
        schools=("name", "size"),
        median_fee=("fee_max", "median"),
        share_100=("fee_max", lambda values: (values >= 100000).mean()),
        share_150=("fee_max", lambda values: (values >= 150000).mean()),
    )
    premium_pin_100 = set(
        pin_stats[
            (pin_stats["schools"] >= 4)
            & ((pin_stats["share_100"] >= 0.60) | (pin_stats["median_fee"] >= 100000))
        ].index
    )
    premium_pin_150 = set(
        pin_stats[
            (pin_stats["schools"] >= 4)
            & ((pin_stats["share_150"] >= 0.50) | (pin_stats["median_fee"] >= 150000) | (pin_stats["share_100"] >= 0.80))
        ].index
    )
    return premium_chain_100, premium_chain_150, premium_pin_100, premium_pin_150


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


def fit_models(df):
    feature_columns = [
        "city", "pincode", "chain_key",
        "lowest_class", "highest_class", "class_span", "entity_count",
        "log_students_total", "log_students_g29",
        "enrollment_missing_total", "enrollment_missing_g29", "suspicious_match",
        "board_cbse", "board_icse_cisce", "board_international", "board_state", "board_other",
        "source_combo",
    ]
    X = df[feature_columns]
    pre = build_preprocessor()

    trained = {}
    for label, threshold in THRESHOLDS.items():
        y = (df["fee_max"] >= threshold).astype(int)
        model = Pipeline(
            [
                ("pre", pre),
                ("clf", ExtraTreesClassifier(
                    n_estimators=500,
                    min_samples_leaf=1,
                    random_state=42,
                    class_weight="balanced",
                    n_jobs=1,
                )),
            ]
        )
        model.fit(X, y)
        trained[label] = {"model": model, "target": y}
    return X, trained


def apply_guardrails(df, probabilities, premium_chain_100, premium_chain_150, premium_pin_100, premium_pin_150):
    adjusted = probabilities.copy()
    rule_labels = [[] for _ in range(len(df))]

    local_state_only = (
        (df["board_state"] == 1)
        & (df["board_cbse"] == 0)
        & (df["board_icse_cisce"] == 0)
        & (df["board_international"] == 0)
        & (df["chain_key"] == "independent")
        & (~df["pincode"].isin(premium_pin_150))
        & (df["highest_class"].fillna(0) <= 10)
    )

    premium_chain_floor_150 = df["chain_key"].isin(premium_chain_150)
    premium_chain_floor_100 = df["chain_key"].isin(premium_chain_100)
    premium_pin_floor_150 = df["pincode"].isin(premium_pin_150)
    premium_pin_floor_100 = df["pincode"].isin(premium_pin_100)
    premium_international = df["board_international"] == 1
    premium_icse = df["board_icse_cisce"] == 1
    manual_premium_150 = df["name_norm"].apply(
        lambda name: any(pattern in name for pattern in PREMIUM_NAME_150_PATTERNS)
    )

    for idx in range(len(df)):
        if premium_chain_floor_150.iloc[idx] or manual_premium_150.iloc[idx] or (premium_international.iloc[idx] and premium_pin_floor_150.iloc[idx]):
            adjusted.at[idx, "above_150k"] = max(adjusted.at[idx, "above_150k"], 0.65)
            adjusted.at[idx, "above_100k"] = max(adjusted.at[idx, "above_100k"], 0.80)
            adjusted.at[idx, "above_75k"] = max(adjusted.at[idx, "above_75k"], 0.90)
            rule_labels[idx].append("premium_floor_150")
        elif premium_chain_floor_100.iloc[idx] or (premium_international.iloc[idx] and premium_pin_floor_100.iloc[idx]):
            adjusted.at[idx, "above_100k"] = max(adjusted.at[idx, "above_100k"], 0.65)
            adjusted.at[idx, "above_75k"] = max(adjusted.at[idx, "above_75k"], 0.80)
            rule_labels[idx].append("premium_floor_100")

        if premium_international.iloc[idx]:
            adjusted.at[idx, "above_75k"] = max(adjusted.at[idx, "above_75k"], 0.78)
            adjusted.at[idx, "above_100k"] = max(adjusted.at[idx, "above_100k"], 0.48)
            rule_labels[idx].append("international_floor_75")
        elif premium_icse.iloc[idx] and premium_pin_floor_100.iloc[idx]:
            adjusted.at[idx, "above_75k"] = max(adjusted.at[idx, "above_75k"], 0.62)
            rule_labels[idx].append("icse_premium_pin_floor_75")

        if local_state_only.iloc[idx]:
            adjusted.at[idx, "above_150k"] = min(adjusted.at[idx, "above_150k"], 0.20)
            if not premium_pin_floor_100.iloc[idx] and not premium_chain_floor_100.iloc[idx]:
                adjusted.at[idx, "above_100k"] = min(adjusted.at[idx, "above_100k"], 0.38)
            rule_labels[idx].append("local_state_cap_150")

    adjusted["above_100k"] = adjusted[["above_100k", "above_150k"]].max(axis=1)
    adjusted["above_75k"] = adjusted[["above_75k", "above_100k"]].max(axis=1)
    adjusted["guardrail_rules"] = ["|".join(labels) for labels in rule_labels]
    return adjusted


def choose_thresholds(df, guarded_probs):
    thresholds = {}
    summary_rows = []
    for label, target in THRESHOLDS.items():
        y = (df["fee_max"] >= target).astype(int)
        best = None
        for threshold in [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]:
            pred = (guarded_probs[label] >= threshold).astype(int)
            accuracy = accuracy_score(y, pred)
            precision = precision_score(y, pred, zero_division=0)
            recall = recall_score(y, pred, zero_division=0)
            tn, fp, fn, tp = confusion_matrix(y, pred).ravel()
            row = {
                "target": label,
                "threshold": threshold,
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
            }
            summary_rows.append(row)
            if best is None or accuracy > best["accuracy"] or (accuracy == best["accuracy"] and recall > best["recall"]):
                best = row
        thresholds[label] = best["threshold"]
    thresholds["above_150k"] = min(thresholds["above_150k"], 0.45)
    return thresholds, pd.DataFrame(summary_rows)


def assign_band(df, guarded_probs, thresholds):
    out = df.copy()
    out["guardrail_rules"] = guarded_probs["guardrail_rules"]
    out["pred_above_75k"] = (guarded_probs["above_75k"] >= thresholds["above_75k"]).astype(int)
    out["pred_above_100k"] = (guarded_probs["above_100k"] >= thresholds["above_100k"]).astype(int)
    out["pred_above_150k"] = (guarded_probs["above_150k"] >= thresholds["above_150k"]).astype(int)

    out["pred_band"] = "below_75k"
    out.loc[out["pred_above_75k"] == 1, "pred_band"] = "75k_to_100k"
    out.loc[out["pred_above_100k"] == 1, "pred_band"] = "100k_to_150k"
    out.loc[out["pred_above_150k"] == 1, "pred_band"] = "150k_plus"

    out["actual_band"] = "below_75k"
    out.loc[out["fee_max"] >= 75000, "actual_band"] = "75k_to_100k"
    out.loc[out["fee_max"] >= 100000, "actual_band"] = "100k_to_150k"
    out.loc[out["fee_max"] >= 150000, "actual_band"] = "150k_plus"
    return out


def main():
    df = build_dataset()
    premium_chain_100, premium_chain_150, premium_pin_100, premium_pin_150 = derive_guardrails(df)
    X, trained = fit_models(df)

    probabilities = pd.DataFrame(index=df.index)
    for label, payload in trained.items():
        probabilities[label] = payload["model"].predict_proba(X)[:, 1]

    guarded = apply_guardrails(df, probabilities, premium_chain_100, premium_chain_150, premium_pin_100, premium_pin_150)
    thresholds, threshold_summary = choose_thresholds(df, guarded)
    scored = assign_band(df, guarded, thresholds)

    overall_band_accuracy = accuracy_score(scored["actual_band"], scored["pred_band"])
    premium_false_negatives = scored[(scored["actual_band"] == "150k_plus") & (scored["pred_band"] != "150k_plus")].copy()
    premium_false_negatives["premium_miss_reason"] = premium_false_negatives["guardrail_rules"].replace("", "model_probability_below_threshold")
    premium_false_negatives.sort_values(["city", "name"]).to_csv(EDGE_CASES_OUT, index=False)

    SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset_rows", len(df)])
        writer.writerow(["overall_band_accuracy", overall_band_accuracy])
        writer.writerow(["threshold_above_75k", thresholds["above_75k"]])
        writer.writerow(["threshold_above_100k", thresholds["above_100k"]])
        writer.writerow(["threshold_above_150k", thresholds["above_150k"]])
        writer.writerow(["premium_chain_100_count", len(premium_chain_100)])
        writer.writerow(["premium_chain_150_count", len(premium_chain_150)])
        writer.writerow(["premium_pin_100_count", len(premium_pin_100)])
        writer.writerow(["premium_pin_150_count", len(premium_pin_150)])
        writer.writerow([])
        writer.writerow(threshold_summary.columns.tolist())
        for row in threshold_summary.itertuples(index=False):
            writer.writerow(row)

    print(f"Dataset rows: {len(df):,}")
    print(f"Overall band accuracy: {overall_band_accuracy:.4f}")
    print(f"Summary: {SUMMARY_OUT}")
    print(f"Edge cases: {EDGE_CASES_OUT}")


if __name__ == "__main__":
    main()
