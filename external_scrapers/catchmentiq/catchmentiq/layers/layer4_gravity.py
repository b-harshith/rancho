import os
import json
import pandas as pd
import geopandas as gpd
import numpy as np
import yaml
import h3
from catchmentiq.utils.geo_helpers import gdf_to_geojson_dict


def _manhattan_distance_km(lat1, lon1, lat2, lon2):
    """
    Vectorised Manhattan distance in kilometres.
    Supports broadcasting: lat1/lon1 can be shape (N, 1) and lat2/lon2 shape (1, M)
    or standard shapes.
    """
    # 1 degree of latitude is approx 111.12 km
    dy = np.abs(lat1 - lat2) * 111.12
    # 1 degree of longitude is approx 111.12 * cos(lat)
    # Using average latitude of the points
    mean_lat_rad = np.radians((lat1 + lat2) / 2.0)
    dx = np.abs(lon1 - lon2) * 111.12 * np.cos(mean_lat_rad)
    return dx + dy


def _load_fee_brackets():
    """Load fee bracket definitions from income_tiers.yaml."""
    try:
        with open("config/income_tiers.yaml") as f:
            config = yaml.safe_load(f)
        return config.get("fee_brackets", {})
    except Exception:
        # Fallback brackets
        return {
            "premium":   {"label": "Premium (40 LPA+)", "fee_min": 150000},
            "midmarket": {"label": "Mid-Market (12-25 LPA)", "fee_min": 60000, "fee_max": 150000},
            "economy":   {"label": "Economy (<12 LPA)", "fee_max": 60000},
        }


def _classify_school_bracket(avg_fee, brackets):
    """Classify a school into a fee bracket based on its average annual fee."""
    for bracket_key, bracket_def in brackets.items():
        fee_min = bracket_def.get("fee_min", 0)
        fee_max = bracket_def.get("fee_max", float("inf"))
        if fee_min <= avg_fee < fee_max:
            return bracket_key
    # If fee is 0 or unknown, classify as economy
    return "economy"


def _classify_listing_bracket(price, transaction_type):
    """Classify a real estate listing into a fee/income bracket."""
    if transaction_type == "Rent":
        if price >= 40000:
            return "premium"
        elif price >= 20000:
            return "midmarket"
        else:
            return "economy"
    else:  # Sale (stubs)
        if price >= 15000000:
            return "premium"
        elif price >= 6000000:
            return "midmarket"
        else:
            return "economy"


def _load_structural_volume(logger):
    """Load structural volume mapping generated from Overture buildings."""
    volume_path = "data/processed/structural_volume_h3_res7.json"
    if os.path.exists(volume_path):
        try:
            with open(volume_path) as f:
                logger.log("Loading structural volume from cache...")
                return json.load(f)
        except Exception as e:
            logger.log(f"Error loading structural volume: {e}", "warning")
    logger.log("Structural volume cache not found. Using uniform 1.0 structural volume base.", "warning")
    return {}


def _compute_kde_idw(schools_gdf, grid_gdf, re_gdf, hex_lats, hex_lons, hex_ids, logger):
    """Compute continuous KDE school concentration and IDW real estate surfaces."""
    logger.log("Computing continuous KDE school concentration and IDW real estate surfaces...")
    
    # 1. School KDE
    n_hexes = len(hex_ids)
    school_lats = schools_gdf.geometry.y.values
    school_lons = schools_gdf.geometry.x.values
    school_weights = (schools_gdf["student_count"].values * schools_gdf["board_confidence"].values).astype(np.float64)
    school_brackets = schools_gdf["fee_bracket"].values
    
    # Manhattan distance matrix N_schools x M_hexes
    dist_schools = _manhattan_distance_km(
        school_lats[:, np.newaxis], school_lons[:, np.newaxis],
        hex_lats[np.newaxis, :], hex_lons[np.newaxis, :]
    )
    
    bandwidth = 5.0  # 5km bandwidth for KDE
    # Quartic Kernel: (1 - (d/R)^2)^2 if d <= R, else 0
    kde_weights = np.where(dist_schools <= bandwidth, (1.0 - (dist_schools / bandwidth) ** 2) ** 2, 0.0)
    
    kde_surfaces = {}
    for bk in ["premium", "midmarket", "economy"]:
        mask = (school_brackets == bk)
        if mask.any():
            kde_surfaces[bk] = np.sum(kde_weights[mask] * school_weights[mask, np.newaxis], axis=0)
        else:
            kde_surfaces[bk] = np.zeros(n_hexes, dtype=np.float64)
            
    # 2. Real Estate IDW
    re_lats = re_gdf.geometry.y.values
    re_lons = re_gdf.geometry.x.values
    re_rents = re_gdf["price_inr"].values.astype(np.float64)
    re_ppsqfts = re_gdf["price_per_sqft"].values.astype(np.float64)
    
    # Compute Manhattan distance matrix N_listings x M_hexes
    dist_re = _manhattan_distance_km(
        re_lats[:, np.newaxis], re_lons[:, np.newaxis],
        hex_lats[np.newaxis, :], hex_lons[np.newaxis, :]
    )
    
    # IDW with power=2 and epsilon=0.1km
    idw_weights = 1.0 / (dist_re + 0.1) ** 2
    weights_sum = idw_weights.sum(axis=0)
    weights_sum_safe = np.where(weights_sum > 0, weights_sum, 1.0)
    
    idw_rent = np.sum(idw_weights * re_rents[:, np.newaxis], axis=0) / weights_sum_safe
    idw_ppsqft = np.sum(idw_weights * re_ppsqfts[:, np.newaxis], axis=0) / weights_sum_safe
    
    # Normalize IDW to 0-100 scale
    def normalize_surface(arr):
        amin, amax = arr.min(), arr.max()
        if amax - amin > 0:
            return (arr - amin) / (amax - amin) * 100.0
        return np.zeros_like(arr)
        
    idw_rent_norm = normalize_surface(idw_rent)
    idw_ppsqft_norm = normalize_surface(idw_ppsqft)
    
    return kde_surfaces, idw_rent_norm, idw_ppsqft_norm


def run(schools_gdf: gpd.GeoDataFrame, grid_gdf: gpd.GeoDataFrame,
        city_config: dict, tier_config: dict, logger) -> gpd.GeoDataFrame:
    """
    Probabilistic Spatial Interaction Model with Fee Bracket Segmentation,
    3D Capacity Mass Realignment, and Manhattan Distance Decay.
    """
    logger.layer_start(4, "Spatial Interaction Model (3D Realignment)")
    
    max_radius = city_config["gravity_model"].get("max_radius_km", 15)
    
    # ---- 1. Load configs and brackets ----
    fee_brackets = _load_fee_brackets()
    bracket_keys = list(fee_brackets.keys())  # ["premium", "midmarket", "economy"]
    
    # Decay betas from config or strict mathematical directives:
    decay_betas = {
        "premium": city_config["gravity_model"].get("premium_beta", 0.15),
        "midmarket": city_config["gravity_model"].get("midmarket_beta", 0.3),
        "economy": city_config["gravity_model"].get("economy_beta", 0.5)
    }
    
    logger.log(f"Dynamic Betas: Premium={decay_betas['premium']}, Mid-Market={decay_betas['midmarket']}, Economy={decay_betas['economy']}")
    logger.log(f"Using Manhattan distance metric and max radius {max_radius}km")
    
    schools_gdf = schools_gdf.copy()
    schools_gdf["fee_bracket"] = schools_gdf["avg_fee"].apply(
        lambda f: _classify_school_bracket(f, fee_brackets)
    )
    
    for bk in bracket_keys:
        count = len(schools_gdf[schools_gdf["fee_bracket"] == bk])
        logger.log(f"  Fee bracket '{bk}': {count} schools")
        
    # ---- 2. Compute 3D Capacity Mass: W_{j,b} = B_j * R_{j,b} ----
    logger.log("Computing 3D Capacity Mass Realignment...")
    
    # 2a. Structural Volume Base (B_j)
    structural_volume = _load_structural_volume(logger)
    
    # Load raw listings for KDE/IDW computation later
    re_path = "data/processed/realestate_processed.parquet"
    re_gdf = gpd.read_parquet(re_path)
    
    habitable = grid_gdf[grid_gdf["is_habitable"] == True].copy()
    
    if habitable.empty:
        logger.log("No habitable hexes found. Skipping gravity model.", "warning")
        grid_gdf["apportioned_students"] = 0.0
        for bk in bracket_keys:
            grid_gdf[f"students_{bk}"] = 0.0
            grid_gdf[f"pct_{bk}"] = 0.0
        logger.layer_end(4, "No habitable hexes.")
        return grid_gdf
        
    hex_ids = habitable["hex_id"].values
    n_hexes = len(hex_ids)
    
    W_jb = {bk: np.zeros(n_hexes, dtype=np.float64) for bk in bracket_keys}
    B_j_vals = np.zeros(n_hexes, dtype=np.float64)
    listings_count_vals = {bk: np.zeros(n_hexes, dtype=np.int32) for bk in bracket_keys}
    ratio_vals = {bk: np.zeros(n_hexes, dtype=np.float64) for bk in bracket_keys}
    
    for idx, hid in enumerate(hex_ids):
        B_j = structural_volume.get(hid, 0.0)
        
        # Read pre-calculated metrics from grid_gdf
        grid_row = grid_gdf[grid_gdf["hex_id"] == hid].iloc[0]
        total_local_listings = (
            int(grid_row.get("listings_premium", 0)) +
            int(grid_row.get("listings_midmarket", 0)) +
            int(grid_row.get("listings_economy", 0))
        )
        
        if B_j == 0.0 and total_local_listings > 0:
            B_j = 1000.0  # assign baseline
            
        B_j_vals[idx] = B_j
        
        # Compute household capacity count from volume: Volume / (average flat area * floor height)
        # Assuming 120m2 average flat size and 3.0m ceiling height
        capacity_count = B_j / (120.0 * 3.0)
        
        for bk in bracket_keys:
            listings_count_vals[bk][idx] = int(grid_row.get(f"listings_{bk}", 0))
            ratio_vals[bk][idx] = float(grid_row.get(f"ratio_{bk}", 0.33))
            W_jb[bk][idx] = capacity_count * ratio_vals[bk][idx]
            
    logger.log(f"3D Capacity Mass computed for {n_hexes} habitable hexes.")
    
    # ---- 3. Extract coordinates ----
    hex_centroids = habitable.geometry.to_crs("EPSG:3857").centroid.to_crs("EPSG:4326")
    hex_lats = hex_centroids.y.values
    hex_lons = hex_centroids.x.values
    
    school_lats = schools_gdf.geometry.y.values
    school_lons = schools_gdf.geometry.x.values
    school_students = schools_gdf["student_count"].values.astype(np.float64)
    school_brackets = schools_gdf["fee_bracket"].values
    school_confidence = schools_gdf["board_confidence"].values.astype(np.float64)
    
    n_schools = len(schools_gdf)
    
    # ---- 4. Routing and Decay (Valhalla Routing with Manhattan fallback) ----
    valhalla_config = city_config.get("gravity_model", {})
    valhalla_url = valhalla_config.get("valhalla_url", "http://localhost:8002")
    costing = valhalla_config.get("costing", "auto")
    
    sources_coords = list(zip(school_lats, school_lons))
    targets_coords = list(zip(hex_lats, hex_lons))
    
    from catchmentiq.utils.valhalla_client import compute_routing_matrices
    dist_matrix, time_matrix = compute_routing_matrices(sources_coords, targets_coords, valhalla_url, costing, logger)
    
    if dist_matrix is not None:
        logger.log("Successfully loaded routing matrices from Valhalla.", "success")
        time_matrix_mins = time_matrix / 60.0
    else:
        logger.log(f"Valhalla service unreachable at {valhalla_url}. Falling back to Manhattan distance metric.", "warning")
        dist_matrix = _manhattan_distance_km(
            school_lats[:, np.newaxis], school_lons[:, np.newaxis],
            hex_lats[np.newaxis, :], hex_lons[np.newaxis, :]
        )
        time_matrix_mins = dist_matrix * 3.0 # 3.0 min/km = 20 km/h avg speed
        
    school_betas = np.array([decay_betas[b] for b in school_brackets], dtype=np.float64)
    within_radius = dist_matrix <= max_radius
    decay_matrix = np.where(within_radius, np.exp(-school_betas[:, np.newaxis] * dist_matrix), 0.0)
    
    # ---- 5. Allocation ----
    weighted_decay = np.zeros_like(decay_matrix)
    for bk in bracket_keys:
        mask = (school_brackets == bk)
        if not mask.any():
            continue
        weighted_decay[mask] = decay_matrix[mask] * W_jb[bk][np.newaxis, :]
        
    row_sums = weighted_decay.sum(axis=1, keepdims=True)
    
    # Fallback for isolated schools
    zero_mask = (row_sums.flatten() == 0)
    if zero_mask.any():
        fallback_sums = decay_matrix[zero_mask].sum(axis=1, keepdims=True)
        super_zero_mask = (fallback_sums.flatten() == 0)
        if super_zero_mask.any():
            sz_indices = np.where(zero_mask)[0][super_zero_mask]
            for s_idx in sz_indices:
                s_dist = dist_matrix[s_idx]
                s_beta = school_betas[s_idx]
                s_within = s_dist <= (max_radius * 2)
                s_decay = np.where(s_within, np.exp(-s_beta * s_dist), 0.0)
                s_bk = school_brackets[s_idx]
                s_weighted = s_decay * W_jb[s_bk]
                s_sum = s_weighted.sum()
                if s_sum > 0:
                    weighted_decay[s_idx] = s_weighted
                    row_sums[s_idx, 0] = s_sum
                else:
                    s_sum_dist = s_decay.sum()
                    weighted_decay[s_idx] = s_decay
                    row_sums[s_idx, 0] = s_sum_dist if s_sum_dist > 0 else 1.0
        row_sums = weighted_decay.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums > 0, row_sums, 1.0)
        
    prob_matrix = weighted_decay / row_sums
    
    # ---- 6. Apportion Students ----
    effective_school_pull = school_students * school_confidence
    students_matrix = effective_school_pull[:, np.newaxis] * prob_matrix
    total_per_hex = students_matrix.sum(axis=0)
    
    bracket_totals = {}
    for bk in bracket_keys:
        mask = (school_brackets == bk)
        if mask.any():
            bracket_totals[bk] = students_matrix[mask].sum(axis=0)
        else:
            bracket_totals[bk] = np.zeros(n_hexes, dtype=np.float64)
            
    # ---- 7. Write Results Back ----
    grid_gdf["apportioned_students"] = 0.0
    for bk in bracket_keys:
        grid_gdf[f"students_{bk}"] = 0.0
        grid_gdf[f"pct_{bk}"] = 0.0
    
    grid_gdf["structural_volume"] = 0.0
    for bk in bracket_keys:
        grid_gdf[f"listings_{bk}"] = 0
        grid_gdf[f"ratio_{bk}"] = 0.0
        
    hex_id_to_idx = {hid: idx for idx, hid in enumerate(hex_ids)}
    
    for idx, row in grid_gdf.iterrows():
        hid = row["hex_id"]
        if hid in hex_id_to_idx:
            arr_idx = hex_id_to_idx[hid]
            total = total_per_hex[arr_idx]
            grid_gdf.at[idx, "apportioned_students"] = total
            
            grid_gdf.at[idx, "structural_volume"] = float(B_j_vals[arr_idx])
            for bk in bracket_keys:
                bk_val = bracket_totals[bk][arr_idx]
                grid_gdf.at[idx, f"students_{bk}"] = bk_val
                grid_gdf.at[idx, f"pct_{bk}"] = (bk_val / total * 100.0) if total > 0 else 0.0
                
                grid_gdf.at[idx, f"listings_{bk}"] = int(listings_count_vals[bk][arr_idx])
                grid_gdf.at[idx, f"ratio_{bk}"] = float(ratio_vals[bk][arr_idx])
                
    # ---- 8. Strict Conservation Check ----
    total_input_students = effective_school_pull.sum()
    total_predicted = total_per_hex.sum()
    conservation_error = abs(total_predicted - total_input_students) / max(total_input_students, 1) * 100
    logger.log(f"Conservation Check: {total_input_students:,.2f} input -> {total_predicted:,.2f} predicted ({conservation_error:.4f}% error)")
    
    if conservation_error > 0.01:
        scale = total_input_students / max(total_predicted, 1.0)
        total_per_hex *= scale
        for bk in bracket_keys:
            bracket_totals[bk] *= scale
            
        for idx, row in grid_gdf.iterrows():
            hid = row["hex_id"]
            if hid in hex_id_to_idx:
                arr_idx = hex_id_to_idx[hid]
                total = total_per_hex[arr_idx]
                grid_gdf.at[idx, "apportioned_students"] = total
                for bk in bracket_keys:
                    bk_val = bracket_totals[bk][arr_idx]
                    grid_gdf.at[idx, f"students_{bk}"] = bk_val
                    grid_gdf.at[idx, f"pct_{bk}"] = (bk_val / total * 100.0) if total > 0 else 0.0
                    
    # ---- 8.5 Precompute Top 10 Feeder Schools for each Hex cell ----
    import json
    logger.log("Pre-calculating top 10 feeder schools for all habitable cells...")
    
    feeder_traces = {bk: [] for bk in bracket_keys}
    
    for arr_idx in range(n_hexes):
        for bk in bracket_keys:
            school_indices = np.where(school_brackets == bk)[0]
            
            cell_feeders = []
            for i in school_indices:
                allocated = students_matrix[i, arr_idx]
                if allocated >= 0.1:
                    prob = prob_matrix[i, arr_idx] * 100.0
                    dist = dist_matrix[i, arr_idx]
                    time_mins = time_matrix_mins[i, arr_idx]
                    decay = decay_matrix[i, arr_idx]
                    mass = W_jb[bk][arr_idx]
                    attraction = mass * decay
                    school_sum = row_sums[i, 0]
                    
                    school_row = schools_gdf.iloc[i]
                    
                    board_val = school_row["board"]
                    board_str = ", ".join(board_val) if isinstance(board_val, list) else str(board_val)
                    
                    cell_feeders.append({
                        "name": str(school_row["name"]),
                        "lat": float(school_row.geometry.y),
                        "lon": float(school_row.geometry.x),
                        "avg_fee": float(school_row["avg_fee"]),
                        "student_count": int(school_row["student_count"]),
                        "board": board_str,
                        "board_confidence": float(school_row["board_confidence"]),
                        "distance": float(dist),
                        "time_mins": float(time_mins),
                        "beta": float(decay_betas[bk]),
                        "decay": float(decay),
                        "mass": float(mass),
                        "attraction": float(attraction),
                        "schoolSum": float(school_sum),
                        "prob": float(prob),
                        "allocated": float(allocated)
                    })
                    
            # Sort by allocated descending, take top 10
            cell_feeders.sort(key=lambda x: x["allocated"], reverse=True)
            top_feeders = cell_feeders[:10]
            
            feeder_traces[bk].append(json.dumps(top_feeders))
            
    grid_gdf["feeder_premium"] = ""
    grid_gdf["feeder_midmarket"] = ""
    grid_gdf["feeder_economy"] = ""
    
    for idx, row in grid_gdf.iterrows():
        hid = row["hex_id"]
        if hid in hex_id_to_idx:
            arr_idx = hex_id_to_idx[hid]
            grid_gdf.at[idx, "feeder_premium"] = feeder_traces["premium"][arr_idx]
            grid_gdf.at[idx, "feeder_midmarket"] = feeder_traces["midmarket"][arr_idx]
            grid_gdf.at[idx, "feeder_economy"] = feeder_traces["economy"][arr_idx]

    # ---- 9. Compute KDE & IDW Surfaces ----
    kde_surfaces, idw_rent_norm, idw_ppsqft_norm = _compute_kde_idw(
        schools_gdf, grid_gdf, re_gdf, hex_lats, hex_lons, hex_ids, logger
    )
    
    grid_gdf["kde_premium"] = 0.0
    grid_gdf["kde_midmarket"] = 0.0
    grid_gdf["kde_economy"] = 0.0
    grid_gdf["idw_rent_normalized"] = 0.0
    grid_gdf["idw_ppsqft_normalized"] = 0.0
    
    for idx, row in grid_gdf.iterrows():
        hid = row["hex_id"]
        if hid in hex_id_to_idx:
            arr_idx = hex_id_to_idx[hid]
            grid_gdf.at[idx, "kde_premium"] = kde_surfaces["premium"][arr_idx]
            grid_gdf.at[idx, "kde_midmarket"] = kde_surfaces["midmarket"][arr_idx]
            grid_gdf.at[idx, "kde_economy"] = kde_surfaces["economy"][arr_idx]
            grid_gdf.at[idx, "idw_rent_normalized"] = idw_rent_norm[arr_idx]
            grid_gdf.at[idx, "idw_ppsqft_normalized"] = idw_ppsqft_norm[arr_idx]
            
    # ---- 10. Dashboard Choropleths ----
    habitable_scored = grid_gdf[grid_gdf["is_habitable"] == True].copy()
    logger.add_choropleth("TAM Density (All Schools)", gdf_to_geojson_dict(habitable_scored),
                          value_field="apportioned_students", color_scale="YlOrRd")
    
    for bk in bracket_keys:
        col = f"students_{bk}"
        label = fee_brackets[bk].get("label", bk)
        logger.add_choropleth(f"Students: {label}", gdf_to_geojson_dict(habitable_scored),
                              value_field=col, color_scale="YlOrRd")
        
    for bk in bracket_keys:
        bk_total = bracket_totals[bk].sum()
        label = fee_brackets[bk].get("label", bk)
        logger.log(f"  {label}: {bk_total:,.0f} students predicted across grid")
        
    logger.layer_end(4, f"Spatial Interaction Model complete. {total_predicted:,.0f} students.")
    return grid_gdf
