import json
import os
import time
import asyncio
import aiohttp
import urllib.parse
import random

CLASSIFIED_FILE = "data/processed/bangalore_projects_classified.json"
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
CONCURRENCY_LIMIT = 35  # Decreased concurrency to 35 as requested

async def geocode_google(session, name, locality):
    if not API_KEY:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY before running this scraper.")
    query_parts = []
    if name:
        query_parts.append(name)
    if locality:
        query_parts.append(locality)
    query_parts.extend(["Bangalore", "Karnataka", "India"])
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

async def worker(queue, session, progress, lock, file_path, all_projects):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
            
        p = item
        name = p.get("name")
        locality = p.get("locality")
        
        # Introduce a small, staggered delay to smooth out requests and avoid rate limits
        await asyncio.sleep(random.uniform(0.1, 0.2))
        
        google_coords = None
        retries = 5
        backoff = 3.0
        
        while retries > 0:
            res_coords, err = await geocode_google(session, name, locality)
            if res_coords == "RETRY_LIMIT":
                # Staggered exponential backoff on query limit
                sleep_time = backoff + random.uniform(1.0, 2.0)
                print(f"\n[Rate Limit] Google API Query Limit hit for '{name}'. Backing off {sleep_time:.1f}s...")
                await asyncio.sleep(sleep_time)
                retries -= 1
                backoff *= 2.0
                continue
            elif res_coords == "RETRY_ERR":
                retries -= 1
                await asyncio.sleep(1.0)
                continue
            else:
                google_coords = res_coords
                break
                
        # Fallback to locality geocode if the specific name query failed
        if google_coords is None and locality:
            retries = 5
            backoff = 3.0
            while retries > 0:
                res_coords, err = await geocode_google(session, None, locality)
                if res_coords == "RETRY_LIMIT":
                    sleep_time = backoff + random.uniform(1.0, 2.0)
                    await asyncio.sleep(sleep_time)
                    retries -= 1
                    backoff *= 2.0
                    continue
                elif res_coords == "RETRY_ERR":
                    retries -= 1
                    await asyncio.sleep(1.0)
                    continue
                else:
                    google_coords = res_coords
                    break
        
        if google_coords:
            p["lat"], p["lon"] = google_coords
            progress["success"] += 1
        else:
            progress["failed"] += 1
            
        progress["done"] += 1
        
        # Print progress summary every 50 projects
        if progress["done"] % 50 == 0 or progress["done"] == progress["total"]:
            print(f"Progress: {progress['done']}/{progress['total']} ({progress['done']/progress['total']*100:.1f}%) | "
                  f"Success: {progress['success']} | Failed: {progress['failed']}")
                  
        # Periodically save progress to file (every 200 records) to prevent data loss
        if progress["done"] % 200 == 0:
            async with lock:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(all_projects, f, indent=2, ensure_ascii=False)
                    
        queue.task_done()

async def main():
    if not os.path.exists(CLASSIFIED_FILE):
        print(f"Error: {CLASSIFIED_FILE} does not exist.")
        return

    with open(CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)

    total_projects = len(projects)
    print(f"Loaded {total_projects} projects to geocode through Google API.")

    queue = asyncio.Queue()
    for p in projects:
        await queue.put(p)
        
    for _ in range(CONCURRENCY_LIMIT):
        await queue.put(None)

    progress = {"done": 0, "total": total_projects, "success": 0, "failed": 0}
    lock = asyncio.Lock()
    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        workers = []
        for _ in range(CONCURRENCY_LIMIT):
            workers.append(asyncio.create_task(worker(queue, session, progress, lock, CLASSIFIED_FILE, projects)))
            
        await asyncio.gather(*workers)

    # Final save
    with open(CLASSIFIED_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start_time
    print(f"\nCompleted! Geocoded {progress['success']}/{total_projects} projects successfully in {elapsed:.1f}s.")
    print(f"Updated dataset saved back to {CLASSIFIED_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
