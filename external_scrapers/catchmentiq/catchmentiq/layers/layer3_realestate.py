import os
import geopandas as gpd
import pandas as pd
import h3
from catchmentiq.utils.geo_helpers import gdf_to_geojson_dict

def run(re_gdf: gpd.GeoDataFrame, grid_gdf: gpd.GeoDataFrame, tier_config: dict, city_config: dict, logger) -> gpd.GeoDataFrame:
    """
    Calculate the wealth capacity surface across the grid based on real estate listings.
    """
    logger.layer_start(3, "Real Estate Capacity Surface")
    
    tier_label = tier_config["label"]
    # Use tier-level rent_weight_override if set (e.g. 0.9 for premium tier)
    # where renting at ₹80k/month is as real a signal as ownership.
    sale_weight = city_config["realestate"]["sale_weight"]
    rent_weight = tier_config.get("rent_weight_override",
                                   city_config["realestate"]["rent_weight"])
    resolution = city_config["grid"]["h3_resolution"]
       # 1. Use ALL listings to calculate PPSQFT averages per hex
    logger.log(f"Calculating true wealth surface based on PPSQFT for tier {tier_label}...")
    
    import numpy as np
    
    sale_ppsqft_floor = tier_config["realestate"]["sale"].get("price_per_sqft_min", 0)
    rent_ppsqft_floor = tier_config["realestate"]["rent"].get("price_per_sqft_min", 0)
    rent_ppsqft_ceil = tier_config["realestate"]["rent"].get("price_per_sqft_max", 999999)
    rent_price_ceil = tier_config["realestate"]["rent"].get("price_max") or 999999999
    
    # Map all listings to H3 Resolution 8
    re_gdf["hex_id_res8"] = re_gdf.apply(
        lambda row: h3.latlng_to_cell(row.geometry.y, row.geometry.x, 8), axis=1
    )
    
    # Filter out missing PPSQFT values for accurate averaging
    valid_re = re_gdf[(re_gdf["price_per_sqft"].notna()) & (re_gdf["price_per_sqft"] > 0)].copy()
    
    # Filter out absurd outliers for Rent
    valid_re = valid_re[
        (valid_re["transaction_type"] == "Sale") |
        ((valid_re["transaction_type"] == "Rent") & 
         (valid_re["price_per_sqft"] <= rent_ppsqft_ceil) & 
         (valid_re["price_inr"] <= rent_price_ceil))
    ]
    
    # Listing-level premium scoring
    def compute_listing_score(row):
        if row["transaction_type"] == "Rent":
            base = row["price_per_sqft"] / 80.0
        else:
            base = row["price_per_sqft"] / 12000.0
            
        score = base
        if row.get("is_luxury") == True:
            score += 0.3
        if row.get("is_prime_location") == True:
            score += 0.2
        return min(1.5, score)
        
    valid_re["premium_score"] = valid_re.apply(compute_listing_score, axis=1)
    
    # Binarize score into brackets
    def classify_bracket(score):
        if score >= 0.8:
            return "premium"
        elif score >= 0.4:
            return "midmarket"
        else:
            return "economy"
            
    valid_re["bracket"] = valid_re["premium_score"].apply(classify_bracket)
    
    # Weight listings by confidence
    valid_re["listing_weight"] = valid_re["confidence_score"] / 100.0
    
    # Group by Res-8 cell and bracket, summing weights
    res8_counts = valid_re.groupby(["hex_id_res8", "bracket"])["listing_weight"].sum().unstack(fill_value=0.0)
    for col in ["premium", "midmarket", "economy"]:
        if col not in res8_counts.columns:
            res8_counts[col] = 0.0
            
    # Also calculate raw unweighted counts for grid reporting
    res8_raw_counts = valid_re.groupby(["hex_id_res8", "bracket"]).size().unstack(fill_value=0)
    for col in ["premium", "midmarket", "economy"]:
        if col not in res8_raw_counts.columns:
            res8_raw_counts[col] = 0
            
    # Spatial smoothing at Resolution-8
    smoothed_res8 = {}
    res8_hexes_set = set(res8_counts.index)
    
    for hid in res8_hexes_set:
        neighbors = h3.grid_ring(hid, 1)
        cluster = [hid] + [nb for nb in neighbors if nb in res8_hexes_set]
        
        smoothed_res8[hid] = {
            "premium": res8_counts.loc[cluster, "premium"].mean(),
            "midmarket": res8_counts.loc[cluster, "midmarket"].mean(),
            "economy": res8_counts.loc[cluster, "economy"].mean()
        }
        
    smoothed_df = pd.DataFrame.from_dict(smoothed_res8, orient="index")
    smoothed_dict = smoothed_df.to_dict(orient="index")
    
    # City-wide ratios fallback
    city_premium = smoothed_df["premium"].sum()
    city_midmarket = smoothed_df["midmarket"].sum()
    city_economy = smoothed_df["economy"].sum()
    city_total = city_premium + city_midmarket + city_economy
    if city_total > 0:
        city_ratios = {
            "premium": city_premium / city_total,
            "midmarket": city_midmarket / city_total,
            "economy": city_economy / city_total
        }
    else:
        city_ratios = {"premium": 0.33, "midmarket": 0.33, "economy": 0.34}
        
    # Initialize ratio, counts and capacity columns in grid_gdf (Res-7)
    grid_gdf["ratio_premium"] = 0.0
    grid_gdf["ratio_midmarket"] = 0.0
    grid_gdf["ratio_economy"] = 0.0
    grid_gdf["listings_premium"] = 0
    grid_gdf["listings_midmarket"] = 0
    grid_gdf["listings_economy"] = 0
    grid_gdf["capacity_mass"] = 0.0
    
    # Aggregate to Resolution-7
    grid_ratios = {}
    for idx, row in grid_gdf.iterrows():
        hid = row["hex_id"]
        children = h3.cell_to_children(hid, 8)
        
        sum_p = 0.0
        sum_m = 0.0
        sum_e = 0.0
        
        raw_p = 0
        raw_m = 0
        raw_e = 0
        
        for child in children:
            if child in smoothed_dict:
                c_vals = smoothed_dict[child]
                sum_p += c_vals["premium"]
                sum_m += c_vals["midmarket"]
                sum_e += c_vals["economy"]
            if child in res8_raw_counts.index:
                row_raw = res8_raw_counts.loc[child]
                raw_p += int(row_raw["premium"])
                raw_m += int(row_raw["midmarket"])
                raw_e += int(row_raw["economy"])
                
        tot = sum_p + sum_m + sum_e
        if tot > 0:
            grid_ratios[hid] = {
                "premium": sum_p / tot,
                "midmarket": sum_m / tot,
                "economy": sum_e / tot,
                "total": tot,
                "raw_p": raw_p,
                "raw_m": raw_m,
                "raw_e": raw_e
            }
        else:
            grid_ratios[hid] = None
            
    # Assign and interpolate
    for hid, ratios in grid_ratios.items():
        if ratios is not None:
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_premium"] = ratios["premium"]
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_midmarket"] = ratios["midmarket"]
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_economy"] = ratios["economy"]
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "listings_premium"] = ratios["raw_p"]
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "listings_midmarket"] = ratios["raw_m"]
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "listings_economy"] = ratios["raw_e"]
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "capacity_mass"] = ratios["total"]
        else:
            interpolated = False
            for r in range(1, 4):
                neighbors = h3.grid_ring(hid, r)
                nb_p = []
                nb_m = []
                nb_e = []
                for nb in neighbors:
                    if grid_ratios.get(nb) is not None:
                        nb_p.append(grid_ratios[nb]["premium"])
                        nb_m.append(grid_ratios[nb]["midmarket"])
                        nb_e.append(grid_ratios[nb]["economy"])
                if nb_p:
                    grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_premium"] = np.mean(nb_p)
                    grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_midmarket"] = np.mean(nb_m)
                    grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_economy"] = np.mean(nb_e)
                    interpolated = True
                    break
            if not interpolated:
                grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_premium"] = city_ratios["premium"]
                grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_midmarket"] = city_ratios["midmarket"]
                grid_gdf.loc[grid_gdf["hex_id"] == hid, "ratio_economy"] = city_ratios["economy"]
                
    re_filtered = valid_re.copy()
    # Map re_filtered hex_id to grid resolution (Res-7) for downstream rental index code compatibility
    re_filtered["hex_id"] = re_filtered.apply(
        lambda row: h3.latlng_to_cell(row.geometry.y, row.geometry.x, resolution), axis=1
    ) # Keep variable name for downstream mapping logic
        
    nonzero_before = len(grid_gdf[grid_gdf["capacity_mass"] > 0])
    logger.log(f"Raw capacity surface: {nonzero_before} hexes contain direct matching listings.")
    
    # 4. Smoothing based on config
    smoothing_method = city_config["smoothing"].get("method", "conditional_kring")
    smoothing_radius = city_config["smoothing"].get("k_ring_radius", 1)
    
    # We compute additions in a separate map to avoid order-dependence.
    additions = {hid: 0.0 for hid in grid_gdf["hex_id"]}
    grid_hexes_set = set(grid_gdf["hex_id"])
    
    # Fast lookups to avoid slow pandas .loc in loops
    habitable_map = dict(zip(grid_gdf["hex_id"], grid_gdf["is_habitable"]))
    mass_map = dict(zip(grid_gdf["hex_id"], grid_gdf["capacity_mass"]))
    
    for idx, row in grid_gdf[grid_gdf["capacity_mass"] > 0].iterrows():
        hid = row["hex_id"]
        center_mass = row["capacity_mass"]
        
        for r in range(1, smoothing_radius + 1):
            neighbors = h3.grid_ring(hid, r)
            weight = 0.2 / r  # Distance decay weight
            for nb in neighbors:
                if nb in grid_hexes_set and habitable_map.get(nb, False):
                    if smoothing_method == "conditional_kring":
                        if mass_map.get(nb, 0) > 0:
                            additions[nb] += center_mass * weight
                    else:
                        additions[nb] += center_mass * weight
                        
    # Add buffered contributions
    for hid, add_val in additions.items():
        if add_val > 0:
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "capacity_mass"] += add_val
            
    # 5. Compute smoothed Rental Index and Price-per-sqft Heatmap
    logger.log("Computing smoothed rental index and price-per-sqft heatmaps...")
    
    rent_listings = re_filtered[re_filtered["transaction_type"] == "Rent"]
    if rent_listings.empty and not re_gdf.empty:
        rent_listings = re_gdf[re_gdf["transaction_type"] == "Rent"]
        
    hex_to_rentals = {}
    for idx, row in rent_listings.iterrows():
        hid = row["hex_id"]
        if hid not in hex_to_rentals:
            hex_to_rentals[hid] = []
        hex_to_rentals[hid].append((row["price_inr"], row["price_per_sqft"]))
        
    grid_gdf["rental_index"] = 0.0
    grid_gdf["rental_ppsqft"] = 0.0
    
    for idx, row in grid_gdf.iterrows():
        hid = row["hex_id"]
        if not row["is_habitable"]:
            continue
            
        price_weight_accum = 0.0
        ppsqft_weight_accum = 0.0
        weighted_price_sum = 0.0
        weighted_ppsqft_sum = 0.0
        
        for r in range(4): # 0 to 3 ring disk
            ring = h3.grid_ring(hid, r) if r > 0 else [hid]
            weight = 1.0 / (1.0 + r)
            for nb_hid in ring:
                if nb_hid in hex_to_rentals:
                    for price, ppsqft in hex_to_rentals[nb_hid]:
                        if price > 0:
                            weighted_price_sum += price * weight
                            price_weight_accum += weight
                        if ppsqft > 0:
                            weighted_ppsqft_sum += ppsqft * weight
                            ppsqft_weight_accum += weight
                            
        if price_weight_accum > 0:
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "rental_index"] = weighted_price_sum / price_weight_accum
        if ppsqft_weight_accum > 0:
            grid_gdf.loc[grid_gdf["hex_id"] == hid, "rental_ppsqft"] = weighted_ppsqft_sum / ppsqft_weight_accum

    # 6. Compute Family Ratio: % of listings with 3+ BHK (family-sized) vs total
    #    This tells us if an area is predominantly family-oriented or bachelor/single occupant.
    logger.log("Computing family occupancy ratio and area premiumness signals...")
    
    grid_gdf["family_ratio"] = 0.0
    grid_gdf["premium_area_score"] = 0.0

    # Build per-Res7-hex BHK stats from all valid listings (not sample)
    if "bhk" in valid_re.columns:
        bhk_res7 = valid_re.copy()
        bhk_res7["hex_id_r7"] = bhk_res7.apply(
            lambda row: h3.latlng_to_cell(row.geometry.y, row.geometry.x, resolution), axis=1
        )
        
        # For each hex, calculate: family_ratio = count(bhk>=3) / count(total)
        # and premium_area_score = weighted ratio_premium (from grid) scaled 0-100
        hex_bhk = bhk_res7.groupby("hex_id_r7").apply(
            lambda g: pd.Series({
                "total_listings": len(g),
                "family_listings": (g["bhk"] >= 3).sum(),
                "bachelor_listings": (g["bhk"] <= 2).sum()
            })
        ).reset_index()
        hex_bhk.columns = ["hex_id", "total_listings", "family_listings", "bachelor_listings"]
        hex_bhk_dict = dict(zip(hex_bhk["hex_id"], zip(
            hex_bhk["total_listings"], hex_bhk["family_listings"], hex_bhk["bachelor_listings"]
        )))
        
        # Assign family ratio to grid, with ring-1 smoothing fallback
        for idx, row in grid_gdf.iterrows():
            hid = row["hex_id"]
            if not row["is_habitable"]:
                continue
            
            # Gather stats from this hex + ring-1 neighbors for smoothing
            total = 0
            family = 0
            for r in range(3):
                ring = h3.grid_ring(hid, r) if r > 0 else [hid]
                for nb in ring:
                    if nb in hex_bhk_dict:
                        t, f, b = hex_bhk_dict[nb]
                        total += t
                        family += f
            
            if total > 0:
                grid_gdf.at[idx, "family_ratio"] = round(family / total, 4)
            
            # Premium area score: combine ratio_premium (0-1) + ppsqft signal (0-1 normalized)
            # Score 0-100: how "premium" this hex is as a residential area
            r_prem = float(row.get("ratio_premium", 0.0))
            grid_gdf.at[idx, "premium_area_score"] = round(r_prem * 100.0, 1)

    # Send filtered RE points to map (using a max limit to avoid browser overload)
    sample_size = min(500, len(re_filtered))
    re_filtered_sample = re_filtered.sample(n=sample_size, random_state=42) if sample_size > 0 else re_filtered
    re_filtered_geojson = gdf_to_geojson_dict(re_filtered_sample)
    
    logger.add_points("RE (Filtered)", re_filtered_geojson, style={
        "color": "#9B59B6",
        "radius": 4,
        "popup_fields": ["price_inr", "bhk", "property_type", "transaction_type"]
    })
    
    # Send choropleth of capacity mass
    habitable_grid = grid_gdf[grid_gdf["is_habitable"] == True].copy()
    logger.add_choropleth("Capacity Mass", gdf_to_geojson_dict(habitable_grid), value_field="capacity_mass", color_scale="Purples")
    
    nonzero_after = len(grid_gdf[grid_gdf["capacity_mass"] > 0])
    logger.layer_end(3, f"Capacity surface complete: {nonzero_after} hexes have non-zero mass.")
    
    # Save to cache
    os.makedirs("data/processed", exist_ok=True)
    grid_gdf.to_parquet("data/processed/re_surface.parquet")
    
    return grid_gdf

