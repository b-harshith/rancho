import os
import json
import geopandas as gpd
import pandas as pd
import numpy as np
import osmnx as ox
import h3
from shapely.geometry import Point, Polygon, MultiPolygon
from catchmentiq.utils.geo_helpers import gdf_to_geojson_dict

def extract_overture_name(names_dict) -> str:
    """Extract primary common name from Overture names dictionary."""
    if not isinstance(names_dict, dict):
        return ""
    p = names_dict.get("primary")
    if p and isinstance(p, str):
        return p
    c_list = names_dict.get("common", [])
    if c_list and isinstance(c_list, list):
        first = c_list[0]
        if isinstance(first, list) and len(first) > 1:
            return first[1]
        elif isinstance(first, dict):
            return first.get("value", "")
    return ""

def extract_overture_cat(cat_dict) -> str:
    """Extract main category from Overture categories dictionary."""
    if not isinstance(cat_dict, dict):
        return ""
    return cat_dict.get("main", "")

def match_local_pois(overture_gdf, category: str, google_type: str, keywords: list) -> list:
    """Find matching POIs in local Overture dataset."""
    matches = []
    
    # Map google types to overture/OSM subclasses
    type_mappings = {
        "car_dealer": ["car_dealer", "car_dealership", "motorvehicle_dealer", "retail_car"],
        "school": ["school", "educational_institution", "kindergarten"],
        "supermarket": ["supermarket", "grocery", "grocery_store", "grocery_market", "retail_food"],
        "gym": ["gym", "fitness_center", "sports_facility", "athletic_club"],
        "restaurant": ["restaurant", "cafe", "food_court", "dining"],
        "office": ["office", "business_park", "commercial", "company"]
    }
    
    target_subclasses = type_mappings.get(google_type, [google_type])
    
    for idx, row in overture_gdf.iterrows():
        try:
            # We check if geometry is a Point. In bangalore_no_buildings, POIs are points or small polygons.
            # Get primary name
            name = extract_overture_name(row.get("names"))
            cat = extract_overture_cat(row.get("categories"))
            subclass = row.get("subclass") or ""
            
            # Check subclass / category matching
            cat_match = (cat in target_subclasses) or (subclass in target_subclasses) or (row.get("class") in target_subclasses)
            
            # Check keyword matching
            keyword_match = False
            if keywords and name:
                name_l = name.lower()
                keyword_match = any(k.lower() in name_l for k in keywords)
                
            # Decisions
            is_match = False
            if google_type == "car_dealer":
                # For luxury cars, it must match car dealer AND have luxury keywords
                is_match = cat_match and keyword_match
            elif google_type == "supermarket":
                # If keywords are specified (premium vs value), match them
                if keywords:
                    is_match = cat_match and keyword_match
                else:
                    is_match = cat_match
            elif google_type == "school":
                # For international schools, name must contain keywords
                if keywords:
                    is_match = cat_match and keyword_match
                else:
                    is_match = cat_match
            else:
                # General match
                is_match = cat_match or (keywords and keyword_match)
                
            if is_match and name:
                geom = row.geometry
                # If geometry is a polygon, get centroid
                if geom.type != "Point":
                    geom = geom.centroid
                matches.append({
                    "name": name,
                    "category": category,
                    "lat": geom.y,
                    "lon": geom.x,
                    "geometry": geom
                })
        except Exception:
            continue
            
    return matches

def fetch_osm_pois(category: str, google_type: str, keywords: list, city_name: str = "Bangalore, India") -> list:
    """Fallback fetch POIs from OpenStreetMap using OSMnx when local results are empty."""
    matches = []
    
    # Map type to OSM tags
    osm_tags = {}
    if google_type == "car_dealer":
        osm_tags = {"shop": "car"}
    elif google_type == "school":
        osm_tags = {"amenity": "school"}
    elif google_type == "supermarket":
        osm_tags = {"shop": "supermarket"}
    elif google_type == "gym":
        osm_tags = {"leisure": "fitness_centre"}
    elif google_type == "restaurant":
        osm_tags = {"amenity": "restaurant"}
    elif google_type == "office":
        osm_tags = {"landuse": "commercial", "office": True}
        
    try:
        gdf = ox.features_from_place(city_name, tags=osm_tags)
        if gdf.empty:
            return []
            
        for idx, row in gdf.iterrows():
            name = row.get("name")
            if not name or pd.isna(name):
                continue
                
            # Filter keywords
            keyword_match = True
            if keywords:
                name_l = name.lower()
                keyword_match = any(k.lower() in name_l for k in keywords)
                
            if keyword_match:
                geom = row.geometry
                if geom.type != "Point":
                    geom = geom.centroid
                matches.append({
                    "name": name,
                    "category": category,
                    "lat": geom.y,
                    "lon": geom.x,
                    "geometry": geom
                })
    except Exception:
        pass
        
    return matches

def run(grid_gdf: gpd.GeoDataFrame, wards_gdf: gpd.GeoDataFrame, tier_config: dict, poi_config: list, logger) -> tuple[gpd.GeoDataFrame, list, gpd.GeoDataFrame]:
    """
    Execute POI validation and ward-level proximity analysis.
    """
    logger.layer_start(6, "POI Validation & Ward Proximity")
    
    city_center = city_config_center = [12.9716, 77.5946] # default Bangalore
    resolution = grid_gdf["hex_id"].iloc[0] # check res
    res_val = h3.get_resolution(resolution)
    
    # ---- 1. Fetch / Load POIs ----
    logger.log("Matching POIs from local Overture dataset...")
    
    overture_path = "overture/bangalore_no_buildings.geojson"
    overture_gdf = None
    if os.path.exists(overture_path):
        try:
            overture_gdf = gpd.read_file(overture_path)
            # Filter to POIs (place layer)
            overture_gdf = overture_gdf[overture_gdf["layer_type"] == "place"].copy()
            logger.log(f"Loaded {len(overture_gdf)} POIs from Overture.")
        except Exception as e:
            logger.log(f"Failed to load Overture: {e}. Will use OSM fallback.", "warning")
            
    all_pois = []
    
    for category_item in poi_config:
        cat_name = category_item["category"]
        google_type = category_item["google_type"]
        keywords = category_item.get("keywords", [])
        weight = category_item["weight"]
        
        cat_matches = []
        if overture_gdf is not None:
            cat_matches = match_local_pois(overture_gdf, cat_name, google_type, keywords)
            
        # Fallback to OSM query if no local matches
        if len(cat_matches) < 5:
            logger.log(f"Low local matches for {cat_name} ({len(cat_matches)}). Fetching from OSM...")
            osm_matches = fetch_osm_pois(cat_name, google_type, keywords)
            cat_matches.extend(osm_matches)
            
        # De-duplicate matches by name & location similarity
        unique_matches = []
        seen = set()
        for m in cat_matches:
            # unique key by rounded coords
            key = (m["name"].lower().strip(), round(m["lat"], 4), round(m["lon"], 4))
            if key not in seen:
                seen.add(key)
                m["weight"] = weight
                unique_matches.append(m)
                
        logger.log(f"Found {len(unique_matches)} POIs for category: {cat_name}")
        all_pois.extend(unique_matches)
        
    if not all_pois:
        logger.log("No validation POIs found. Validating all top-scoring zones by default.", "warning")
        grid_gdf["poi_density"] = 0.0
        grid_gdf["poi_validated"] = grid_gdf["percentile_score"] >= 90
        grid_gdf["ward_name"] = "Outskirts"
        grid_gdf["ward_poi_score"] = 0.0
        
        # Create empty POI GeoDataFrame
        empty_gdf = gpd.GeoDataFrame(columns=["name", "category", "weight", "geometry"], geometry="geometry", crs="EPSG:4326")
        return grid_gdf, [], empty_gdf
        
    pois_gdf = gpd.GeoDataFrame(all_pois, geometry="geometry", crs="EPSG:4326")
    
    # Send POI points to map
    logger.add_points("POIs", gdf_to_geojson_dict(pois_gdf), style={
        "color": "#F1C40F",
        "radius": 5,
        "popup_fields": ["name", "category"]
    })
    
    # ---- 2. Hex-Level POI Density ----
    # Assign each POI to its H3 cell
    pois_gdf["hex_id"] = pois_gdf.apply(
        lambda row: h3.latlng_to_cell(row.geometry.y, row.geometry.x, res_val), axis=1
    )
    
    # Compute distance-decayed density per hex
    grid_gdf["poi_density"] = 0.0
    for idx, row in grid_gdf.iterrows():
        hid = row["hex_id"]
        
        density = 0.0
        # Multi-ring distance decay for POI density
        for r in range(3): # Ring 0, 1, 2
            ring = h3.grid_ring(hid, r) if r > 0 else [hid]
            weight_factor = 1.0 / (1.0 + r) # 1.0, 0.5, 0.33
            
            nearby_pois = pois_gdf[pois_gdf["hex_id"].isin(ring)]
            if not nearby_pois.empty:
                density += nearby_pois["weight"].sum() * weight_factor
                
        grid_gdf.loc[grid_gdf["hex_id"] == hid, "poi_density"] = density
        
    # Validation flag: top-scoring hexes with above-median POI density
    active_poi_hexes = grid_gdf[grid_gdf["poi_density"] > 0]
    median_poi = active_poi_hexes["poi_density"].median() if not active_poi_hexes.empty else 0.0
    logger.log(f"Median non-zero hex POI density score: {median_poi:.2f}")
    
    grid_gdf["poi_validated"] = (
        (grid_gdf["percentile_score"] >= 90) &
        (grid_gdf["poi_density"] >= median_poi)
    )
    
    # Add validation status layers to map
    validated_hexes = grid_gdf[(grid_gdf["is_habitable"] == True) & (grid_gdf["poi_validated"] == True)].copy()
    unvalidated_hexes = grid_gdf[(grid_gdf["is_habitable"] == True) & (grid_gdf["percentile_score"] >= 90) & (grid_gdf["poi_validated"] == False)].copy()
    
    logger.add_polygons("Validated ✅", gdf_to_geojson_dict(validated_hexes), style={
        "fill_color": "#2ECC71", "fill_opacity": 0.35, "stroke_color": "#27AE60", "stroke_width": 2
    })
    logger.add_polygons("Unvalidated ⚠️", gdf_to_geojson_dict(unvalidated_hexes), style={
        "fill_color": "#E67E22", "fill_opacity": 0.20, "stroke_color": "#D35400", "stroke_width": 1.5
    })
    
    # ---- 3. Ward-Level POI Proximity ----
    logger.log("Computing ward-level POI proximity scores...")
    
    # Load or download wards
    if wards_gdf is None or len(wards_gdf) == 0:
        logger.log("Wards file missing, downloading Bangalore admin_level=10 boundaries from OSM...")
        try:
            downloaded_wards = ox.features_from_place("Bangalore, India", tags={"admin_level": "10"})
            downloaded_wards = downloaded_wards[downloaded_wards.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
            downloaded_wards = downloaded_wards[downloaded_wards["name"].notna()].copy()
            wards_gdf = downloaded_wards.reset_index(drop=True)
            logger.log(f"Successfully downloaded {len(wards_gdf)} wards.")
            # Cache locally
            os.makedirs("data/boundaries", exist_ok=True)
            wards_gdf.to_file("data/boundaries/bangalore_wards.geojson", driver="GeoJSON")
        except Exception as e:
            logger.log(f"Failed to fetch OSM wards: {e}. Generating bounding box grid as placeholder wards.", "warning")
            # Create a 4x4 grid of polygon bounding box divisions as fake wards
            minx, miny, maxx, maxy = grid_gdf.total_bounds
            x_coords = np.linspace(minx, maxx, 5)
            y_coords = np.linspace(miny, maxy, 5)
            fake_wards = []
            ward_idx = 1
            for ix in range(4):
                for iy in range(4):
                    poly = Polygon([
                        (x_coords[ix], y_coords[iy]),
                        (x_coords[ix], y_coords[iy+1]),
                        (x_coords[ix+1], y_coords[iy+1]),
                        (x_coords[ix+1], y_coords[iy]),
                    ])
                    fake_wards.append({
                        "name": f"Ward Subzone {ward_idx}",
                        "geometry": poly
                    })
                    ward_idx += 1
            wards_gdf = gpd.GeoDataFrame(fake_wards, geometry="geometry", crs="EPSG:4326")
            
    # Project to metric CRS for distance calculations (UTM 43N)
    wards_projected = wards_gdf.to_crs(epsg=32643)
    pois_projected = pois_gdf.to_crs(epsg=32643)
    
    ward_scores = []
    
    for w_idx, ward in wards_gdf.iterrows():
        ward_poly_proj = wards_projected.loc[w_idx].geometry
        ward_centroid_proj = ward_poly_proj.centroid
        
        ward_result = {
            "ward_name": ward["name"],
            "ward_id": w_idx,
            "category_scores": {}
        }
        
        total_proximity_score = 0.0
        
        for category_item in poi_config:
            cat_name = category_item["category"]
            cat_weight = category_item["weight"]
            
            cat_pois = pois_projected[pois_projected["category"] == cat_name]
            
            if cat_pois.empty:
                ward_result["category_scores"][cat_name] = {
                    "nearest_meters": None,
                    "count_within_2km": 0,
                    "proximity_factor": 0.0
                }
                continue
                
            # Distances from ward centroid to all POIs of this category
            # use geometry distance function
            distances = cat_pois.geometry.distance(ward_centroid_proj)
            nearest_dist = distances.min() # meters
            count_2km = (distances <= 2000.0).sum()
            
            # Proximity factor: 1.0 at center, 0.0 at >= 5km
            max_dist = 5000.0
            proximity_factor = max(0.0, 1.0 - (nearest_dist / max_dist))
            
            weighted_score = cat_weight * proximity_factor
            total_proximity_score += weighted_score
            
            ward_result["category_scores"][cat_name] = {
                "nearest_meters": int(round(nearest_dist)),
                "count_within_2km": int(count_2km),
                "proximity_factor": round(proximity_factor, 3)
            }
            
        ward_result["total_proximity_score"] = round(total_proximity_score, 3)
        ward_scores.append(ward_result)
        
    # Scored wards GeoDataFrame
    wards_scored = wards_gdf.copy()
    wards_scored["ward_poi_score"] = [ws["total_proximity_score"] for ws in ward_scores]
    wards_scored["ward_name"] = wards_gdf["name"]
    
    # Assign each hex to its ward via spatial join on hex centroid
    grid_centroids = grid_gdf.copy()
    grid_centroids["geometry"] = grid_centroids.geometry.centroid
    
    joined_wards = gpd.sjoin(grid_centroids, wards_scored[["ward_name", "ward_poi_score", "geometry"]], how="left", predicate="within")
    
    # Merge the ward_name and ward_poi_score back to grid_gdf
    # Create dict mapping hex_id to ward info
    hex_ward_map = {}
    for idx, row in joined_wards.iterrows():
        hex_ward_map[row["hex_id"]] = {
            "ward_name": row["ward_name"] if pd.notna(row["ward_name"]) else "Outskirts",
            "ward_poi_score": row["ward_poi_score"] if pd.notna(row["ward_poi_score"]) else 0.0
        }
        
    grid_gdf["ward_name"] = grid_gdf["hex_id"].apply(lambda hid: hex_ward_map.get(hid, {}).get("ward_name", "Outskirts"))
    grid_gdf["ward_poi_score"] = grid_gdf["hex_id"].apply(lambda hid: hex_ward_map.get(hid, {}).get("ward_poi_score", 0.0))
    
    # Add Ward Proximity score to map
    logger.add_choropleth("Ward POI Proximity", gdf_to_geojson_dict(wards_scored), value_field="ward_poi_score", color_scale="BuGn")
    
    validated_count = len(validated_hexes)
    logger.log(f"Ward proximity mapped for {len(wards_gdf)} wards.")
    logger.layer_end(6, f"Validation complete. {validated_count} hot-zones validated by POI data.")
    
    return grid_gdf, ward_scores, pois_gdf
