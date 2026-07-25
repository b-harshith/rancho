#!/usr/bin/env python3
import json
import os
import asyncio
import aiohttp
import urllib.parse

INPUT_FILE = "data/raw/bangalore_projects.jsonl"
OUTPUT_FILE = "data/raw/bangalore_projects_geocoded.jsonl"
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
CONCURRENCY_LIMIT = 50  # Number of concurrent HTTP requests (QPS)

async def geocode_address(session, address):
    if not API_KEY:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY before running this scraper.")
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={API_KEY}"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("status") == "OK" and data.get("results"):
                    loc = data["results"][0]["geometry"]["location"]
                    return loc["lat"], loc["lng"]
                elif data.get("status") == "OVER_QUERY_LIMIT":
                    print("Warning: Google API Over Query Limit. Sleep required.")
                    return "OVER_LIMIT", None
            return None, None
    except Exception as e:
        return None, None

async def worker(queue, session, write_queue):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        
        idx, card = item
        name = card.get("psmName") or card.get("devName") or ""
        sublocality = card.get("lmtDName") or ""
        
        # Build address query
        query_parts = []
        if name:
            query_parts.append(name)
        if sublocality:
            query_parts.append(sublocality)
        query_parts.extend(["Bangalore", "Karnataka", "India"])
        address = ", ".join(query_parts)
        
        # Check if already geocoded in raw card
        if "latitude" in card and "longitude" in card and card["latitude"] is not None:
            await write_queue.put((idx, card))
            queue.task_done()
            continue
            
        lat, lon = await geocode_address(session, address)
        
        if lat == "OVER_LIMIT":
            # Re-enqueue item and wait
            await asyncio.sleep(2)
            await queue.put((idx, card))
            queue.task_done()
            continue
            
        card["latitude"] = lat
        card["longitude"] = lon
        
        await write_queue.put((idx, card))
        queue.task_done()

async def writer(write_queue, total_lines):
    # Load all processed so we can rewrite or we can just keep output order
    # To keep exact matching order of jsonl lines, we can collect results and write.
    # But since we want to see it written live, we'll write them as they finish.
    processed_count = 0
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        while True:
            item = await write_queue.get()
            if item is None:
                write_queue.task_done()
                break
            idx, card = item
            f.write(json.dumps(card, ensure_ascii=False) + "\n")
            f.flush()
            processed_count += 1
            if processed_count % 100 == 0 or processed_count == total_lines:
                print(f"Geocoded and saved: {processed_count}/{total_lines} projects...")
            write_queue.task_done()

async def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} does not exist.")
        return

    # Read all lines
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
    print(f"Loaded {total_lines} projects to geocode.")

    queue = asyncio.Queue()
    write_queue = asyncio.Queue()

    # Enqueue work
    for idx, card in enumerate(cards):
        await queue.put((idx, card))

    # Add termination sentinels for workers
    for _ in range(CONCURRENCY_LIMIT):
        await queue.put(None)

    async with aiohttp.ClientSession() as session:
        # Start workers
        workers = []
        for _ in range(CONCURRENCY_LIMIT):
            workers.append(asyncio.create_task(worker(queue, session, write_queue)))

        # Start writer
        writer_task = asyncio.create_task(writer(write_queue, total_lines))

        # Wait for workers to finish
        await asyncio.gather(*workers)
        
        # Signal writer to finish
        await write_queue.put(None)
        await writer_task

    print(f"Geocoding complete! Geocoded dataset saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
