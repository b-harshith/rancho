#!/usr/bin/env python3
"""
Spatial budget scoring and conservative ultra-premium refinement for Stage 1.5
H3 resolution 7 evidence cells.

This script is additive: it does not rewrite the Stage 1.5 evidence layer.
It writes a derived analytical layer with spatial lag features, premium
candidate scores, refined labels, Moran's I tests, join-count tests, and
dataset audit summaries.
"""

from __future__ import annotations

import copy
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import h3
import numpy as np


DATA_DIR = Path("DATA")
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIT_DIR = DATA_DIR / "audits"

INPUT_JSON = PROCESSED_DATA_DIR / "stage1_5_hex7_features.json"
OUTPUT_JSON = PROCESSED_DATA_DIR / "stage1_5_hex7_spatial_budget_features.json"
OUTPUT_CSV = PROCESSED_DATA_DIR / "stage1_5_hex7_spatial_budget_features_flat.csv"
AUDIT_JSON = AUDIT_DIR / "stage1_5_spatial_budget_audit.json"
REPORT_MD = AUDIT_DIR / "stage1_5_spatial_budget_report.md"

SEGMENTS = ("Affordable", "Mid-Segment", "Premium")
NEIGHBOR_K = 1
BASE_DIRECT_WEIGHT = 0.70
BASE_SPATIAL_WEIGHT = 0.30
MORANS_PERMUTATIONS = 4999
JOIN_COUNT_PERMUTATIONS = 4999
RANDOM_SEED = 42


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def clean_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def metric_value(record: dict[str, Any], metric: str) -> float | None:
    metrics = safe_dict(safe_dict(record.get("market_insights")).get("metrics"))
    return clean_float(safe_dict(metrics.get(metric)).get("weighted_avg"))


def support_weight(record: dict[str, Any]) -> float:
    support = safe_dict(safe_dict(record.get("market_insights")).get("support"))
    return clean_float(support.get("total_support_weight"), 0.0) or 0.0


def quality_flags(record: dict[str, Any]) -> list[str]:
    flags = safe_dict(record.get("quality")).get("flags") or []
    return list(flags) if isinstance(flags, list) else []


def is_in_bounds(record: dict[str, Any]) -> bool:
    return not quality_flags(record)


def budget_shares(record: dict[str, Any]) -> dict[str, float]:
    shares = safe_dict(record.get("budget_segments"))
    return {segment: clean_float(shares.get(segment), 0.0) or 0.0 for segment in SEGMENTS}


def dominant_from_shares(shares: dict[str, float]) -> tuple[str, float]:
    segment = max(SEGMENTS, key=lambda item: shares.get(item, 0.0))
    return segment, shares.get(segment, 0.0)


def classify_from_shares(shares: dict[str, float]) -> str:
    segment, share = dominant_from_shares(shares)
    if share >= 0.60:
        return segment
    if share >= 0.45:
        return f"Mixed - {segment} leaning"
    return "Mixed/Diverse"


def normalize(value: float | None, low: float | None, high: float | None) -> float:
    if value is None or low is None or high is None or high <= low:
        return 0.0
    return clamp((value - low) / (high - low))


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.array(values, dtype=float), pct))


def percentile_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {f"p{pct}": None for pct in (0, 10, 25, 50, 75, 90, 95, 100)}
    arr = np.array(values, dtype=float)
    return {
        f"p{pct}": float(np.percentile(arr, pct))
        for pct in (0, 10, 25, 50, 75, 90, 95, 100)
    }


def load_records() -> list[dict[str, Any]]:
    with INPUT_JSON.open("r", encoding="utf-8") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise ValueError(f"{INPUT_JSON} must contain a top-level array.")
    return records


def neighbor_cells(record: dict[str, Any], cell_set: set[str]) -> list[str]:
    cell = record["hex_id"]
    return sorted(
        neighbor
        for neighbor in h3.grid_disk(cell, NEIGHBOR_K)
        if neighbor != cell and neighbor in cell_set
    )


def weighted_neighbor_shares(
    neighbors: list[str],
    by_cell: dict[str, dict[str, Any]],
) -> tuple[dict[str, float], float]:
    accum = defaultdict(float)
    total_weight = 0.0
    for neighbor in neighbors:
        record = by_cell[neighbor]
        weight = support_weight(record)
        if weight <= 0:
            weight = 1.0
        total_weight += weight
        for segment, share in budget_shares(record).items():
            accum[segment] += share * weight

    if total_weight <= 0:
        return {segment: 0.0 for segment in SEGMENTS}, 0.0
    return {segment: accum[segment] / total_weight for segment in SEGMENTS}, total_weight


def spatial_weight_factor(neighbor_count: int, neighbor_support: float) -> tuple[float, dict[str, float]]:
    neighbor_count_factor = clamp(neighbor_count / 3.0)
    support_factor = clamp(math.log1p(max(0.0, neighbor_support)) / math.log1p(100.0))
    spatial_weight = BASE_SPATIAL_WEIGHT * neighbor_count_factor * support_factor
    return spatial_weight, {
        "neighbor_count_factor": neighbor_count_factor,
        "neighbor_support_factor": support_factor,
    }


def blended_shares(direct: dict[str, float], spatial: dict[str, float], spatial_weight: float) -> dict[str, float]:
    direct_weight = 1.0 - spatial_weight
    raw = {
        segment: direct_weight * direct.get(segment, 0.0)
        + spatial_weight * spatial.get(segment, 0.0)
        for segment in SEGMENTS
    }
    total = sum(raw.values())
    if total <= 0:
        return {segment: 0.0 for segment in SEGMENTS}
    return {segment: raw[segment] / total for segment in SEGMENTS}


def candidate_score(
    record: dict[str, Any],
    direct_shares: dict[str, float],
    spatial_premium_lag: float,
    premium_cluster_score: float,
    thresholds: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    price = metric_value(record, "market_price_per_sqft")
    lens = metric_value(record, "premium_lens_score") or 0.0
    price_score = normalize(price, thresholds["price_p75"], thresholds["price_p95"])
    lens_score = clamp(lens / thresholds["premium_lens_p95"]) if thresholds["premium_lens_p95"] else 0.0
    direct_premium_share = direct_shares.get("Premium", 0.0)
    cluster_score = clamp(premium_cluster_score)
    score = (
        0.35 * direct_premium_share
        + 0.25 * price_score
        + 0.20 * lens_score
        + 0.20 * cluster_score
    )
    components = {
        "direct_premium_share": direct_premium_share,
        "price_score": price_score,
        "premium_lens_score_normalized": lens_score,
        "spatial_premium_lag": spatial_premium_lag,
        "premium_cluster_score": cluster_score,
    }
    return clamp(score), components


def refine_label(
    record: dict[str, Any],
    direct_shares: dict[str, float],
    spatial_shares: dict[str, float],
    score: float,
    components: dict[str, float],
    thresholds: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    direct_class = record.get("budget_classification") or "unknown"
    direct_premium = direct_shares.get("Premium", 0.0)
    spatial_premium = spatial_shares.get("Premium", 0.0)
    price = metric_value(record, "market_price_per_sqft")
    support = support_weight(record)
    flagged = bool(quality_flags(record))

    ultra_gate = (
        not flagged
        and price is not None
        and price >= thresholds["price_p90"]
        and score >= 0.65
        and max(direct_premium, spatial_premium) >= 0.55
        and support >= 20.0
        and (
            components["premium_lens_score_normalized"] >= 0.40
            or components["premium_cluster_score"] >= 0.15
            or components["spatial_premium_lag"] >= 0.30
        )
    )
    if ultra_gate:
        return "Ultra Premium", [
            "price_above_p90",
            "strong_premium_candidate_score",
            "strong_premium_share",
            "sufficient_support",
        ]

    if direct_class == "Mixed - Premium leaning":
        reasons.append("mixed_premium_leaning_default_candidate")
        return "Premium Candidate", reasons

    if direct_class == "Mixed - Mid-Segment leaning":
        triggers = []
        if direct_premium >= 0.25:
            triggers.append("meaningful_direct_premium_share")
        if components["price_score"] >= 0.50:
            triggers.append("high_price_signal")
        if components["premium_lens_score_normalized"] >= 0.60:
            triggers.append("strong_premium_lens")
        if components["spatial_premium_lag"] >= 0.35:
            triggers.append("nearby_premium_pressure")
        if score >= 0.50:
            triggers.append("premium_candidate_score")
        if triggers:
            return "Premium Candidate", triggers

    if direct_class not in {"Premium", "Ultra Premium"}:
        if score >= 0.60 and components["spatial_premium_lag"] >= 0.35:
            return "Premium Candidate", ["high_candidate_score_with_nearby_premium_pressure"]

    return direct_class, ["kept_direct_evidence_label"]


def conflict_flags(
    record: dict[str, Any],
    direct_shares: dict[str, float],
    spatial_premium_lag: float,
    components: dict[str, float],
    thresholds: dict[str, Any],
) -> list[str]:
    flags = []
    price = metric_value(record, "market_price_per_sqft")
    direct_class = record.get("budget_classification") or ""
    direct_premium = direct_shares.get("Premium", 0.0)

    if (
        direct_class in {"Premium", "Mixed - Premium leaning"}
        and price is not None
        and thresholds["price_p50"] is not None
        and price < thresholds["price_p50"]
    ):
        flags.append("premium_label_below_median_price")
    if direct_class == "Premium" and spatial_premium_lag < 0.15:
        flags.append("premium_label_spatially_isolated")
    if (
        price is not None
        and thresholds["price_p90"] is not None
        and price >= thresholds["price_p90"]
        and direct_premium < 0.30
        and spatial_premium_lag < 0.30
    ):
        flags.append("high_price_low_premium_evidence")
    if (
        direct_class not in {"Premium", "Mixed - Premium leaning"}
        and spatial_premium_lag >= 0.50
        and components["price_score"] >= 0.50
    ):
        flags.append("nearby_premium_pressure_not_in_direct_label")
    return flags


def derive_thresholds(records: list[dict[str, Any]]) -> dict[str, Any]:
    in_bounds = [record for record in records if is_in_bounds(record)]
    prices = [
        metric_value(record, "market_price_per_sqft")
        for record in in_bounds
        if metric_value(record, "market_price_per_sqft") is not None
    ]
    premium_lens = [
        metric_value(record, "premium_lens_score") or 0.0
        for record in in_bounds
    ]
    return {
        "price_distribution": percentile_summary(prices),
        "premium_lens_distribution": percentile_summary(premium_lens),
        "price_p50": percentile(prices, 50),
        "price_p75": percentile(prices, 75),
        "price_p90": percentile(prices, 90),
        "price_p95": percentile(prices, 95),
        "premium_lens_p75": percentile(premium_lens, 75),
        "premium_lens_p90": percentile(premium_lens, 90),
        "premium_lens_p95": percentile(premium_lens, 95),
    }


def enrich_records(records: list[dict[str, Any]], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    by_cell = {record["hex_id"]: record for record in records}
    cell_set = set(by_cell)
    enriched = []

    for record in records:
        out = copy.deepcopy(record)
        neighbors = neighbor_cells(record, cell_set)
        neighbor_shares, neighbor_support = weighted_neighbor_shares(neighbors, by_cell)
        spatial_weight, confidence_components = spatial_weight_factor(len(neighbors), neighbor_support)
        direct = budget_shares(record)
        spatial_segments = blended_shares(direct, neighbor_shares, spatial_weight)
        direct_segment = record.get("dominant_budget_segment") or dominant_from_shares(direct)[0]
        local_agreement = neighbor_shares.get(direct_segment, 0.0)
        spatial_confidence = clamp(
            0.50 * local_agreement
            + 0.25 * confidence_components["neighbor_count_factor"]
            + 0.25 * confidence_components["neighbor_support_factor"]
        )
        spatial_premium_lag = neighbor_shares.get("Premium", 0.0)
        premium_cluster_score = direct.get("Premium", 0.0) * spatial_premium_lag
        score, components = candidate_score(
            record,
            direct,
            spatial_premium_lag,
            premium_cluster_score,
            thresholds,
        )
        refined, reasons = refine_label(
            record,
            direct,
            spatial_segments,
            score,
            components,
            thresholds,
        )
        flags = conflict_flags(record, direct, spatial_premium_lag, components, thresholds)

        scoring = {
            "neighbor_k": NEIGHBOR_K,
            "neighbor_hex_count": len(neighbors),
            "neighbor_hexes": neighbors,
            "neighbor_support_weight": neighbor_support,
            "direct_weight": 1.0 - spatial_weight,
            "spatial_weight": spatial_weight,
            "neighbor_budget_segments": neighbor_shares,
            "spatial_budget_segments": spatial_segments,
            "spatial_premium_lag": spatial_premium_lag,
            "premium_cluster_score": premium_cluster_score,
            "spatial_confidence": spatial_confidence,
            "spatial_confidence_components": {
                **confidence_components,
                "local_agreement_with_direct_segment": local_agreement,
            },
            "premium_candidate_score": score,
            "premium_candidate_components": components,
            "refined_budget_segment": refined,
            "refinement_reasons": reasons,
            "spatial_conflict_flags": flags,
        }
        out["spatial_budget_scoring"] = scoring
        out["spatial_budget_segments"] = spatial_segments
        out["spatial_premium_lag"] = spatial_premium_lag
        out["premium_cluster_score"] = premium_cluster_score
        out["spatial_confidence"] = spatial_confidence
        out["premium_candidate_score"] = score
        out["refined_budget_segment"] = refined
        out["spatial_conflict_flags"] = flags
        enriched.append(out)

    return sorted(enriched, key=lambda item: item["hex_id"])


def edge_list(records: list[dict[str, Any]]) -> list[tuple[str, str]]:
    cells = [record["hex_id"] for record in records]
    cell_set = set(cells)
    edges = set()
    for cell in cells:
        for neighbor in h3.grid_disk(cell, NEIGHBOR_K):
            if neighbor != cell and neighbor in cell_set:
                edges.add(tuple(sorted((cell, neighbor))))
    return sorted(edges)


def weight_matrix(records: list[dict[str, Any]]) -> tuple[np.ndarray, int, float]:
    cells = [record["hex_id"] for record in records]
    cell_set = set(cells)
    idx = {cell: i for i, cell in enumerate(cells)}
    matrix = np.zeros((len(cells), len(cells)), dtype=float)
    rows_with_neighbors = 0
    for cell in cells:
        neighbors = [
            neighbor
            for neighbor in h3.grid_disk(cell, NEIGHBOR_K)
            if neighbor != cell and neighbor in cell_set
        ]
        if not neighbors:
            continue
        rows_with_neighbors += 1
        row_weight = 1.0 / len(neighbors)
        for neighbor in neighbors:
            matrix[idx[cell], idx[neighbor]] = row_weight
    return matrix, rows_with_neighbors, float(matrix.sum())


def morans_i(
    records: list[dict[str, Any]],
    values: list[float],
    permutations: int = MORANS_PERMUTATIONS,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    n = len(records)
    matrix, rows_with_neighbors, weight_sum = weight_matrix(records)
    x = np.array(values, dtype=float)
    z = x - np.mean(x)
    denominator = float(np.sum(z**2))
    expected = -1.0 / (n - 1) if n > 1 else math.nan
    if denominator == 0.0 or weight_sum == 0.0:
        return {
            "n_hexes": n,
            "moran_i": None,
            "expected_i": expected,
            "z_score": None,
            "p_value_two_sided": None,
            "p_value_greater": None,
            "rows_with_neighbors": rows_with_neighbors,
            "weight_sum": weight_sum,
            "permutations": permutations,
        }

    observed = float((n / weight_sum) * (z @ matrix @ z) / denominator)
    rng = np.random.default_rng(seed)
    sims = np.empty(permutations, dtype=float)
    for i in range(permutations):
        zp = rng.permutation(z)
        sims[i] = float((n / weight_sum) * (zp @ matrix @ zp) / denominator)

    mean = float(np.mean(sims))
    sd = float(np.std(sims, ddof=1)) if permutations > 1 else math.nan
    centered_observed = abs(observed - mean)
    z_score = (observed - mean) / sd if sd > 0 else math.nan
    return {
        "n_hexes": n,
        "moran_i": observed,
        "expected_i": expected,
        "permutation_mean": mean,
        "permutation_sd": sd,
        "z_score": float(z_score),
        "p_value_two_sided": float(
            (np.sum(np.abs(sims - mean) >= centered_observed) + 1) / (permutations + 1)
        ),
        "p_value_greater": float((np.sum(sims >= observed) + 1) / (permutations + 1)),
        "rows_with_neighbors": rows_with_neighbors,
        "weight_sum": weight_sum,
        "permutations": permutations,
    }


def join_count(
    records: list[dict[str, Any]],
    labels: list[str],
    permutations: int = JOIN_COUNT_PERMUTATIONS,
    seed: int = RANDOM_SEED + 1,
) -> dict[str, Any]:
    cells = [record["hex_id"] for record in records]
    edges = edge_list(records)
    if not edges:
        return {"edges": 0, "observed_same_fraction": None}
    label_by_cell = {cells[i]: labels[i] for i in range(len(cells))}
    observed_same = sum(1 for a, b in edges if label_by_cell[a] == label_by_cell[b])
    observed_fraction = observed_same / len(edges)
    label_array = np.array(labels, dtype=object)
    rng = np.random.default_rng(seed)
    sims = np.empty(permutations, dtype=float)
    for i in range(permutations):
        permuted = rng.permutation(label_array)
        permuted_by_cell = {cells[j]: permuted[j] for j in range(len(cells))}
        sims[i] = sum(1 for a, b in edges if permuted_by_cell[a] == permuted_by_cell[b]) / len(edges)
    mean = float(np.mean(sims))
    sd = float(np.std(sims, ddof=1)) if permutations > 1 else math.nan
    return {
        "edges": len(edges),
        "observed_same_edges": observed_same,
        "observed_same_fraction": observed_fraction,
        "permutation_mean": mean,
        "permutation_sd": sd,
        "z_score": float((observed_fraction - mean) / sd) if sd > 0 else None,
        "p_value_greater": float((np.sum(sims >= observed_fraction) + 1) / (permutations + 1)),
        "permutations": permutations,
    }


def moran_inputs(records: list[dict[str, Any]]) -> dict[str, tuple[list[dict[str, Any]], list[float]]]:
    inputs: dict[str, tuple[list[dict[str, Any]], list[float]]] = {}
    for segment in SEGMENTS:
        inputs[f"direct_budget_share_{segment.lower().replace('-', '_')}"] = (
            records,
            [budget_shares(record).get(segment, 0.0) for record in records],
        )
        inputs[f"spatial_budget_share_{segment.lower().replace('-', '_')}"] = (
            records,
            [safe_dict(record.get("spatial_budget_segments")).get(segment, 0.0) for record in records],
        )
    for metric in ("market_price_per_sqft", "premium_lens_score", "activity_score"):
        valid = [record for record in records if metric_value(record, metric) is not None]
        if valid:
            inputs[metric] = (valid, [metric_value(record, metric) or 0.0 for record in valid])
    inputs["premium_candidate_score"] = (
        records,
        [clean_float(record.get("premium_candidate_score"), 0.0) or 0.0 for record in records],
    )
    inputs["premium_cluster_score"] = (
        records,
        [clean_float(record.get("premium_cluster_score"), 0.0) or 0.0 for record in records],
    )
    return inputs


def run_spatial_tests(records: list[dict[str, Any]]) -> dict[str, Any]:
    all_results = {}
    in_bounds = [record for record in records if is_in_bounds(record)]
    for scope_name, scope_records in (("all_records", records), ("in_bounds_only", in_bounds)):
        moran_results = {}
        for metric, (metric_records, values) in moran_inputs(scope_records).items():
            if len(metric_records) >= 10:
                moran_results[metric] = morans_i(metric_records, values)

        all_results[scope_name] = {
            "record_count": len(scope_records),
            "edge_count": len(edge_list(scope_records)),
            "morans_i": moran_results,
            "join_count": {
                "original_budget_classification": join_count(
                    scope_records,
                    [str(record.get("budget_classification")) for record in scope_records],
                ),
                "refined_budget_segment": join_count(
                    scope_records,
                    [str(record.get("refined_budget_segment")) for record in scope_records],
                ),
            },
        }
    return all_results


def classification_changes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes = []
    for record in records:
        original = record.get("budget_classification")
        refined = record.get("refined_budget_segment")
        if original == refined:
            continue
        changes.append(
            {
                "hex_id": record["hex_id"],
                "name": record.get("name"),
                "original": original,
                "refined": refined,
                "premium_candidate_score": record.get("premium_candidate_score"),
                "spatial_premium_lag": record.get("spatial_premium_lag"),
                "premium_cluster_score": record.get("premium_cluster_score"),
                "price_per_sqft": metric_value(record, "market_price_per_sqft"),
                "support_weight": support_weight(record),
                "reasons": safe_dict(record.get("spatial_budget_scoring")).get("refinement_reasons"),
            }
        )
    return sorted(
        changes,
        key=lambda item: (
            str(item["refined"]) != "Ultra Premium",
            -(item.get("premium_candidate_score") or 0),
        ),
    )


def audit_payload(
    original_records: list[dict[str, Any]],
    enriched_records: list[dict[str, Any]],
    thresholds: dict[str, Any],
    spatial_tests: dict[str, Any],
) -> dict[str, Any]:
    in_bounds = [record for record in enriched_records if is_in_bounds(record)]
    changes = classification_changes(enriched_records)
    conflict_examples = [
        {
            "hex_id": record["hex_id"],
            "name": record.get("name"),
            "budget_classification": record.get("budget_classification"),
            "refined_budget_segment": record.get("refined_budget_segment"),
            "flags": record.get("spatial_conflict_flags"),
            "price_per_sqft": metric_value(record, "market_price_per_sqft"),
            "premium_share": budget_shares(record).get("Premium"),
            "spatial_premium_lag": record.get("spatial_premium_lag"),
            "premium_candidate_score": record.get("premium_candidate_score"),
        }
        for record in enriched_records
        if record.get("spatial_conflict_flags")
    ]

    return {
        "input": str(INPUT_JSON),
        "outputs": {
            "json": str(OUTPUT_JSON),
            "csv": str(OUTPUT_CSV),
            "report": str(REPORT_MD),
        },
        "method": {
            "neighbor_k": NEIGHBOR_K,
            "base_direct_weight": BASE_DIRECT_WEIGHT,
            "base_spatial_weight": BASE_SPATIAL_WEIGHT,
            "spatial_weight_damping": "0.30 * min(neighbor_count/3, 1) * min(log1p(neighbor_support)/log1p(100), 1)",
            "premium_candidate_score": "0.35 direct premium share + 0.25 price score + 0.20 normalized premium lens + 0.20 premium cluster score",
            "ultra_premium_rule": "No quality flags, price >= p90, score >= 0.65, premium share >= 0.55, support >= 20, and at least one premium spatial/lens signal.",
        },
        "thresholds": thresholds,
        "source_counts": {
            "records": len(original_records),
            "in_bounds_records": len(in_bounds),
            "quality_flagged_records": len(original_records) - len(in_bounds),
            "edge_count_all": len(edge_list(enriched_records)),
            "edge_count_in_bounds": len(edge_list(in_bounds)),
        },
        "classification_counts": {
            "original": dict(Counter(record.get("budget_classification") for record in enriched_records)),
            "refined": dict(Counter(record.get("refined_budget_segment") for record in enriched_records)),
            "original_in_bounds": dict(Counter(record.get("budget_classification") for record in in_bounds)),
            "refined_in_bounds": dict(Counter(record.get("refined_budget_segment") for record in in_bounds)),
        },
        "classification_change_count": len(changes),
        "classification_change_examples": changes[:40],
        "ultra_premium_candidates": [
            item for item in changes if item["refined"] == "Ultra Premium"
        ],
        "spatial_conflict_count": len(conflict_examples),
        "spatial_conflict_examples": conflict_examples[:40],
        "spatial_tests": spatial_tests,
    }


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    direct = budget_shares(record)
    spatial = safe_dict(record.get("spatial_budget_segments"))
    scoring = safe_dict(record.get("spatial_budget_scoring"))
    components = safe_dict(scoring.get("premium_candidate_components"))
    support = safe_dict(safe_dict(record.get("market_insights")).get("support"))
    return {
        "hex_id": record.get("hex_id"),
        "name": record.get("name"),
        "budget_classification": record.get("budget_classification"),
        "refined_budget_segment": record.get("refined_budget_segment"),
        "dominant_budget_segment": record.get("dominant_budget_segment"),
        "direct_affordable_share": direct.get("Affordable"),
        "direct_mid_segment_share": direct.get("Mid-Segment"),
        "direct_premium_share": direct.get("Premium"),
        "spatial_affordable_share": spatial.get("Affordable"),
        "spatial_mid_segment_share": spatial.get("Mid-Segment"),
        "spatial_premium_share": spatial.get("Premium"),
        "spatial_premium_lag": record.get("spatial_premium_lag"),
        "premium_cluster_score": record.get("premium_cluster_score"),
        "spatial_confidence": record.get("spatial_confidence"),
        "premium_candidate_score": record.get("premium_candidate_score"),
        "price_score": components.get("price_score"),
        "premium_lens_score_normalized": components.get("premium_lens_score_normalized"),
        "neighbor_hex_count": scoring.get("neighbor_hex_count"),
        "neighbor_support_weight": scoring.get("neighbor_support_weight"),
        "direct_weight": scoring.get("direct_weight"),
        "spatial_weight": scoring.get("spatial_weight"),
        "market_price_per_sqft": metric_value(record, "market_price_per_sqft"),
        "premium_lens_score": metric_value(record, "premium_lens_score"),
        "activity_score": metric_value(record, "activity_score"),
        "support_weight": support.get("total_support_weight"),
        "locality_count": support.get("locality_count"),
        "quality_flags": ", ".join(quality_flags(record)),
        "spatial_conflict_flags": ", ".join(record.get("spatial_conflict_flags") or []),
        "refinement_reasons": ", ".join(scoring.get("refinement_reasons") or []),
    }


def write_outputs(enriched_records: list[dict[str, Any]], audit: dict[str, Any]) -> None:
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    OUTPUT_JSON.write_text(json.dumps(enriched_records, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = [flatten_record(record) for record in enriched_records]
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    AUDIT_JSON.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT_MD.write_text(render_report(audit), encoding="utf-8")


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(audit: dict[str, Any]) -> str:
    tests = audit["spatial_tests"]["in_bounds_only"]
    moran = tests["morans_i"]
    refined_join = tests["join_count"]["refined_budget_segment"]
    original_join = tests["join_count"]["original_budget_classification"]
    lines = [
        "# Stage 1.5 Spatial Budget Audit",
        "",
        "## Summary",
        f"- Input records: {audit['source_counts']['records']}",
        f"- In-bound records: {audit['source_counts']['in_bounds_records']}",
        f"- Quality-flagged records: {audit['source_counts']['quality_flagged_records']}",
        f"- Classification changes: {audit['classification_change_count']}",
        f"- Spatial conflicts flagged: {audit['spatial_conflict_count']}",
        "",
        "## Classification Counts",
        f"- Original: `{audit['classification_counts']['original']}`",
        f"- Refined: `{audit['classification_counts']['refined']}`",
        "",
        "## Key Moran's I Results (In-Bounds)",
    ]
    for metric in (
        "direct_budget_share_affordable",
        "direct_budget_share_premium",
        "market_price_per_sqft",
        "premium_lens_score",
        "premium_candidate_score",
        "premium_cluster_score",
    ):
        if metric in moran:
            result = moran[metric]
            lines.append(
                f"- {metric}: I={fmt(result.get('moran_i'))}, "
                f"z={fmt(result.get('z_score'))}, p={fmt(result.get('p_value_two_sided'))}"
            )
    lines.extend(
        [
            "",
            "## Join Count",
            (
                f"- Original labels: same-edge fraction={fmt(original_join.get('observed_same_fraction'))}, "
                f"p={fmt(original_join.get('p_value_greater'))}"
            ),
            (
                f"- Refined labels: same-edge fraction={fmt(refined_join.get('observed_same_fraction'))}, "
                f"p={fmt(refined_join.get('p_value_greater'))}"
            ),
            "",
            "## Ultra Premium Candidates",
        ]
    )
    ultra = audit.get("ultra_premium_candidates") or []
    if not ultra:
        lines.append("- None under the conservative gate.")
    else:
        for item in ultra:
            lines.append(
                f"- {item['name']} (`{item['hex_id']}`): price={fmt(item.get('price_per_sqft'), 0)}, "
                f"score={fmt(item.get('premium_candidate_score'))}, support={fmt(item.get('support_weight'), 1)}"
            )
    lines.extend(["", "## Top Classification Changes"])
    for item in audit.get("classification_change_examples", [])[:20]:
        lines.append(
            f"- {item['name']} (`{item['hex_id']}`): {item['original']} -> {item['refined']}; "
            f"score={fmt(item.get('premium_candidate_score'))}, lag={fmt(item.get('spatial_premium_lag'))}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    records = load_records()
    thresholds = derive_thresholds(records)
    enriched_records = enrich_records(records, thresholds)
    spatial_tests = run_spatial_tests(enriched_records)
    audit = audit_payload(records, enriched_records, thresholds, spatial_tests)
    write_outputs(enriched_records, audit)

    print(f"Wrote {OUTPUT_JSON} ({len(enriched_records)} records)")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {AUDIT_JSON}")
    print(f"Wrote {REPORT_MD}")


if __name__ == "__main__":
    main()
