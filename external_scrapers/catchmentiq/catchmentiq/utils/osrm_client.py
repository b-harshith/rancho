import requests
import time
from shapely.geometry import Polygon, Point
import geopandas as gpd

def get_isochrone(lat: float, lon: float, time_minutes: int,
                  osrm_url: str = "http://localhost:5000", profile: str = "car") -> Polygon:
    """
    Compute a single isochrone polygon using OSRM's table service or
    falls back to generating a metric distance buffer representing peak-hour traffic (~20 km/h).
    """
    # 1. Attempt to query OSRM table service to estimate road network accessibility
    # A standard way to get OSRM isochrones is via the /table service to sample points
    # or using a concave hull of reachable points.
    # However, if OSRM is not running or fails, we fall back to a metric buffer.
    
    use_fallback = True
    
    if osrm_url:
        try:
            # We sample a ring of points around the center to check their travel times.
            # Let's check 32 angles at estimated maximum radius (say 12km for 30 min at 24km/h)
            # and request table travel times from center to those 32 points.
            # Then filter points that are <= time_minutes and compute concave hull.
            
            # Since local OSRM is not running in this environment, this block will fail
            # and fall back to the geometric method.
            # We will try a simple request first to see if OSRM is active:
            r = requests.get(f"{osrm_url}/route/v1/{profile}/{lon},{lat};{lon},{lat}", timeout=1.5)
            if r.status_code == 200:
                use_fallback = False
                # If OSRM is active, let's compute an approximation based on table:
                # We'll sample 24 destination points at different bearings:
                import numpy as np
                bearings = np.linspace(0, 2 * np.pi, 24, endpoint=False)
                # Max search radius: 25 km/h -> ~416 meters per minute
                max_radius_m = 416 * time_minutes
                # Convert max_radius to degrees approx
                max_radius_deg = max_radius_m / 111000.0
                
                coords = [f"{lon},{lat}"]
                dest_points = []
                for b in bearings:
                    dest_lon = lon + max_radius_deg * np.sin(b)
                    dest_lat = lat + max_radius_deg * np.cos(b)
                    coords.append(f"{dest_lon},{dest_lat}")
                    dest_points.append((dest_lon, dest_lat))
                
                coords_str = ";".join(coords)
                table_url = f"{osrm_url}/table/v1/{profile}/{coords_str}?sources=0&annotations=duration"
                tr = requests.get(table_url, timeout=3.0)
                if tr.status_code == 200:
                    data = tr.json()
                    durations = data.get("durations", [[]])[0] # Durations from source (0) to all destinations
                    
                    reachable_points = [(lon, lat)] # Always start with origin
                    for idx, duration in enumerate(durations[1:]): # skip first (source to source)
                        if duration is not None:
                            duration_min = duration / 60.0
                            if duration_min <= time_minutes:
                                reachable_points.append(dest_points[idx])
                            else:
                                # Interpolate point position along the bearing based on duration
                                fraction = time_minutes / duration_min
                                if fraction < 1.0:
                                    int_lon = lon + (dest_points[idx][0] - lon) * fraction
                                    int_lat = lat + (dest_points[idx][1] - lat) * fraction
                                    reachable_points.append((int_lon, int_lat))
                    
                    if len(reachable_points) >= 3:
                        # Construct polygon from points ordered by angle
                        # Compute angle relative to center
                        angles = [np.arctan2(p[1]-lat, p[0]-lon) for p in reachable_points]
                        sorted_points = [p for _, p in sorted(zip(angles, reachable_points))]
                        return Polygon(sorted_points)
        except Exception:
            pass
            
    if use_fallback:
        # Peak traffic driving speed in Bangalore is ~20 km/h (333.3 meters per minute)
        avg_speed_m_per_min = 333.33
        radius_meters = avg_speed_m_per_min * time_minutes
        
        # Create point and project to UTM 43N
        point = Point(lon, lat)
        series = gpd.GeoSeries([point], crs="EPSG:4326")
        series_projected = series.to_crs(epsg=32643) # UTM 43N
        buffer_projected = series_projected.buffer(radius_meters)
        buffer_wgs84 = buffer_projected.to_crs(epsg=4326)
        
        return buffer_wgs84.iloc[0]
