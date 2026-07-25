import requests
import time
from shapely.geometry import shape, Polygon, MultiPolygon

def get_ors_isochrones(lat: float, lon: float, bands_minutes: list, api_key: str, logger, profile: str = "driving-car") -> dict:
    """
    Fetch isochrones from OpenRouteService for a single location.
    ORS can return multiple rings in a single request.
    """
    url = f"https://api.openrouteservice.org/v2/isochrones/{profile}"
    
    headers = {
        "Accept": "application/json, application/geo+json, application/gpx+xml, img/png; charset=utf-8",
        "Authorization": api_key,
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # ORS expects range in seconds when range_type is "time"
    ranges = [m * 60 for m in bands_minutes]
    
    payload = {
        "locations": [[lon, lat]],
        "range": ranges,
        "range_type": "time"
    }
    
    max_retries = 5
    backoff_sec = 2.0
    results = {}
    
    for attempt in range(max_retries):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15.0)
            if res.status_code == 200:
                data = res.json()
                for feature in data.get("features", []):
                    val = feature.get("properties", {}).get("value")
                    if val is not None:
                        minutes = int(val / 60)
                        geom = shape(feature["geometry"])
                        results[minutes] = geom
                return results
            elif res.status_code == 429:
                logger.log(f"ORS API Rate limit (429) hit. Retrying in {backoff_sec}s...", "warning")
                time.sleep(backoff_sec)
                backoff_sec *= 2.0
            else:
                logger.log(f"ORS API error {res.status_code}: {res.text}", "warning")
                break
        except Exception as e:
            logger.log(f"Network error on ORS request: {e}. Retrying...", "warning")
            time.sleep(2.0)
            
    return results
