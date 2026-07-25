"""
CatchmentIQ — Pipeline Orchestrator
=====================================
A probabilistic Spatial Decision Support System (SDSS) for identifying
optimal locations to open education centres for HNI families.

Usage:
    python main.py --city bangalore --tier premium_40lpa
    python main.py --city bangalore --tier midmarket_12lpa --alpha 1.2 --beta 2.5
    python main.py --city bangalore --tier premium_40lpa --cache --no-logger
"""

import argparse
import os
import sys
import yaml
import geopandas as gpd

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catchmentiq.logger.live_logger import LiveLogger, NullLogger
from catchmentiq.layers import layer0_ingest
from catchmentiq.layers import layer1_isochrones
from catchmentiq.layers import layer2_grid
from catchmentiq.layers import layer3_realestate
from catchmentiq.layers import layer4_gravity
from catchmentiq.layers import layer5_scoring
from catchmentiq.layers import layer6_validation
from catchmentiq.layers import school_partnership_score
from catchmentiq.output import generator
from catchmentiq.output import pdf_report


def load_config(city: str, tier: str):
    """Load all config files and merge."""
    city_config_path = f"config/city_{city}.yaml"
    tiers_config_path = "config/income_tiers.yaml"
    poi_config_path = "config/poi_categories.yaml"

    if not os.path.exists(city_config_path):
        raise FileNotFoundError(f"City config not found: {city_config_path}")

    with open(city_config_path) as f:
        city_config = yaml.safe_load(f)

    with open(tiers_config_path) as f:
        all_tiers = yaml.safe_load(f)

    with open(poi_config_path) as f:
        all_pois = yaml.safe_load(f)

    if tier not in all_tiers["tiers"]:
        raise ValueError(f"Unknown income tier: '{tier}'. Available: {list(all_tiers['tiers'].keys())}")

    tier_config = all_tiers["tiers"][tier]

    if tier not in all_pois:
        print(f"[WARNING] No POI config for tier '{tier}', using empty POI list.")
        poi_config = []
    else:
        poi_config = all_pois[tier]

    return city_config, tier_config, poi_config


def aggregate_res8_to_res7(grid_res8: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Aggregate resolution 8 hexes to resolution 7 parent hexes."""
    import h3
    from catchmentiq.utils.h3_helpers import get_hex_polygon
    
    df = grid_res8.copy()
    
    # Ensure all columns exist
    cols_to_check = [
        "apportioned_students", "absolute_tam", "capacity_mass", "poi_density", 
        "is_habitable", "ward_name", "ward_poi_score", "stability_flag", 
        "rental_index", "rental_ppsqft", "school_density",
        "students_premium", "students_midmarket", "students_economy",
        "kde_premium", "kde_midmarket", "kde_economy",
        "idw_rent_normalized", "idw_ppsqft_normalized",
        "structural_volume", "listings_premium", "listings_midmarket", "listings_economy",
        "ratio_premium", "ratio_midmarket", "ratio_economy"
    ]
    for col in cols_to_check:
        if col not in df.columns:
            if col in ["ward_name", "stability_flag"]:
                df[col] = "N/A"
            elif col in ["listings_premium", "listings_midmarket", "listings_economy"]:
                df[col] = 0
            else:
                df[col] = 0.0
            
    df["parent_hex_id"] = df["hex_id"].apply(lambda h: h3.cell_to_parent(h, 7))
    
    # Perform grouping
    agg_df = df.groupby("parent_hex_id").agg({
        "apportioned_students": "sum",
        "absolute_tam": "sum",
        "capacity_mass": "sum",
        "poi_density": "sum",
        "is_habitable": "max",
        "ward_name": "first",
        "ward_poi_score": "mean",
        "rental_index": "mean",
        "rental_ppsqft": "mean",
        "school_density": "mean",
        "students_premium": "sum",
        "students_midmarket": "sum",
        "students_economy": "sum",
        "structural_volume": "sum",
        "listings_premium": "sum",
        "listings_midmarket": "sum",
        "listings_economy": "sum",
        "ratio_premium": "mean",
        "ratio_midmarket": "mean",
        "ratio_economy": "mean",
        "kde_premium": "mean",
        "kde_midmarket": "mean",
        "kde_economy": "mean",
        "idw_rent_normalized": "mean",
        "idw_ppsqft_normalized": "mean"
    }).reset_index()
    
    agg_df.rename(columns={"parent_hex_id": "hex_id"}, inplace=True)
    
    # Re-calculate percentile_score for resolution 7 grid
    agg_df["percentile_score"] = 0.0
    habitable_mask = (agg_df["is_habitable"] == True) & (agg_df["apportioned_students"] > 0)
    active = agg_df[habitable_mask].copy()
    
    if not active.empty:
        active["percentile_score"] = active["apportioned_students"].rank(pct=True) * 100.0
        active["absolute_tam"] = active["apportioned_students"].round().astype(int)
        for idx, row in active.iterrows():
            agg_df.loc[agg_df["hex_id"] == row["hex_id"], "percentile_score"] = row["percentile_score"]
            agg_df.loc[agg_df["hex_id"] == row["hex_id"], "absolute_tam"] = row["absolute_tam"]
            
    # Calculate parent stability
    stability_map = {}
    for parent_id, group in df.groupby("parent_hex_id"):
        stable_count = (group["stability_flag"] == "Stable").sum()
        stability_map[parent_id] = "Stable" if stable_count > 0 else "Sensitive"
    agg_df["stability_flag"] = agg_df["hex_id"].map(stability_map)
    
    # Calculate parent validation
    active_poi = agg_df[agg_df["poi_density"] > 0]
    median_poi = active_poi["poi_density"].median() if not active_poi.empty else 0.0
    agg_df["poi_validated"] = (agg_df["percentile_score"] >= 90) & (agg_df["poi_density"] >= median_poi)
    
    # Geoms
    agg_df["geometry"] = agg_df["hex_id"].apply(get_hex_polygon)
    
    return gpd.GeoDataFrame(agg_df, geometry="geometry", crs="EPSG:4326")



def main():
    parser = argparse.ArgumentParser(
        description="CatchmentIQ — Spatial Decision Support for Rancho Labs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --city bangalore --tier premium_40lpa
  python main.py --city bangalore --tier midmarket_12lpa --alpha 1.2 --beta 2.5 --cache
  python main.py --city bangalore --tier premium_40lpa --no-logger
        """
    )
    parser.add_argument("--city", required=True, help="City name (e.g., bangalore)")
    parser.add_argument("--tier", required=True, help="Income tier (premium_40lpa | midmarket_12lpa)")
    parser.add_argument("--alpha", type=float, default=None, help="Override gravity model wealth sensitivity (default from config)")
    parser.add_argument("--beta", type=float, default=None, help="Override gravity model commute friction (default from config)")
    parser.add_argument("--no-logger", action="store_true", help="Disable live dashboard (run headless)")
    parser.add_argument("--cache", action="store_true", help="Use cached intermediate results where available")
    parser.add_argument("--port", type=int, default=5050, help="Live dashboard port (default: 5050)")
    args = parser.parse_args()

    # ---- Load Configs ----
    print(f"\n{'='*60}")
    print(f"  CatchmentIQ Pipeline")
    print(f"  City: {args.city.title()}  |  Tier: {args.tier}")
    print(f"{'='*60}\n")

    city_config, tier_config, poi_config = load_config(args.city, args.tier)

    # Override parameters if provided
    if args.alpha is not None:
        city_config["gravity_model"]["alpha"] = args.alpha
        print(f"[CONFIG] Overriding alpha = {args.alpha}")
    if args.beta is not None:
        city_config["gravity_model"]["beta"] = args.beta
        print(f"[CONFIG] Overriding beta = {args.beta}")

    alpha = city_config["gravity_model"]["alpha"]
    beta = city_config["gravity_model"]["beta"]
    print(f"[CONFIG] Gravity Model: α={alpha} (Wealth Sensitivity), β={beta} (Commute Friction)")

    # ---- Initialize Logger ----
    if args.no_logger:
        logger = NullLogger()
        print("[LOGGER] Running in headless mode (no live dashboard).")
    else:
        logger = LiveLogger(
            port=args.port,
            city_center=city_config["city"]["center"],
            zoom=city_config["city"]["zoom"]
        )
        logger.open()

    logger.log(f"CatchmentIQ Pipeline: {city_config['city']['name']} · {tier_config['label']}", "info")
    logger.log(f"Model parameters: α={alpha}, β={beta}", "info")

    # ═══════════════════════════════════════
    # LAYER 0: Data Ingest & Cleaning
    # ═══════════════════════════════════════
    schools_gdf, re_gdf = layer0_ingest.run(city_config, logger)

    # ═══════════════════════════════════════
    # LAYER 2: H3 Grid & Habitability Masking
    # ═══════════════════════════════════════
    grid_gdf = layer2_grid.run(city_config, logger, use_cache=args.cache)

    # ═══════════════════════════════════════
    # LAYER 1: School Catchments (Isochrones)
    # ═══════════════════════════════════════
    isochrones_gdf = layer1_isochrones.run(
        schools_gdf, tier_config, city_config, logger, use_cache=args.cache
    )

    # ═══════════════════════════════════════
    # LAYER 3: Real Estate Capacity Surface
    # ═══════════════════════════════════════
    grid_gdf = layer3_realestate.run(re_gdf, grid_gdf, tier_config, city_config, logger)

    # ═══════════════════════════════════════
    # LAYER 4: Gravity Model (Huff Apportionment)
    # ═══════════════════════════════════════
    grid_gdf = layer4_gravity.run(schools_gdf, grid_gdf, city_config, tier_config, logger)

    # ═══════════════════════════════════════
    # LAYER 5: Scoring & Stability
    # ═══════════════════════════════════════
    grid_gdf = layer5_scoring.run(grid_gdf, schools_gdf, isochrones_gdf, city_config, tier_config, logger)

    # ═══════════════════════════════════════
    # SCHOOL PARTNERSHIP SCORE
    # ═══════════════════════════════════════
    # Ranked list of schools to approach first — more actionable than a heatmap alone.
    logger.log("Computing School Partnership Scores...", "info")
    ranked_schools_df = school_partnership_score.compute_school_partnership_score(
        schools_gdf=schools_gdf,
        grid_gdf=grid_gdf,
        tier_config=tier_config,
        city_config=city_config,
        logger=logger
    )

    # ═══════════════════════════════════════
    # LAYER 6: POI Validation & Ward Proximity
    # ═══════════════════════════════════════
    wards_gdf = None
    wards_path = f"data/boundaries/{args.city}_wards.geojson"
    if os.path.exists(wards_path):
        logger.log(f"Loading ward boundaries from {wards_path}...")
        wards_gdf = gpd.read_file(wards_path)
    else:
        logger.log(f"Ward boundaries not found at {wards_path}. Will fetch from OSM.", "info")

    grid_gdf, ward_scores, pois_gdf = layer6_validation.run(
        grid_gdf, wards_gdf, tier_config, poi_config, logger
    )

    # ═══════════════════════════════════════
    # AGGREGATE TO RESOLUTION 7
    # ═══════════════════════════════════════
    if city_config["grid"]["h3_resolution"] > 7:
        logger.log("Aggregating resolution 8 grid to resolution 7...", "info")
        grid_res7_gdf = aggregate_res8_to_res7(grid_gdf)
    else:
        logger.log("Grid is already resolution 7 or lower, skipping aggregation.", "info")
        grid_res7_gdf = grid_gdf.copy()

    # ═══════════════════════════════════════
    # OUTPUT BUNDLE
    # ═══════════════════════════════════════
    logger.log("Generating output bundle...", "info")
    os.makedirs("output", exist_ok=True)

    bundle_dir = generator.create_output_bundle(
        grid_res8_gdf=grid_gdf,
        grid_res7_gdf=grid_res7_gdf,
        schools_gdf=schools_gdf,
        pois_gdf=pois_gdf,
        ward_scores=ward_scores,
        city_config=city_config,
        tier_config=tier_config,
        re_gdf=re_gdf,
        isochrones_gdf=isochrones_gdf,
        ranked_schools_df=ranked_schools_df
    )

    # Save School Partnership Score to bundle
    school_partnership_score.save_school_partnership_output(
        ranked_df=ranked_schools_df,
        bundle_dir=bundle_dir,
        logger=logger
    )

    # Generate PDF
    pdf_report.generate_pdf_report(
        grid_gdf=grid_gdf,
        ward_scores=ward_scores,
        city_config=city_config,
        tier_config=tier_config,
        bundle_dir=bundle_dir
    )

    logger.log(f"Pipeline complete! Output bundle saved to: {bundle_dir}", "success")

    # Keep dashboard alive
    logger.wait()


if __name__ == "__main__":
    main()
