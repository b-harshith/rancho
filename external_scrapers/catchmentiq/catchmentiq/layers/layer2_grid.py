import os
import geopandas as gpd
import pandas as pd
import osmnx as ox
import h3
from shapely.geometry import Polygon, MultiPolygon, Point
from catchmentiq.utils.h3_helpers import get_hex_polygon
from catchmentiq.utils.geo_helpers import gdf_to_geojson_dict

def run(city_config: dict, logger, use_cache: bool = False) -> gpd.GeoDataFrame:
    """
    Generate H3 hex grid and mask out uninhabitable areas.
    """
    logger.layer_start(2, "H3 Grid & Habitability Masking")
    resolution = city_config["grid"]["h3_resolution"]
    
    cache_path = "data/processed/h3_grid_masked.parquet"
    if use_cache and os.path.exists(cache_path):
        logger.log("Loading H3 grid and mask from cache...")
        grid_gdf = gpd.read_file(cache_path) if cache_path.endswith('.geojson') else gpd.read_parquet(cache_path)
        
        if not grid_gdf.empty and "hex_id" in grid_gdf.columns:
            cached_res = h3.get_resolution(grid_gdf["hex_id"].iloc[0])
            if cached_res == resolution:
                # Log counts
                total = len(grid_gdf)
                active = len(grid_gdf[grid_gdf["is_habitable"] == True])
                pct = (active / total) * 100 if total > 0 else 0
                logger.log(f"Loaded {total} hexes from cache at resolution {cached_res}. {active} habitable ({pct:.1f}%).")
                
                # Send layers to map
                logger.add_polygons("H3 Grid", gdf_to_geojson_dict(grid_gdf[grid_gdf["is_habitable"] == True]), style={
                    "fill_color": "#2C3E50", "fill_opacity": 0.05, "stroke_color": "#34495E", "stroke_width": 0.5
                })
                logger.add_polygons("Masked Hexes", gdf_to_geojson_dict(grid_gdf[grid_gdf["is_habitable"] == False]), style={
                    "fill_color": "#E74C3C", "fill_opacity": 0.35, "stroke_color": "#C0392B", "stroke_width": 0.5
                })
                
                logger.layer_end(2, f"{active} habitable hexes loaded from cache")
                return grid_gdf
            else:
                logger.log(f"Cached grid resolution ({cached_res}) does not match configured resolution ({resolution}). Regenerating H3 grid...")


    city_name = city_config["city"]["name"]
    resolution = city_config["grid"]["h3_resolution"]
    
    # 1. Construct City Boundary from Config Bounding Box
    logger.log("Constructing boundary from bounding box configuration to cover outer areas...")
    bbox = city_config["city"]["bounding_box"]
    city_boundary = Polygon([
        (bbox["min_lon"], bbox["min_lat"]),
        (bbox["min_lon"], bbox["max_lat"]),
        (bbox["max_lon"], bbox["max_lat"]),
        (bbox["max_lon"], bbox["min_lat"])
    ])
        
    # 2. Generate H3 Hexes
    logger.log(f"Generating H3 grid at resolution {resolution}...")
    
    def shapely_to_h3_shape(geom):
        if isinstance(geom, Polygon):
            outer = [(lat, lon) for lon, lat in geom.exterior.coords]
            holes = [[(lat, lon) for lon, lat in hole.coords] for hole in geom.interiors]
            return h3.LatLngPoly(outer, *holes)
        elif isinstance(geom, MultiPolygon):
            h3_polys = []
            for poly in geom.geoms:
                outer = [(lat, lon) for lon, lat in poly.exterior.coords]
                holes = [[(lat, lon) for lon, lat in poly.interiors] for hole in poly.interiors]
                h3_polys.append(h3.LatLngPoly(outer, *holes))
            return h3.LatLngMultiPoly(*h3_polys)
        raise ValueError("Unsupported shape type")

    h3_boundary = shapely_to_h3_shape(city_boundary)
    hex_ids = list(h3.polygon_to_cells(h3_boundary, resolution))
    
    # Construct Grid GeoDataFrame
    hex_records = []
    for hid in hex_ids:
        poly = get_hex_polygon(hid)
        hex_records.append({
            "hex_id": hid,
            "geometry": poly
        })
        
    grid_gdf = gpd.GeoDataFrame(hex_records, geometry="geometry", crs="EPSG:4326")
    logger.log(f"Generated {len(grid_gdf)} hexes covering the city.")
    
    # 3. Habitability Masking
    logger.log("Performing habitability masking using Overture features...")
    overture_path = "overture/bangalore_no_buildings.geojson"
    if not os.path.exists(overture_path):
        logger.log(f"Overture data not found at {overture_path}, skipping masking step.", "warning")
        grid_gdf["is_habitable"] = True
    else:
        logger.log("Loading land-use features from Overture GeoJSON...")
        # Load overture dataset
        overture_gdf = gpd.read_file(overture_path)
        
        # Filter mask sources from config:
        # - natural=water -> water features
        # - landuse=industrial / military -> industrial & military zones
        # - reservoir/swimming_pool/etc.
        mask_classes = city_config["grid"].get("mask_sources", ["water", "industrial", "military"])
        if "water" in mask_classes and "reservoir" not in mask_classes:
            mask_classes.append("reservoir")
            
        mask_gdf = overture_gdf[
            (overture_gdf["layer_type"] == "water") |
            (overture_gdf["class"].isin(mask_classes))
        ].copy()
        
        logger.log(f"Found {len(mask_gdf)} mask feature geometries (lakes, industrial zones, cantonments).")
        
        # Filter to only mask features that overlap with city bounds to keep spatial index small
        mask_gdf = mask_gdf[mask_gdf.geometry.intersects(city_boundary.envelope)]
        
        # Compute centroids of grid hexes
        centroids_gdf = gpd.GeoDataFrame(
            grid_gdf[["hex_id"]], 
            geometry=grid_gdf.geometry.centroid, 
            crs="EPSG:4326"
        )
        
        # Spatial join: find which hex centroids are within mask polygons
        joined = gpd.sjoin(centroids_gdf, mask_gdf, how="left", predicate="within")
        
        # Any hex centroid that matched a mask feature is marked uninhabitable
        masked_hex_ids = set(joined[joined["index_right"].notna()]["hex_id"])
        
        # Override: Keep cells that contain schools, have structural volume, or have real estate listings
        school_hexes = set()
        schools_path = "data/processed/schools_processed.parquet"
        if os.path.exists(schools_path):
            try:
                schools_df = gpd.read_parquet(schools_path)
                school_hexes = set(schools_df.apply(
                    lambda row: h3.latlng_to_cell(row.geometry.y, row.geometry.x, resolution), axis=1
                ))
            except Exception as e:
                logger.log(f"Could not load school hexes for override: {e}", "warning")
                
        volume_hexes = set()
        volume_path = "data/processed/structural_volume_h3_res7.json"
        if os.path.exists(volume_path):
            try:
                import json
                with open(volume_path) as f:
                    structural_volume = json.load(f)
                    volume_hexes = set(k for k, v in structural_volume.items() if v > 0)
            except Exception as e:
                logger.log(f"Could not load volume hexes for override: {e}", "warning")
                
        listing_hexes = set()
        re_path = "data/processed/realestate_processed.parquet"
        if os.path.exists(re_path):
            try:
                re_df = gpd.read_parquet(re_path)
                listing_hexes = set(re_df.apply(
                    lambda row: h3.latlng_to_cell(row.geometry.y, row.geometry.x, resolution), axis=1
                ))
            except Exception as e:
                logger.log(f"Could not load real estate listing hexes for override: {e}", "warning")
                
        # Only mask hexes that have NO schools, NO structural volume, and NO listings
        final_masked_hex_ids = set()
        for hid in masked_hex_ids:
            if hid not in school_hexes and hid not in volume_hexes and hid not in listing_hexes:
                final_masked_hex_ids.add(hid)
                
        grid_gdf["is_habitable"] = grid_gdf["hex_id"].apply(lambda hid: hid not in final_masked_hex_ids)
        
    total_hexes = len(grid_gdf)
    habitable_count = len(grid_gdf[grid_gdf["is_habitable"]])
    masked_count = total_hexes - habitable_count
    pct = (habitable_count / total_hexes) * 100 if total_hexes > 0 else 0
    
    logger.log(f"Active hexes: {habitable_count}/{total_hexes} ({pct:.1f}% habitable). {masked_count} masked out.")
    
    # Send layers to map
    logger.add_polygons("H3 Grid", gdf_to_geojson_dict(grid_gdf[grid_gdf["is_habitable"] == True]), style={
        "fill_color": "#2C3E50", "fill_opacity": 0.05, "stroke_color": "#34495E", "stroke_width": 0.5
    })
    logger.add_polygons("Masked Hexes", gdf_to_geojson_dict(grid_gdf[grid_gdf["is_habitable"] == False]), style={
        "fill_color": "#E74C3C", "fill_opacity": 0.35, "stroke_color": "#C0392B", "stroke_width": 0.5
    })
    
    # Cache results
    os.makedirs("data/processed", exist_ok=True)
    grid_gdf.to_parquet(cache_path)
    logger.log("Layer 2 H3 Grid and mask cached to data/processed/", "success")
    
    logger.layer_end(2, f"{habitable_count} habitable hexes generated")
    return grid_gdf
