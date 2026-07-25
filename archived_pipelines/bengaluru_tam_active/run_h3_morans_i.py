#!/usr/bin/env python3
"""
Run global Moran's I tests for H3-level budget segment patterns.

The preferred input is DATA/processed/h3_heatmap_cells.geojson because it is
already aggregated to one row per hex. The stage1 locality CSV is supported as
a fallback by aggregating repeated locality rows to h3_res_8 first.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import h3
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HEX_GEOJSON = PROJECT_ROOT / "DATA" / "processed" / "h3_heatmap_cells.geojson"
DEFAULT_LOCALITY_CSV = PROJECT_ROOT / "DATA" / "processed" / "stage1_locality_features_flat.csv"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "DATA" / "audits" / "h3_morans_i_budget_segments.csv"
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "DATA" / "audits" / "h3_morans_i_budget_segments.json"

SEGMENTS = ("Affordable", "Mid-Segment", "Premium")
SHARE_METRICS = {
    "budget_share_affordable": "Share distribution: Affordable",
    "budget_share_mid_segment": "Share distribution: Mid-Segment",
    "budget_share_premium": "Share distribution: Premium",
}
CLASS_METRICS = {
    "dominant_is_affordable": "Dominant classification: Affordable",
    "dominant_is_mid_segment": "Dominant classification: Mid-Segment",
    "dominant_is_premium": "Dominant classification: Premium",
}


def clean_float(value: object, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def canonical_segment(value: object) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if text in {"affordable", "budget", "low"}:
        return "Affordable"
    if text in {"mid-segment", "mid segment", "mid", "middle"}:
        return "Mid-Segment"
    if text in {"premium", "luxury", "high"}:
        return "Premium"
    return "unknown"


def choose_input(preferred: Path, fallback: Path) -> tuple[Path, str]:
    if preferred.exists():
        return preferred, "compiled_hex_geojson"
    if fallback.exists():
        return fallback, "stage1_locality_csv_aggregated_to_hex"
    raise FileNotFoundError(f"Neither {preferred} nor {fallback} exists.")


def load_hex_geojson(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        cell = props.get("h3_cell")
        if not cell:
            continue
        dominant = canonical_segment(props.get("dominant_budget_segment"))
        row = {
            "h3_cell": str(cell),
            "dominant_budget_segment": dominant,
            "budget_share_affordable": clean_float(props.get("budget_share_affordable")),
            "budget_share_mid_segment": clean_float(props.get("budget_share_mid_segment")),
            "budget_share_premium": clean_float(props.get("budget_share_premium")),
        }
        add_class_indicators(row)
        rows.append(row)
    return rows


def load_locality_csv_as_hex(path: Path) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "count": 0,
            "share_sums": Counter(),
            "dominant_counts": Counter(),
        }
    )

    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cell = row.get("h3_res_8")
            if not cell:
                continue
            bucket = grouped[cell]
            bucket["count"] = int(bucket["count"]) + 1
            bucket["share_sums"]["budget_share_affordable"] += clean_float(
                row.get("h3_budget_share_affordable")
            )
            bucket["share_sums"]["budget_share_mid_segment"] += clean_float(
                row.get("h3_budget_share_mid_segment")
            )
            bucket["share_sums"]["budget_share_premium"] += clean_float(
                row.get("h3_budget_share_premium")
            )
            bucket["dominant_counts"][canonical_segment(row.get("h3_dominant_budget_segment"))] += 1

    rows = []
    for cell, bucket in grouped.items():
        count = int(bucket["count"])
        dominant = bucket["dominant_counts"].most_common(1)[0][0]
        out = {
            "h3_cell": cell,
            "dominant_budget_segment": dominant,
            "budget_share_affordable": bucket["share_sums"]["budget_share_affordable"] / count,
            "budget_share_mid_segment": bucket["share_sums"]["budget_share_mid_segment"] / count,
            "budget_share_premium": bucket["share_sums"]["budget_share_premium"] / count,
        }
        add_class_indicators(out)
        rows.append(out)
    return rows


def add_class_indicators(row: dict[str, object]) -> None:
    dominant = row.get("dominant_budget_segment")
    row["dominant_is_affordable"] = 1.0 if dominant == "Affordable" else 0.0
    row["dominant_is_mid_segment"] = 1.0 if dominant == "Mid-Segment" else 0.0
    row["dominant_is_premium"] = 1.0 if dominant == "Premium" else 0.0


def build_dense_weight_matrix(cells: list[str], neighbor_k: int) -> tuple[np.ndarray, int, float]:
    """Builds a dense NumPy row-standardized spatial weights matrix."""
    n = len(cells)
    cell_set = set(cells)
    cell_to_idx = {c: i for i, c in enumerate(cells)}
    
    W = np.zeros((n, n), dtype=float)
    rows_with_neighbors = 0

    for i, cell in enumerate(cells):
        neighbors = [
            neighbor for neighbor in h3.grid_disk(cell, neighbor_k)
            if neighbor != cell and neighbor in cell_set
        ]
        if neighbors:
            rows_with_neighbors += 1
            weight = 1.0 / len(neighbors)
            for neighbor in neighbors:
                j = cell_to_idx[neighbor]
                W[i, j] = weight

    return W, rows_with_neighbors, float(rows_with_neighbors)


def fast_permutation_test(
    values: np.ndarray,
    W: np.ndarray,
    rows_with_neighbors: int,
    weight_sum: float,
    permutations: int,
    seed: int,
) -> dict[str, float | int | None]:
    """Fully vectorized Moran's I and permutation test using matrix algebra."""
    n = len(values)
    z = values - np.mean(values)
    denominator = float(np.sum(z**2))
    expected = -1.0 / (n - 1) if n > 1 else math.nan

    if denominator == 0.0 or weight_sum == 0.0 or permutations <= 0:
        return {
            "moran_i": math.nan,
            "expected_i": expected,
            "permutation_mean": None,
            "permutation_sd": None,
            "z_score": None,
            "p_value_two_sided": None,
            "p_value_greater": None,
            "permutations": permutations,
            "rows_with_neighbors": rows_with_neighbors,
            "weight_sum": weight_sum,
        }

    # 1. Calculate Observed Moran's I (z.T @ W @ z)
    numerator = np.dot(z, np.dot(W, z))
    observed = (n / weight_sum) * (numerator / denominator)

    # 2. Vectorized Permutations
    rng = np.random.default_rng(seed)
    
    # Generate random noise to create permuted indices efficiently
    noise = rng.random((permutations, n))
    perm_indices = np.argsort(noise, axis=1)
    
    # Z_perms is a matrix of shape (permutations, N) containing all permuted states at once
    Z_perms = z[perm_indices]

    # Matrix multiplication: Z_perms @ W.T 
    WZ = np.dot(Z_perms, W.T)
    
    # Row-wise dot product to get all 9999 numerators in one go
    numerators_sim = np.sum(Z_perms * WZ, axis=1)
    
    # Compute simulated Moran's I values
    simulated = (n / weight_sum) * (numerators_sim / denominator)

    # 3. Calculate Distribution Statistics
    simulated_mean = float(np.mean(simulated))
    simulated_sd = float(np.std(simulated, ddof=1)) if permutations > 1 else math.nan
    z_score = (observed - simulated_mean) / simulated_sd if simulated_sd > 0 else math.nan
    
    centered_observed = abs(observed - simulated_mean)
    p_two_sided = (np.sum(np.abs(simulated - simulated_mean) >= centered_observed) + 1) / (permutations + 1)
    p_greater = (np.sum(simulated >= observed) + 1) / (permutations + 1)

    return {
        "moran_i": float(observed),
        "expected_i": float(expected),
        "permutation_mean": simulated_mean,
        "permutation_sd": simulated_sd,
        "z_score": float(z_score),
        "p_value_two_sided": float(p_two_sided),
        "p_value_greater": float(p_greater),
        "permutations": permutations,
        "rows_with_neighbors": rows_with_neighbors,
        "weight_sum": weight_sum,
    }


def run_analysis(rows: list[dict[str, object]], neighbor_k: int, permutations: int, seed: int) -> list[dict[str, object]]:
    rows = sorted(rows, key=lambda item: str(item["h3_cell"]))
    cells = [str(row["h3_cell"]) for row in rows]
    
    print(f"[*] Building dense spatial weights matrix for {len(cells):,} cells (k={neighbor_k})...")
    start_time = time.time()
    W, rows_with_neighbors, weight_sum = build_dense_weight_matrix(cells, neighbor_k)
    print(f"    -> Done in {time.time() - start_time:.3f} seconds.\n")

    all_metrics = {**SHARE_METRICS, **CLASS_METRICS}
    results = []
    
    for metric, label in all_metrics.items():
        print(f"[*] Analyzing metric: {metric}")
        start_metric = time.time()
        
        values = np.array([clean_float(row.get(metric)) for row in rows], dtype=float)
        test = fast_permutation_test(values, W, rows_with_neighbors, weight_sum, permutations, seed)
        
        results.append({
            "metric": metric,
            "label": label,
            "n_hexes": len(rows),
            "neighbor_k": neighbor_k,
            "mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=1)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            **test,
        })
        
        elapsed = time.time() - start_metric
        print(f"    -> Moran's I: {test['moran_i']: .5f} | z-score: {test['z_score']: .3f} | "
              f"p-val: {test['p_value_two_sided']:.4f}")
        print(f"    -> Completed 1 + {permutations:,} permutations in {elapsed:.3f} seconds.\n")
        
    return results


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Global Moran's I tests for H3 budget-segment distribution and classification."
    )
    parser.add_argument("--hex-geojson", type=Path, default=DEFAULT_HEX_GEOJSON)
    parser.add_argument("--locality-csv", type=Path, default=DEFAULT_LOCALITY_CSV)
    parser.add_argument("--input", type=Path, help="Optional explicit input path: .geojson/.json or .csv.")
    parser.add_argument("--neighbor-k", type=int, default=1, help="H3 grid_disk distance for spatial weights.")
    parser.add_argument("--permutations", type=int, default=9999)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    return parser.parse_args()


def main() -> None:
    print("=" * 60)
    print(" H3 SPATIAL AUTOCORRELATION ENGINE (Vectorized)")
    print("=" * 60)
    
    args = parse_args()
    if args.neighbor_k < 1:
        raise ValueError("--neighbor-k must be at least 1.")

    if args.input:
        input_path = args.input.resolve()
        source_kind = "explicit_input"
    else:
        input_path, source_kind = choose_input(args.hex_geojson, args.locality_csv)

    print(f"[*] Loading data from: {input_path.name}")
    start_load = time.time()
    if input_path.suffix.lower() == ".csv":
        rows = load_locality_csv_as_hex(input_path)
    else:
        rows = load_hex_geojson(input_path)
    print(f"    -> Loaded {len(rows):,} cells in {time.time() - start_load:.3f} seconds.\n")

    if not rows:
        raise ValueError(f"No H3 rows loaded from {input_path}.")

    total_start_time = time.time()
    results = run_analysis(rows, args.neighbor_k, args.permutations, args.seed)
    total_elapsed = time.time() - total_start_time

    payload = {
        "source_path": str(input_path),
        "source_kind": source_kind,
        "method": {
            "statistic": "Global Moran's I",
            "spatial_weights": f"H3 grid_disk(cell, {args.neighbor_k}) contiguity, row-standardized",
            "permutation_test": {
                "permutations": args.permutations,
                "seed": args.seed,
                "p_value_two_sided": "Pseudo p-value from random permutations.",
                "p_value_greater": "Pseudo p-value for positive spatial autocorrelation.",
            },
        },
        "results": results,
    }

    write_csv(args.output_csv, results)
    write_json(args.output_json, payload)

    print("=" * 60)
    print(f" TOTAL RUNTIME: {total_elapsed:.2f} seconds")
    print("=" * 60)
    print(f"Wrote CSV : {args.output_csv}")
    print(f"Wrote JSON: {args.output_json}")


if __name__ == "__main__":
    main()
    