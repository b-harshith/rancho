import geopandas as gpd
from shapely.geometry import Point, mapping
import json

def is_within_bbox(lat: float, lon: float, bbox: dict) -> bool:
    """Check if lat/lon point falls inside the city bounding box."""
    if bbox is None:
        return True
    return (bbox["min_lat"] <= lat <= bbox["max_lat"]) and (bbox["min_lon"] <= lon <= bbox["max_lon"])

def gdf_to_geojson_dict(gdf: gpd.GeoDataFrame, simplify_tolerance: float = None) -> dict:
    """Convert GeoDataFrame to GeoJSON dict, optionally simplifying geometries to reduce payload size."""
    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}
    
    # Reproject to 4326 if not already
    if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
        
    temp_gdf = gdf.copy()
    if simplify_tolerance:
        # Simplify geometry in metric/degree depending on CRS (here we simplify in degrees if WGS84)
        temp_gdf["geometry"] = temp_gdf["geometry"].simplify(simplify_tolerance, preserve_topology=True)
        
    # Convert to json string then dict
    geojson_str = temp_gdf.to_json()
    return json.loads(geojson_str)

def project_to_utm(gdf: gpd.GeoDataFrame, epsg: int = 32643) -> gpd.GeoDataFrame:
    """Project GeoDataFrame to UTM coordinate reference system for metric distance calculations."""
    return gdf.to_crs(epsg=epsg)

def project_to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Project GeoDataFrame back to WGS84 (EPSG:4326)."""
    return gdf.to_crs(epsg=4326)
