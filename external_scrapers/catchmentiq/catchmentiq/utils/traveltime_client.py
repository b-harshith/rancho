import requests
import time
import json
from shapely.geometry import shape, Polygon, MultiPolygon

def get_traveltime_isochrones(
    searches: list, 
    app_id: str, 
    api_key: str, 
    logger
) -> dict:
    """
    Query TravelTime API /v4/time-map for multiple searches.
    
    Arguments:
        searches: A list of dicts:
            [
                {
                    "id": "school_name__10",
                    "lat": float,
                    "lon": float,
                    "travel_time_seconds": int,
                    "transportation_type": str,
                    "arrival_time": str
                },
                ...
            ]
        app_id: TravelTime application ID
        api_key: TravelTime API key
        logger: Logger instance to print messages
        
    Returns:
        A dictionary mapping search_id -> shapely geometry (Polygon or MultiPolygon)
    """
    url = "https://api.traveltimeapp.com/v4/time-map"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/geo+json",
        "X-Application-Id": app_id,
        "X-Api-Key": api_key
    }
    
    results = {}
    
    # TravelTime standard limit: max 10 searches per request
    batch_size = 10
    batches = [searches[i:i + batch_size] for i in range(0, len(searches), batch_size)]
    
    for batch_idx, batch in enumerate(batches):
        arrival_searches = []
        for s in batch:
            arrival_searches.append({
                "id": s["id"],
                "coords": {
                    "lat": s["lat"],
                    "lng": s["lon"]
                },
                "arrival_time": s["arrival_time"],
                "travel_time": s["travel_time_seconds"],
                "transportation": {
                    "type": s["transportation_type"]
                }
            })
            
        payload = {
            "arrival_searches": arrival_searches
        }
        
        # Make post request with retries for 429
        max_retries = 5
        backoff_sec = 2.0
        success = False
        
        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=15.0)
                if response.status_code == 200:
                    geojson_res = response.json()
                    # Parse GeoJSON features into shapely shapes
                    for feature in geojson_res.get("features", []):
                        search_id = feature.get("properties", {}).get("search_id")
                        geom_dict = feature.get("geometry")
                        if search_id and geom_dict:
                            results[search_id] = shape(geom_dict)
                    success = True
                    break
                elif response.status_code == 429:
                    logger.log(f"TravelTime API Rate limit (429) hit on batch {batch_idx+1}/{len(batches)}. Retrying in {backoff_sec}s...", "warning")
                    time.sleep(backoff_sec)
                    backoff_sec *= 2.0
                else:
                    logger.log(f"TravelTime API returned status code {response.status_code}: {response.text}", "warning")
                    break
            except Exception as e:
                logger.log(f"Network error on TravelTime batch {batch_idx+1}: {e}. Retrying...", "warning")
                time.sleep(2.0)
                
        if not success:
            logger.log(f"Failed to process TravelTime batch {batch_idx+1}/{len(batches)} after retries.", "warning")
            
        # Standard API rate limit window spacing to be polite
        time.sleep(0.5)
        
    return results
