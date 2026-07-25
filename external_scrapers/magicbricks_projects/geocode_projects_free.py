#!/usr/bin/env python3
import json
import os
import time
import asyncio
import aiohttp
import urllib.parse

INPUT_FILE = "data/raw/bangalore_projects.jsonl"
OUTPUT_FILE = "data/raw/bangalore_projects_geocoded_free.jsonl"
ARCGIS_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
CONCURRENCY_LIMIT = 20  # Safe concurrency limit to prevent rate limits/timeouts

async def geocode_arcgis(session, query):
    params = {
        "SingleLine": query,
        "f": "json",
        "maxLocations": 1
    }
    url = f"{ARCGIS_URL}?{urllib.parse.urlencode(params)}"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    loc = candidates[0]["location"]
                    return loc["y"], loc["x"]  # lat, lon
                return None, None
            elif response.status == 429 or response.status >= 500:
                return "RETRY", f"HTTP {response.status}"
            return None, None
    except Exception as e:
        return "RETRY", str(e)

async def worker(queue, session, write_queue, existing_coords):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        
        idx, card = item
        psmid = card.get("psmid")
        name = card.get("psmName") or card.get("devName") or ""
        sublocality = card.get("lmtDName") or ""
        
        # 1. Check if already has coordinates from previous runs (in existing_coords mapping)
        if psmid and psmid in existing_coords:
            card["latitude"], card["longitude"] = existing_coords[psmid]
            await write_queue.put((idx, card, True))
            queue.task_done()
            continue
            
        # 2. Check if already has coordinates in the raw record
        if "latitude" in card and "longitude" in card and card["latitude"] is not None:
            await write_queue.put((idx, card, True))
            queue.task_done()
            continue
            
        # Try exact project name + sublocality with retries on network error
        query = f"{name}, {sublocality}, Bangalore, India" if sublocality else f"{name}, Bangalore, India"
        
        lat, lon = None, None
        retries = 3
        while retries > 0:
            res_lat, res_lon = await geocode_arcgis(session, query)
            if res_lat == "RETRY":
                retries -= 1
                await asyncio.sleep(1.5 * (3 - retries))
                continue
            else:
                lat, lon = res_lat, res_lon
                break
            
        # Fallback to sublocality only if project query failed (with retries on network error)
        if lat is None and lon is None and sublocality:
            fallback_query = f"{sublocality}, Bangalore, India"
            retries = 3
            while retries > 0:
                res_lat, res_lon = await geocode_arcgis(session, fallback_query)
                if res_lat == "RETRY":
                    retries -= 1
                    await asyncio.sleep(1.5 * (3 - retries))
                    continue
                else:
                    lat, lon = res_lat, res_lon
                    break
                
        card["latitude"] = lat
        card["longitude"] = lon
        
        await write_queue.put((idx, card, False))
        queue.task_done()

async def writer(write_queue, total_lines):
    processed_count = 0
    cached_count = 0
    new_geocoded_count = 0
    start_time = time.time()
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        while True:
            item = await write_queue.get()
            if item is None:
                write_queue.task_done()
                break
            idx, card, was_cached = item
            f.write(json.dumps(card, ensure_ascii=False) + "\n")
            f.flush()
            
            processed_count += 1
            if was_cached:
                cached_count += 1
            else:
                new_geocoded_count += 1
                lat = card.get("latitude")
                lon = card.get("longitude")
                name = card.get("psmName") or card.get("devName") or "Unknown"
                locality = card.get("lmtDName") or "Unknown"
                # Print the new geocoded item to the terminal
                print(f"[Geocoded] '{name}' in {locality} -> ({lat}, {lon})")
                
            elapsed = time.time() - start_time
            # Calculate QPS and ETA based on new requests made to avoid skewed stats from cache loading
            if new_geocoded_count > 0 and elapsed > 0:
                qps = new_geocoded_count / elapsed
                remaining = total_lines - processed_count
                eta_seconds = remaining / qps
            else:
                qps = 0
                eta_seconds = 0
                
            # Format ETA
            eta_h = int(eta_seconds // 3600)
            eta_m = int((eta_seconds % 3600) // 60)
            eta_s = int(eta_seconds % 60)
            
            progress_pct = (processed_count / total_lines) * 100
            print(
                f"\rProgress: {processed_count}/{total_lines} ({progress_pct:.1f}%) | "
                f"New: {new_geocoded_count} | Cached: {cached_count} | QPS: {qps:.1f} | "
                f"Elapsed: {int(elapsed)}s | ETA: {eta_h:02d}:{eta_m:02d}:{eta_s:02d}",
                end="",
                flush=True
            )
            write_queue.task_done()
    print()  # Final newline

async def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} does not exist.")
        return

    # Load existing geocoded records from the output file to support resuming
    existing_coords = {}
    if os.path.exists(OUTPUT_FILE):
        print(f"Reading existing output file '{OUTPUT_FILE}' for resume coordinates...")
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            record = json.loads(line)
                            psmid = record.get("psmid")
                            if psmid and record.get("latitude") is not None:
                                existing_coords[psmid] = (record["latitude"], record["longitude"])
                        except:
                            pass
            print(f"Successfully loaded {len(existing_coords)} coordinates to resume.")
        except Exception as e:
            print(f"Could not load output file for resumption: {e}")

    # Read raw cards
    cards = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    cards.append(json.loads(line))
                except:
                    pass

    total_lines = len(cards)
    print(f"Loaded {total_lines} total projects to process.")

    queue = asyncio.Queue()
    write_queue = asyncio.Queue()

    # Enqueue tasks
    for idx, card in enumerate(cards):
        await queue.put((idx, card))

    # Add sentinels to stop workers
    for _ in range(CONCURRENCY_LIMIT):
        await queue.put(None)

    async with aiohttp.ClientSession() as session:
        workers = []
        for _ in range(CONCURRENCY_LIMIT):
            workers.append(asyncio.create_task(worker(queue, session, write_queue, existing_coords)))

        writer_task = asyncio.create_task(writer(write_queue, total_lines))

        await asyncio.gather(*workers)
        await write_queue.put(None)
        await writer_task

    print(f"Geocoding complete! Geocoded dataset saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main_start = time.time()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\nExecution interrupted by user. Safe checkpoints were saved to {OUTPUT_FILE}.")
