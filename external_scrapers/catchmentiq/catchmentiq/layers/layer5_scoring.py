import pandas as pd
import geopandas as gpd
import h3
from catchmentiq.layers.layer4_gravity import run as run_gravity_model
from catchmentiq.logger.live_logger import NullLogger
from catchmentiq.utils.geo_helpers import gdf_to_geojson_dict

def run(grid_gdf: gpd.GeoDataFrame, schools_gdf: gpd.GeoDataFrame, isochrones_gdf: gpd.GeoDataFrame, city_config: dict, tier_config: dict, logger) -> gpd.GeoDataFrame:
    """
    Compute percentile demand scores and perform a 3-run stability check under parameter variations.
    """
    logger.layer_start(5, "Scoring & Stability")
    
    # ---- 1. Percentile Scoring ----
    logger.log("Calculating percentile demand scores for habitable hexes...")
    
    # Default initialize
    grid_gdf["percentile_score"] = 0.0
    grid_gdf["absolute_tam"] = 0
    
    habitable_mask = (grid_gdf["is_habitable"] == True) & (grid_gdf["apportioned_students"] > 0)
    active = grid_gdf[habitable_mask].copy()
    
    if not active.empty:
        # Calculate rank percentile
        active["percentile_score"] = active["apportioned_students"].rank(pct=True) * 100.0
        active["absolute_tam"] = active["apportioned_students"].round().astype(int)
        
        # Merge back
        for idx, row in active.iterrows():
            grid_gdf.loc[grid_gdf["hex_id"] == row["hex_id"], "percentile_score"] = row["percentile_score"]
            grid_gdf.loc[grid_gdf["hex_id"] == row["hex_id"], "absolute_tam"] = row["absolute_tam"]
            
    # Send Demand Score layer to map
    habitable_grid = grid_gdf[grid_gdf["is_habitable"] == True].copy()
    logger.add_choropleth("Demand Score", gdf_to_geojson_dict(habitable_grid), value_field="percentile_score", color_scale="YlOrRd")
    
    # Add Top 10% Zones layer
    top_10_pct_val = grid_gdf["percentile_score"].quantile(0.90)
    top_10_grid = grid_gdf[(grid_gdf["is_habitable"] == True) & (grid_gdf["percentile_score"] >= top_10_pct_val) & (grid_gdf["percentile_score"] > 0)].copy()
    
    logger.log(f"Top 10% zones cutoff score: {top_10_pct_val:.2f}%. Found {len(top_10_grid)} hexes.")
    logger.add_polygons("Top 10% Zones", gdf_to_geojson_dict(top_10_grid), style={
        "fill_color": "#E74C3C", 
        "fill_opacity": 0.35, 
        "stroke_color": "#C0392B", 
        "stroke_width": 2
    })
    
    # ---- 2. Compute School Density Heatmap ----
    logger.log("Computing continuous school density heatmap...")
    resolution = city_config["grid"]["h3_resolution"]
    
    # Pre-filter schools to only include those in the target tier (i.e. those with computed isochrones)
    target_schools = schools_gdf[schools_gdf["id"].isin(isochrones_gdf["school_id"].unique())]
    logger.log(f"Using {len(target_schools)} target tier schools for density index...")
    
    hex_to_schools = {}
    for idx, school in target_schools.iterrows():
        lat = school.geometry.y
        lon = school.geometry.x
        school_hex = h3.latlng_to_cell(lat, lon, resolution)
        if school_hex not in hex_to_schools:
            hex_to_schools[school_hex] = []
        hex_to_schools[school_hex].append(school.get("student_count", 0))
        
    grid_gdf["school_density"] = 0.0
    
    for idx, row in grid_gdf.iterrows():
        hid = row["hex_id"]
        if not row["is_habitable"]:
            continue
            
        density_sum = 0.0
        for r in range(4): # 0 to 3 ring disk
            ring = h3.grid_ring(hid, r) if r > 0 else [hid]
            weight = 1.0 / (1.0 + r)
            for nb_hid in ring:
                if nb_hid in hex_to_schools:
                    for count in hex_to_schools[nb_hid]:
                        density_sum += count * weight
                        
        grid_gdf.loc[grid_gdf["hex_id"] == hid, "school_density"] = density_sum
        
    # ---- 3. Multi-Run Stability Check ----
    num_runs = city_config["stability"].get("num_runs", 12)
    logger.log(f"Running {num_runs}-run parameter sensitivity stability checks...")
    
    base_alpha = city_config["gravity_model"]["alpha"]
    jitter_alpha = city_config["stability"]["alpha_jitter"] # 0.3
    jitter_beta = city_config["stability"]["beta_jitter"] # 0.5
    top_n = city_config["output"]["top_n_zones"] # 20
    
    import random
    random.seed(42)
    
    top_hex_sets = []
    null_logger = NullLogger()
    
    for i in range(1, num_runs + 1):
        if i == 1:
            a_val = base_alpha
            p_beta = 0.15
            m_beta = 0.3
            e_beta = 0.5
        else:
            a_val = base_alpha + random.uniform(-jitter_alpha, jitter_alpha)
            p_beta = max(0.01, 0.15 + random.uniform(-jitter_beta, jitter_beta))
            m_beta = max(0.01, 0.3 + random.uniform(-jitter_beta, jitter_beta))
            e_beta = max(0.01, 0.5 + random.uniform(-jitter_beta, jitter_beta))
            
        logger.log(f"Stability check run {i}/{num_runs}: Alpha={a_val:.2f}, PremiumBeta={p_beta:.2f}, MidBeta={m_beta:.2f}, EcoBeta={e_beta:.2f}...")
        
        # Jitter config
        import copy
        temp_config = copy.deepcopy(city_config)
        temp_config["gravity_model"]["alpha"] = a_val
        temp_config["gravity_model"]["premium_beta"] = p_beta
        temp_config["gravity_model"]["midmarket_beta"] = m_beta
        temp_config["gravity_model"]["economy_beta"] = e_beta
        
        # Run gravity model silently
        temp_grid = grid_gdf.copy()
        result_grid = run_gravity_model(
            schools_gdf=schools_gdf,
            grid_gdf=temp_grid,
            city_config=temp_config,
            tier_config=tier_config,
            logger=null_logger
        )
        
        # Extract top N cells
        top_hexes = set(result_grid.nlargest(top_n, "apportioned_students")["hex_id"])
        top_hex_sets.append(top_hexes)
        
    # A hex is Stable if it is in the top-N across ALL runs
    stable_hexes = set.intersection(*top_hex_sets)
    
    grid_gdf["stability_flag"] = grid_gdf["hex_id"].apply(
        lambda h: "Stable" if h in stable_hexes else "Sensitive"
    )
    
    logger.log(f"Sensitivity check complete. Stable hexes in top-{top_n}: {len(stable_hexes)}/{top_n}.", "success")
    logger.layer_end(5, f"Scoring complete. {len(stable_hexes)} stable top-scoring zones identified.")
    
    return grid_gdf
