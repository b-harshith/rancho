"""
School Partnership Score
========================
The most actionable output for Rancho Labs.

A heatmap of hexes is strategic. A ranked list of schools to approach
first thing Monday morning is operational.

This module ranks every school by a composite score:
    Partnership Score = Board Confidence × Fee Alignment × TAM Density

Where:
  - Board Confidence: IB/IGCSE = 1.0, Cambridge = 0.85, ICSE = 0.75, CBSE = 0.5
  - Fee Alignment: how closely the school's fee bracket matches the target tier
  - TAM Density: the percentile demand score of the H3 hex where the school sits
                  + contribution from all hexes within a 1-ring buffer

The output is a ranked CSV/GeoJSON that tells the sales team:
  "School X in Whitefield is your best first call — it's IB, fees match,
   and 94% of the residential TAM lives in a 20-min drive of it."
"""

import os
import json
import geopandas as gpd
import pandas as pd
import numpy as np
import h3
from catchmentiq.utils.geo_helpers import gdf_to_geojson_dict


def compute_school_partnership_score(
    schools_gdf: gpd.GeoDataFrame,
    grid_gdf: gpd.GeoDataFrame,
    tier_config: dict,
    city_config: dict,
    logger
) -> pd.DataFrame:
    """
    Rank all schools by their suitability for a Rancho Labs partnership approach.

    Returns a DataFrame with one row per school, sorted by partnership_score descending.
    """
    logger.log("Computing School Partnership Scores...", "info")

    resolution = city_config["grid"]["h3_resolution"]
    fee_min = tier_config["school_fee_min"]
    fee_max = tier_config.get("school_fee_max")  # None for premium tier
    board_priority = tier_config.get("board_priority", {})
    default_board_score = board_priority.get("default", 0.5)

    # Pre-build a hex_id → percentile_score lookup for speed
    hex_score_map = {}
    if "percentile_score" in grid_gdf.columns:
        for _, row in grid_gdf[grid_gdf["is_habitable"] == True].iterrows():
            hex_score_map[row["hex_id"]] = row.get("percentile_score", 0.0) or 0.0

    results = []

    for idx, school in schools_gdf.iterrows():
        school_name = school["name"]
        boards = school.get("board", [])
        avg_fee = school.get("avg_fee", 0.0) or 0.0
        student_count = school.get("student_count", 0)
        board_confidence = school.get("board_confidence", 0.3)

        # ---- 1. Board Score ----
        # Use the tier's board_priority map if available, otherwise use pre-computed confidence
        if boards and board_priority:
            board_scores = [board_priority.get(b, default_board_score) for b in boards]
            board_score = max(board_scores)
            # Normalise to 0-1 range (max priority value is 3.0 in config)
            max_priority = max(board_priority.values()) if board_priority else 3.0
            board_score_normalised = board_score / max_priority
        else:
            board_score_normalised = board_confidence  # fallback to Layer 0 signal

        # ---- 2. Fee Alignment Score ----
        # How well does this school's fee match the target tier?
        # Perfect alignment = school fee is at or just above fee_min.
        # Schools far below fee_min or far above are penalised.
        if fee_max is None:
            # Premium tier: reward schools above fee_min, cap at 3x fee_min
            if avg_fee >= fee_min:
                fee_score = min(1.0, avg_fee / (fee_min * 3))
            else:
                # Below tier minimum — partial credit based on proximity
                fee_score = max(0.0, avg_fee / fee_min) * 0.5
        else:
            # Mid-market tier: reward schools within range, penalise outliers
            if fee_min <= avg_fee <= fee_max:
                # Normalise within range
                fee_score = (avg_fee - fee_min) / (fee_max - fee_min)
                fee_score = 0.5 + (fee_score * 0.5)  # floor at 0.5 for in-range schools
            elif avg_fee < fee_min:
                fee_score = max(0.0, avg_fee / fee_min) * 0.4
            else:
                # Above max — might be premium tier leakage
                fee_score = max(0.0, 1 - (avg_fee - fee_max) / fee_max) * 0.6

        # ---- 3. TAM Density Score ----
        # What is the residential demand density around this school's location?
        # We look at the school's own hex plus its 1-ring neighbours.
        school_hex = h3.latlng_to_cell(school.geometry.y, school.geometry.x, resolution)
        neighborhood = h3.grid_disk(school_hex, 1)  # school's hex + 6 neighbors

        neighborhood_scores = [hex_score_map.get(hid, 0.0) for hid in neighborhood]
        # Use weighted average: own hex gets 2x weight vs ring
        own_hex_score = hex_score_map.get(school_hex, 0.0)
        if neighborhood_scores:
            tam_score = (own_hex_score * 2 + sum(neighborhood_scores)) / (len(neighborhood_scores) + 2)
        else:
            tam_score = own_hex_score

        tam_score_normalised = tam_score / 100.0  # percentile → 0-1

        # ---- 4. Composite Partnership Score ----
        # Weights reflect what matters most for Rancho Labs:
        # TAM Density is most important (are there enough families nearby?)
        # Board is second (are they the right audience?)
        # Fee alignment third (sanity check on income tier match)
        WEIGHT_TAM = 0.50
        WEIGHT_BOARD = 0.35
        WEIGHT_FEE = 0.15

        partnership_score = (
            (WEIGHT_TAM * tam_score_normalised) +
            (WEIGHT_BOARD * board_score_normalised) +
            (WEIGHT_FEE * fee_score)
        ) * 100  # Scale to 0-100

        # ---- 5. Build Output Record ----
        results.append({
            "school_name": school_name,
            "board": ", ".join(boards),
            "board_confidence": round(board_confidence, 2),
            "avg_fee_annual": int(avg_fee),
            "student_count": student_count,
            "partnership_score": round(partnership_score, 2),
            "board_score": round(board_score_normalised, 3),
            "fee_alignment_score": round(fee_score, 3),
            "tam_density_score": round(tam_score_normalised, 3),
            "hex_percentile": round(own_hex_score, 1),
            "lat": round(school.geometry.y, 6),
            "lon": round(school.geometry.x, 6),
        })

    if not results:
        logger.log("No schools to score for partnership.", "warning")
        return pd.DataFrame()

    ranked_df = pd.DataFrame(results).sort_values("partnership_score", ascending=False).reset_index(drop=True)
    ranked_df.index += 1  # 1-based rank
    ranked_df.index.name = "rank"
    ranked_df = ranked_df.reset_index()

    top_5 = ranked_df.head(5)
    logger.log(f"Top 5 schools to approach first:", "success")
    for _, row in top_5.iterrows():
        logger.log(
            f"  #{int(row['rank'])} {row['school_name']} | Score: {row['partnership_score']:.1f} "
            f"| Board: {row['board']} | Fee: ₹{row['avg_fee_annual']:,} | TAM hex: {row['hex_percentile']:.0f}%ile",
            "info"
        )

    return ranked_df


def save_school_partnership_output(ranked_df: pd.DataFrame, bundle_dir: str, logger):
    """Save the School Partnership Score to CSV and GeoJSON."""
    if ranked_df.empty:
        return

    csv_path = f"{bundle_dir}/school_partnership_scores.csv"
    ranked_df.to_csv(csv_path, index=False)
    logger.log(f"School Partnership Scores saved to: {csv_path}", "success")

    # Also save a GeoJSON for mapping
    geojson_path = f"{bundle_dir}/school_partnership_scores.geojson"
    features = []
    for _, row in ranked_df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["lon"], row["lat"]]
            },
            "properties": {k: v for k, v in row.items() if k not in ["lat", "lon"]}
        })
    with open(geojson_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    logger.log(f"School Partnership GeoJSON saved to: {geojson_path}", "success")

    return csv_path, geojson_path
