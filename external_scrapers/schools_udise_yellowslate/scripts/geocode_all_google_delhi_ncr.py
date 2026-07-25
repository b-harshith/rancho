import json
import os
import time
import asyncio
import aiohttp
import urllib.parse
import random

MASTER_FILE = "data/output/yellowslate_schools_master_delhi_ncr.json"
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
CONCURRENCY_LIMIT = 20

def infer_city_source(url):
    if not url:
        return "delhi"
    try:
        parts = url.rstrip("/").split("/")
        if "school" in parts:
            idx = parts.index("school")
            if idx + 1 < len(parts):
                return parts[idx + 1].lower()
    except Exception:
        pass
    return "delhi"

async def geocode_google(session, name, area, city_source):
    if not API_KEY:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY before running this scraper.")
    query_parts = []
    if name:
        query_parts.append(name)
    if area:
        query_parts.append(area)
        
    city_suffix = "Delhi, India"
    if city_source == "noida":
        city_suffix = "Noida, Uttar Pradesh, India"
    elif city_source in ("gurgaon", "gurugram"):
        city_suffix = "Gurugram, Haryana, India"
    elif city_source == "ghaziabad":
        city_suffix = "Ghaziabad, Uttar Pradesh, India"
    elif city_source == "faridabad":
        city_suffix = "Faridabad, Haryana, India"
        
    query_parts.append(city_suffix)
    address = ", ".join(query_parts)
    
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={API_KEY}"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                status = data.get("status")
                if status == "OK" and data.get("results"):
                    loc = data["results"][0]["geometry"]["location"]
                    return (loc["lat"], loc["lng"]), None
                elif status == "OVER_QUERY_LIMIT":
                    return "RETRY_LIMIT", status
                elif status in ["ZERO_RESULTS", "REQUEST_DENIED", "INVALID_REQUEST", "UNKNOWN_ERROR"]:
                    return None, status
            return None, f"HTTP {response.status}"
    except Exception as e:
        return "RETRY_ERR", str(e)

async def worker(queue, session, progress):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
            
        p = item
        name = p.get("school_name")
        area = p.get("area")
        url = p.get("school_url")
        city_source = infer_city_source(url)
        
        await asyncio.sleep(random.uniform(0.05, 0.1))
        
        google_coords = None
        retries = 3
        backoff = 2.0
        
        while retries > 0:
            res_coords, err = await geocode_google(session, name, area, city_source)
            if res_coords == "RETRY_LIMIT":
                sleep_time = backoff + random.uniform(0.5, 1.5)
                await asyncio.sleep(sleep_time)
                retries -= 1
                backoff *= 2.0
                continue
            elif res_coords == "RETRY_ERR":
                retries -= 1
                await asyncio.sleep(0.5)
                continue
            else:
                google_coords = res_coords
                break
                
        # Fallback query with just area
        if google_coords is None and area:
            retries = 3
            backoff = 2.0
            while retries > 0:
                res_coords, err = await geocode_google(session, None, area, city_source)
                if res_coords == "RETRY_LIMIT":
                    sleep_time = backoff + random.uniform(0.5, 1.5)
                    await asyncio.sleep(sleep_time)
                    retries -= 1
                    backoff *= 2.0
                    continue
                elif res_coords == "RETRY_ERR":
                    retries -= 1
                    await asyncio.sleep(0.5)
                    continue
                else:
                    google_coords = res_coords
                    break
        
        if google_coords:
            p["latitude"], p["longitude"] = google_coords
            progress["success"] += 1
        else:
            progress["failed"] += 1
            
        total_done = progress["success"] + progress["failed"]
        if total_done % 10 == 0:
            print(f"Progress: {total_done} processed. Success: {progress['success']}, Failed: {progress['failed']}")
            
        queue.task_done()

async def main():
    if not os.path.exists(MASTER_FILE):
        print(f"Error: {MASTER_FILE} not found.")
        return

    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        schools = json.load(f)

    target_schools = [s for s in schools if s.get("latitude") is None or s.get("longitude") is None]
    print(f"Found {len(schools)} total schools. {len(target_schools)} need geocoding.")

    if not target_schools:
        print("All schools already have coordinates. Nothing to do.")
        return

    queue = asyncio.Queue()
    for s in target_schools:
        await queue.put(s)

    progress = {"success": 0, "failed": 0}

    async with aiohttp.ClientSession() as session:
        workers = []
        for _ in range(CONCURRENCY_LIMIT):
            workers.append(asyncio.create_task(worker(queue, session, progress)))

        # Add poison pills to stop workers
        for _ in range(CONCURRENCY_LIMIT):
            await queue.put(None)

        await queue.join()
        await asyncio.gather(*workers)

    # Save master file back
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(schools, f, ensure_ascii=False, indent=2)

    print(f"\nGeocoding finished.")
    print(f" - Successfully geocoded: {progress['success']}")
    print(f" - Failed to geocode: {progress['failed']}")
    print(f"Saved updated master to {MASTER_FILE}.")

if __name__ == "__main__":
    asyncio.run(main())
