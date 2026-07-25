#!/usr/bin/env python3
"""
Interactive Web Dashboard Server for K12 Bangalore Schools Geocoding & Footprints.
Exposes a lightweight REST API and SSE stream to power a real-time visualization UI.
"""

import os
import sys
import json
import time
import asyncio
import threading
import pandas as pd
from pathlib import Path
from datetime import datetime
from aiohttp import web

# Resolve import paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from scratch.geocode_schools import run_geocoding, GeocodeCache, CACHE_DB_PATH
from scratch.fetch_school_boundaries import run_matching, load_buildings, BUILDINGS_PATH, CSV_PATH

# ── Global Application State ──────────────────────────────────────────────────
loop = None
sse_queues = []
state_lock = threading.Lock()

SYSTEM_STATE = {
    "status": "IDLE",                # IDLE, LOADING_BUILDINGS, GEOCODING, MATCHING
    "current_school": "",
    "processed_count": 0,
    "total_count": 0,
    "success_count": 0,
    "fail_count": 0,
    "cache_hits": 0,
    "api_queries": 0,
    "match_rate": "0.0%",
    "avg_perimeter": "—",
    "elapsed_time": 0,
    "active_provider": "ArcGIS"
}

pipeline_stop_event = threading.Event()
pipeline_thread = None
buildings_cache = []
buildings_loaded = False
start_time = None

# ── Helper functions ──────────────────────────────────────────────────────────
def get_elapsed_str():
    if start_time is None:
        return "0s"
    diff = int(time.time() - start_time)
    if diff < 60:
        return f"{diff}s"
    return f"{diff // 60}m {diff % 60}s"

def broadcast_event(event_type, data):
    """Sends an event payload to all active SSE client connections."""
    if not loop:
        return
    payload = json.dumps({
        "type": event_type,
        "data": data,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })
    for q in sse_queues:
        loop.call_soon_threadsafe(q.put_nowait, payload)

# ── Pipeline Wrappers ─────────────────────────────────────────────────────────
def run_geocode_pipeline_thread(provider):
    global start_time, SYSTEM_STATE
    start_time = time.time()
    pipeline_stop_event.clear()

    try:
        cache = GeocodeCache(CACHE_DB_PATH)
        df = pd.read_csv(CSV_PATH)

        if "Latitude" not in df.columns: df["Latitude"] = None
        if "Longitude" not in df.columns: df["Longitude"] = None

        total = len(df)
        already = int(df["Latitude"].notna().sum())

        with state_lock:
            SYSTEM_STATE.update({
                "status": "GEOCODING",
                "total_count": total,
                "processed_count": already,
                "success_count": already,
                "fail_count": 0,
                "cache_hits": 0,
                "api_queries": 0,
                "active_provider": provider,
                "elapsed_time": "0s"
            })

        broadcast_event("status_update", SYSTEM_STATE)

        def callback(stats, event, current_school):
            with state_lock:
                SYSTEM_STATE.update({
                    "processed_count": stats["processed"],
                    "success_count": stats["success"],
                    "fail_count": stats["fail"],
                    "cache_hits": stats["cache_hit"],
                    "api_queries": stats["api_query"],
                    "current_school": current_school,
                    "elapsed_time": get_elapsed_str()
                })
                # Success rate
                p = stats["processed"]
                SYSTEM_STATE["match_rate"] = f"{stats['success']/p*100:.1f}%" if p > 0 else "0.0%"

            broadcast_event("status_update", SYSTEM_STATE)
            if event:
                broadcast_event("log", event)

        run_geocoding(df, cache, callback=callback, stop_event=pipeline_stop_event, provider_override=provider)
        cache.close()

    except Exception as e:
        broadcast_event("log", {"time": datetime.now().strftime("%H:%M:%S"), "code": "ERR", "name": "Geocoding", "status": "FAIL", "details": str(e)})
    finally:
        with state_lock:
            SYSTEM_STATE["status"] = "IDLE"
            SYSTEM_STATE["current_school"] = "Done"
        broadcast_event("status_update", SYSTEM_STATE)


def run_matching_pipeline_thread():
    global start_time, buildings_cache, buildings_loaded, SYSTEM_STATE
    start_time = time.time()
    pipeline_stop_event.clear()

    # Step 1: Check/Load Overture building footprint data
    if not buildings_loaded:
        with state_lock:
            SYSTEM_STATE["status"] = "LOADING_BUILDINGS"
            SYSTEM_STATE["current_school"] = "Loading 1.88M building footprints..."
        broadcast_event("status_update", SYSTEM_STATE)
        
        t0 = time.time()
        try:
            buildings_cache = load_buildings(BUILDINGS_PATH)
            buildings_loaded = True
            broadcast_event("log", {
                "time": datetime.now().strftime("%H:%M:%S"), 
                "code": "SYS", 
                "name": "Overture Loader", 
                "status": "SUCCESS", 
                "details": f"Loaded {len(buildings_cache):,} polygons in {time.time() - t0:.1f}s"
            })
        except Exception as e:
            broadcast_event("log", {
                "time": datetime.now().strftime("%H:%M:%S"), 
                "code": "ERR", 
                "name": "Overture Loader", 
                "status": "FAIL", 
                "details": str(e)
            })
            with state_lock:
                SYSTEM_STATE["status"] = "IDLE"
            broadcast_event("status_update", SYSTEM_STATE)
            return

    # Step 2: Run Matching
    try:
        df = pd.read_csv(CSV_PATH)
        if "Latitude" not in df.columns or "Longitude" not in df.columns:
            broadcast_event("log", {
                "time": datetime.now().strftime("%H:%M:%S"), 
                "code": "ERR", 
                "name": "Matcher", 
                "status": "FAIL", 
                "details": "No Latitude/Longitude in CSV. Run geocoding first."
            })
            with state_lock:
                SYSTEM_STATE["status"] = "IDLE"
            broadcast_event("status_update", SYSTEM_STATE)
            return

        valid = df[df["Latitude"].notna() & df["Longitude"].notna()]
        total = len(valid)
        already = int(df["Boundary_Polygon"].notna().sum())

        with state_lock:
            SYSTEM_STATE.update({
                "status": "MATCHING",
                "total_count": total,
                "processed_count": already,
                "success_count": already,
                "fail_count": 0,
                "elapsed_time": "0s"
            })
        broadcast_event("status_update", SYSTEM_STATE)

        def callback(stats, event, current_school):
            with state_lock:
                SYSTEM_STATE.update({
                    "processed_count": stats["processed"],
                    "success_count": stats["found"],
                    "fail_count": stats["not_found"],
                    "current_school": current_school,
                    "elapsed_time": get_elapsed_str()
                })
                # Match rate
                p = stats["processed"]
                SYSTEM_STATE["match_rate"] = f"{stats['found']/p*100:.1f}%" if p > 0 else "0.0%"
                SYSTEM_STATE["avg_perimeter"] = f"{stats['total_perim']/stats['found']:.1f}m" if stats["found"] > 0 else "—"

            broadcast_event("status_update", SYSTEM_STATE)
            if event:
                # Add extra info for map plotting if found
                if event.get("status") == "FOUND" and current_school:
                    # Parse school code to find row and retrieve polygon coords
                    school_code = event["code"]
                    row = df[df["School_Code"] == school_code]
                    if not row.empty:
                        poly_str = row.iloc[0].get("Boundary_Polygon")
                        if poly_str and pd.notna(poly_str):
                            event["polygon"] = json.loads(poly_str)
                            event["latitude"] = float(row.iloc[0]["Latitude"])
                            event["longitude"] = float(row.iloc[0]["Longitude"])
                broadcast_event("log", event)

        run_matching(df, buildings_cache, callback=callback, stop_event=pipeline_stop_event)

    except Exception as e:
        broadcast_event("log", {
            "time": datetime.now().strftime("%H:%M:%S"), 
            "code": "ERR", 
            "name": "Matching", 
            "status": "FAIL", 
            "details": str(e)
        })
    finally:
        with state_lock:
            SYSTEM_STATE["status"] = "IDLE"
            SYSTEM_STATE["current_school"] = "Done"
        broadcast_event("status_update", SYSTEM_STATE)

# ── API Handlers ──────────────────────────────────────────────────────────────
async def handle_index(request):
    """Serves the main dashboard page."""
    html_path = PROJECT_ROOT / "scratch" / "templates" / "index.html"
    if not html_path.exists():
        return web.Response(text="Dashboard HTML template not found. Build index.html first.", status=404)
    return web.FileResponse(html_path)

async def handle_status(request):
    """Returns current geocoding or matching stats."""
    return web.json_response(SYSTEM_STATE)

async def handle_schools(request):
    """Returns full school list for table and map, with minimal coordinates data to save bandwidth."""
    if not CSV_PATH.exists():
        return web.json_response([], status=404)
    
    df = pd.read_csv(CSV_PATH)
    schools = []
    
    for _, row in df.iterrows():
        lat = row.get("Latitude")
        lon = row.get("Longitude")
        poly = row.get("Boundary_Polygon")
        
        schools.append({
            "code": str(row["School_Code"]),
            "name": str(row["Name"]),
            "board": str(row.get("Board", "Unknown")),
            "address": str(row.get("Address", "")),
            "lat": float(lat) if pd.notna(lat) else None,
            "lon": float(lon) if pd.notna(lon) else None,
            "has_polygon": pd.notna(poly) and isinstance(poly, str) and len(poly) > 10,
            "polygon": json.loads(poly) if pd.notna(poly) and isinstance(poly, str) and len(poly) > 10 else None,
            "perimeter": float(row.get("Perimeter_Meters")) if pd.notna(row.get("Perimeter_Meters")) else None
        })
    return web.json_response(schools)

async def handle_start(request):
    """Starts the geocoding or matching thread."""
    global pipeline_thread
    data = await request.json()
    task_type = data.get("task")
    provider = data.get("provider", "ArcGIS")

    with state_lock:
        if SYSTEM_STATE["status"] in ["GEOCODING", "MATCHING", "LOADING_BUILDINGS"]:
            return web.json_response({"error": "A pipeline task is already running."}, status=400)
    
    if task_type == "geocode":
        pipeline_thread = threading.Thread(target=run_geocode_pipeline_thread, args=(provider,), daemon=True)
        pipeline_thread.start()
        return web.json_response({"status": "SUCCESS", "message": "Geocoding process started."})
        
    elif task_type == "match":
        pipeline_thread = threading.Thread(target=run_matching_pipeline_thread, daemon=True)
        pipeline_thread.start()
        return web.json_response({"status": "SUCCESS", "message": "Footprint matching process started."})

    return web.json_response({"error": "Invalid task type specified."}, status=400)

async def handle_stop(request):
    """Requests the active pipeline to pause/stop."""
    pipeline_stop_event.set()
    return web.json_response({"status": "SUCCESS", "message": "Stop request sent."})

async def handle_stream(request):
    """Server-Sent Events (SSE) stream client."""
    response = web.StreamResponse()
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Access-Control-Allow-Origin'] = '*'
    await response.prepare(request)

    q = asyncio.Queue()
    sse_queues.append(q)
    
    # Send current system status snapshot immediately
    initial_payload = json.dumps({"type": "status_update", "data": SYSTEM_STATE, "timestamp": datetime.now().strftime("%H:%M:%S")})
    await response.write(f"data: {initial_payload}\n\n".encode('utf-8'))

    try:
        while True:
            payload = await q.get()
            try:
                await response.write(f"data: {payload}\n\n".encode('utf-8'))
            except Exception:
                # Catch any write failures (disconnects, connection resets) gracefully
                break
            q.task_done()
    except asyncio.CancelledError:
        pass
    finally:
        if q in sse_queues:
            sse_queues.remove(q)
    return response

# ── Server Setup ──────────────────────────────────────────────────────────────
async def start_server():
    global loop
    loop = asyncio.get_running_loop()
    
    app = web.Application()
    
    # Router mapping
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/status', handle_status)
    app.router.add_get('/api/schools', handle_schools)
    app.router.add_post('/api/start', handle_start)
    app.router.add_post('/api/stop', handle_stop)
    app.router.add_get('/api/stream', handle_stream)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    
    print("\n" + "="*80)
    print(" 🚀 K12 BANGALORE SCHOOLS GEOPROCESSING MISSION CONTROL DASHBOARD ")
    print("="*80)
    print(" * Local Web Server launched successfully!")
    print(" * Open in browser: http://localhost:8080")
    print("="*80 + "\n", flush=True)
    
    await site.start()
    
    # Keep server running infinitely
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping Web Dashboard Server...", flush=True)
