import os
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, MultiPolygon
from concurrent.futures import ThreadPoolExecutor, as_completed
from catchmentiq.utils.osrm_client import get_isochrone
from catchmentiq.utils.geo_helpers import gdf_to_geojson_dict

def matches_tier_boards(school_boards: list, tier_boards: list) -> bool:
    """Check if any school board matches any preferred tier board (case-insensitive substring match)."""
    if not school_boards:
        return False
    school_boards_lower = [b.lower() for b in school_boards]
    for tb in tier_boards:
        tb_l = tb.lower()
        if any(tb_l in sb or sb in tb_l for sb in school_boards_lower):
            return True
        if tb_l == "cambridge" and any("igcse" in sb or "cie" in sb for sb in school_boards_lower):
            return True
        if tb_l == "state" and any("state" in sb or "sslc" in sb for sb in school_boards_lower):
            return True
    return False

def compute_school_bands(school_row, bands, osrm_url, profile) -> list:
    """Compute banded isochrone polygons for a single school."""
    school_name = school_row["name"]
    lat = school_row.geometry.y
    lon = school_row.geometry.x
    
    results = []
    prev_poly = None
    sorted_bands = sorted(bands)
    
    for minutes in sorted_bands:
        full_poly = get_isochrone(lat, lon, minutes, osrm_url, profile)
        
        if prev_poly:
            try:
                band_poly = full_poly.difference(prev_poly)
            except Exception:
                band_poly = full_poly
        else:
            band_poly = full_poly
            
        if band_poly.is_empty:
            band_poly = full_poly
            
        band_name = f"0-{sorted_bands[0]}" if not prev_poly else f"{sorted_bands[sorted_bands.index(minutes)-1]}-{minutes}"
        midpoint = minutes / 2 if not prev_poly else (minutes + sorted_bands[sorted_bands.index(minutes)-1]) / 2
        
        results.append({
            "school_name": school_name,
            "school_id": school_row.get("id", school_name),
            "band": band_name,
            "band_midpoint_minutes": midpoint,
            "geometry": band_poly
        })
        
        prev_poly = full_poly
        
    return results

def run(schools_gdf: gpd.GeoDataFrame, tier_config: dict, city_config: dict, logger, use_cache: bool = False) -> gpd.GeoDataFrame:
    """
    Generate drive-time catchment zones (isochrone bands) for each filtered school.
    Supports OSRM (forward) and TravelTime (true arrival-based reverse) engines.
    Clips and subtracts uninhabitable zones from all resulting geometries.
    """
    logger.layer_start(1, "School Catchments (Isochrones)")
    
    cache_path = "data/processed/isochrones.parquet"
    if os.path.exists(cache_path):
        logger.log("Loading isochrones from cache...")
        isochrones_gdf = gpd.read_parquet(cache_path)
        logger.log(f"Loaded {len(isochrones_gdf)} isochrone bands from cache.")
        
        BAND_STYLES = {
            "0-10":  {"fill_color": "#27AE60", "fill_opacity": 0.20, "stroke_color": "#27AE60", "stroke_width": 0.5},
            "10-20": {"fill_color": "#F39C12", "fill_opacity": 0.12, "stroke_color": "#F39C12", "stroke_width": 0.5},
            "20-30": {"fill_color": "#E74C3C", "fill_opacity": 0.06, "stroke_color": "#E74C3C", "stroke_width": 0.5},
        }
        for band_name, style in BAND_STYLES.items():
            band_subset = isochrones_gdf[isochrones_gdf["band"] == band_name]
            if not band_subset.empty:
                logger.add_polygons(f"Isochrones {band_name}", gdf_to_geojson_dict(band_subset), style=style)
                
        logger.layer_end(1, f"{len(isochrones_gdf)} isochrone bands loaded from cache")
        return isochrones_gdf

    # ---- 1. Filter schools to tier specifications ----
    fee_min = tier_config["school_fee_min"]
    fee_max = tier_config.get("school_fee_max")
    boards = tier_config["school_boards"]
    
    filtered_schools = schools_gdf[
        (schools_gdf["avg_fee"] >= fee_min) &
        (schools_gdf["board"].apply(lambda b: matches_tier_boards(b, boards)))
    ].copy()
    
    if fee_max is not None:
        filtered_schools = filtered_schools[filtered_schools["avg_fee"] <= fee_max]
        
    logger.log(f"Filtered schools list size: {len(filtered_schools)} matching fee range and boards.")
    if len(filtered_schools) == 0:
        logger.log("No schools match the filter criteria. Using all schools as fallback.", "warning")
        filtered_schools = schools_gdf.copy()
        
    engine = city_config["isochrones"].get("engine", "osrm")
    bands = city_config["isochrones"]["bands_minutes"]
    profile = city_config["isochrones"]["profile"]
    
    # ---- 2. Construct City Boundary from Config Bounding Box ----
    logger.log("Preparing boundary and land-use mask for isochrone clipping (using bounding box limits)...")
    bbox = city_config["city"]["bounding_box"]
    city_boundary = Polygon([
        (bbox["min_lon"], bbox["min_lat"]),
        (bbox["min_lon"], bbox["max_lat"]),
        (bbox["max_lon"], bbox["max_lat"]),
        (bbox["max_lon"], bbox["min_lat"])
    ])
        
    overture_path = "overture/bangalore_no_buildings.geojson"
    mask_geom = None
    if os.path.exists(overture_path):
        try:
            overture_gdf = gpd.read_file(overture_path)
            mask_classes = ["industrial", "military", "reservoir", "water"]
            mask_gdf = overture_gdf[
                (overture_gdf["layer_type"] == "water") |
                (overture_gdf["class"].isin(mask_classes))
            ].copy()
            mask_gdf = mask_gdf[mask_gdf.geometry.intersects(city_boundary.envelope)]
            if not mask_gdf.empty:
                mask_geom = mask_gdf.unary_union
                logger.log("Land-use mask prepared.")
        except Exception as e:
            logger.log(f"Failed to prepare land-use mask: {e}", "warning")
            
    def clean_and_subtract_geom(geom):
        if geom is None or geom.is_empty:
            return None
        try:
            # Keep only portion inside city boundary
            clipped = geom.intersection(city_boundary)
            if clipped.is_empty:
                return geom
            # Subtract uninhabitable zones
            if mask_geom is not None:
                subtracted = clipped.difference(mask_geom)
                if not subtracted.is_empty:
                    return subtracted
            return clipped
        except Exception:
            return geom

    # ---- 3. Isochrone Computation ----
    raw_records = []
    
    if engine == "traveltime":
        app_id = city_config["isochrones"]["traveltime_app_id"]
        api_key = city_config["isochrones"]["traveltime_api_key"]
        
        logger.log(f"Using TravelTime API for true arrival-based reverse isochrone calculations...")
        searches = []
        for idx, school in filtered_schools.iterrows():
            school_name = school["name"]
            school_id = school.get("id", school_name)
            lat = school.geometry.y
            lon = school.geometry.x
            for mins in bands:
                searches.append({
                    "id": f"{school_id}__{mins}",
                    "lat": lat,
                    "lon": lon,
                    "travel_time_seconds": mins * 60,
                    "transportation_type": profile,
                    "arrival_time": "2026-06-08T08:30:00Z" # Morning arrival time (Monday)
                })
                
        from catchmentiq.utils.traveltime_client import get_traveltime_isochrones
        raw_polygons = get_traveltime_isochrones(searches, app_id, api_key, logger)
        
        logger.log("Processing and banding TravelTime reverse isochrones...")
        for idx, school in filtered_schools.iterrows():
            school_name = school["name"]
            school_id = school.get("id", school_name)
            
            poly_10 = raw_polygons.get(f"{school_id}__10")
            poly_20 = raw_polygons.get(f"{school_id}__20")
            poly_30 = raw_polygons.get(f"{school_id}__30")
            
            if poly_10:
                band_0_10 = clean_and_subtract_geom(poly_10)
                if band_0_10:
                    raw_records.append({
                        "school_name": school_name, "school_id": school_id,
                        "band": "0-10", "band_midpoint_minutes": 5.0, "geometry": band_0_10
                    })
                    
            if poly_20:
                diff = poly_20.difference(poly_10) if poly_10 else poly_20
                band_10_20 = clean_and_subtract_geom(diff)
                if band_10_20:
                    raw_records.append({
                        "school_name": school_name, "school_id": school_id,
                        "band": "10-20", "band_midpoint_minutes": 15.0, "geometry": band_10_20
                    })
                    
            if poly_30:
                diff = poly_30.difference(poly_20) if poly_20 else poly_30
                band_20_30 = clean_and_subtract_geom(diff)
                if band_20_30:
                    raw_records.append({
                        "school_name": school_name, "school_id": school_id,
                        "band": "20-30", "band_midpoint_minutes": 25.0, "geometry": band_20_30
                    })
    elif engine == "ors":
        api_key = city_config["isochrones"].get("ors_api_key")
        logger.log(f"Using OpenRouteService API for forward isochrone calculations...")
        
        from catchmentiq.utils.ors_client import get_ors_isochrones
        import time
        
        # Map generic profile to ORS specific
        ors_profile = "driving-car" if profile == "driving" else profile
        
        completed_schools_count = 0
        for idx, school in filtered_schools.iterrows():
            school_name = school["name"]
            school_id = school.get("id", school_name)
            lat = school.geometry.y
            lon = school.geometry.x
            
            raw_polys = get_ors_isochrones(lat, lon, bands, api_key, logger, ors_profile)
            
            poly_10 = raw_polys.get(10)
            poly_20 = raw_polys.get(20)
            poly_30 = raw_polys.get(30)
            
            if poly_10:
                band_0_10 = clean_and_subtract_geom(poly_10)
                if band_0_10:
                    raw_records.append({
                        "school_name": school_name, "school_id": school_id,
                        "band": "0-10", "band_midpoint_minutes": 5.0, "geometry": band_0_10
                    })
                    
            if poly_20:
                diff = poly_20.difference(poly_10) if poly_10 else poly_20
                band_10_20 = clean_and_subtract_geom(diff)
                if band_10_20:
                    raw_records.append({
                        "school_name": school_name, "school_id": school_id,
                        "band": "10-20", "band_midpoint_minutes": 15.0, "geometry": band_10_20
                    })
                    
            if poly_30:
                diff = poly_30.difference(poly_20) if poly_20 else poly_30
                band_20_30 = clean_and_subtract_geom(diff)
                if band_20_30:
                    raw_records.append({
                        "school_name": school_name, "school_id": school_id,
                        "band": "20-30", "band_midpoint_minutes": 25.0, "geometry": band_20_30
                    })
                    
            completed_schools_count += 1
            if completed_schools_count % 10 == 0 or completed_schools_count == len(filtered_schools):
                logger.log(f"ORS Isochrone progress: {completed_schools_count}/{len(filtered_schools)} processed")
            
            time.sleep(1.6) # Limit to ~37 requests per minute
            
    elif engine == "none" or engine == "buffer":
        logger.log("Isochrone engine set to 'none' or 'buffer'. Generating geometric distance buffers as catchments.")
        # 1km is approx 0.009 degrees
        for idx, school in filtered_schools.iterrows():
            school_name = school["name"]
            school_id = school.get("id", school_name)
            pt = school.geometry
            
            poly_10 = pt.buffer(3.5 * 0.009)
            poly_20 = pt.buffer(5.5 * 0.009)
            poly_30 = pt.buffer(7.5 * 0.009)
            
            band_0_10 = clean_and_subtract_geom(poly_10)
            if band_0_10:
                raw_records.append({
                    "school_name": school_name, "school_id": school_id,
                    "band": "0-10", "band_midpoint_minutes": 5.0, "geometry": band_0_10
                })
            band_10_20 = clean_and_subtract_geom(poly_20.difference(poly_10))
            if band_10_20:
                raw_records.append({
                    "school_name": school_name, "school_id": school_id,
                    "band": "10-20", "band_midpoint_minutes": 15.0, "geometry": band_10_20
                })
            band_20_30 = clean_and_subtract_geom(poly_30.difference(poly_20))
            if band_20_30:
                raw_records.append({
                    "school_name": school_name, "school_id": school_id,
                    "band": "20-30", "band_midpoint_minutes": 25.0, "geometry": band_20_30
                })
    else:
        # Fallback to OSRM engine
        osrm_url = city_config["isochrones"]["osrm_url"]
        logger.log(f"Using OSRM engine at {osrm_url} (profile: {profile})")
        
        completed_schools_count = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(compute_school_bands, row, bands, osrm_url, profile): idx 
                for idx, row in filtered_schools.iterrows()
            }
            
            for future in as_completed(futures):
                try:
                    school_records = future.result()
                    for rec in school_records:
                        cleaned_poly = clean_and_subtract_geom(rec["geometry"])
                        if cleaned_poly:
                            rec["geometry"] = cleaned_poly
                            raw_records.append(rec)
                except Exception as e:
                    school_idx = futures[future]
                    school_name = filtered_schools.loc[school_idx, "name"]
                    logger.log(f"Failed to compute OSRM isochrone for school {school_name}: {e}", "warning")
                    
                completed_schools_count += 1
                if completed_schools_count % 25 == 0 or completed_schools_count == len(filtered_schools):
                    logger.log(f"OSRM Isochrone progress: {completed_schools_count}/{len(filtered_schools)} processed")
                    
    isochrones_gdf = gpd.GeoDataFrame(raw_records, geometry="geometry", crs="EPSG:4326")
    logger.log(f"Generated {len(isochrones_gdf)} total subtracted isochrone band polygons.")
    
    # Send layers to map
    BAND_STYLES = {
        "0-10":  {"fill_color": "#27AE60", "fill_opacity": 0.20, "stroke_color": "#27AE60", "stroke_width": 0.5},
        "10-20": {"fill_color": "#F39C12", "fill_opacity": 0.12, "stroke_color": "#F39C12", "stroke_width": 0.5},
        "20-30": {"fill_color": "#E74C3C", "fill_opacity": 0.06, "stroke_color": "#E74C3C", "stroke_width": 0.5},
    }
    for band_name, style in BAND_STYLES.items():
        band_subset = isochrones_gdf[isochrones_gdf["band"] == band_name]
        if not band_subset.empty:
            logger.add_polygons(f"Isochrones {band_name}", gdf_to_geojson_dict(band_subset), style=style)
            
    # Cache results
    os.makedirs("data/processed", exist_ok=True)
    isochrones_gdf.to_parquet(cache_path)
    logger.log("Layer 1 Isochrones cached to data/processed/", "success")
    
    logger.layer_end(1, f"{len(isochrones_gdf)} isochrone band polygons created")
    return isochrones_gdf
