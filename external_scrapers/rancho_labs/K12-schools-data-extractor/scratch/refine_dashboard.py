#!/usr/bin/env python3
"""
Interactive Web Dashboard Server for K12 Bangalore Schools Stage 2 Campus Polygon Refinement.
Exposes a lightweight REST API and SSE stream to power a real-time spatial visualization UI.
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

from scratch.campus_refiner import run_refinement, CSV_PATH, MERGE_THRESHOLD

# ── Global Application State ──────────────────────────────────────────────────
loop = None
sse_queues = []
state_lock = threading.Lock()

SYSTEM_STATE = {
    "status": "IDLE",                # IDLE, SCANNING, MERGING, COMPLETE
    "current_school": "",
    "processed_count": 0,
    "total_count": 0,
    "refined_count": 0,
    "unchanged_count": 0,
    "candidates_count": 0,
    "merged_count": 0,
    "rejected_count": 0,
    "avg_area_increase": 0.0,
    "current_layer": "",
    "features_scanned": 0,
    "elapsed_time": "0s"
}

pipeline_stop_event = threading.Event()
pipeline_thread = None
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

# ── Pipeline Wrapper ──────────────────────────────────────────────────────────
def run_refinement_pipeline_thread():
    global start_time, SYSTEM_STATE
    start_time = time.time()
    pipeline_stop_event.clear()

    try:
        with state_lock:
            SYSTEM_STATE.update({
                "status": "SCANNING",
                "current_school": "Initializing spatial layers...",
                "processed_count": 0,
                "total_count": 983,
                "refined_count": 0,
                "unchanged_count": 0,
                "candidates_count": 0,
                "merged_count": 0,
                "rejected_count": 0,
                "avg_area_increase": 0.0,
                "current_layer": "building",
                "features_scanned": 0,
                "elapsed_time": "0s"
            })
        broadcast_event("status_update", SYSTEM_STATE)

        broadcast_event("log", {
            "time": datetime.now().strftime("%H:%M:%S"),
            "code": "SYS",
            "name": "Pipeline",
            "status": "INFO",
            "details": "Initializing Campus Refinement Pipeline..."
        })

        def callback(stats, event, current_label):
            with state_lock:
                if stats:
                    SYSTEM_STATE.update({
                        "status": stats.get("phase", "SCANNING"),
                        "total_count": stats.get("total_schools", 0),
                        "processed_count": stats.get("schools_processed", 0),
                        "refined_count": stats.get("schools_refined", 0),
                        "unchanged_count": stats.get("schools_unchanged", 0),
                        "candidates_count": stats.get("total_candidates", 0),
                        "merged_count": stats.get("total_merged", 0),
                        "rejected_count": stats.get("total_rejected", 0),
                        "avg_area_increase": stats.get("avg_area_increase", 0.0),
                        "current_layer": stats.get("current_layer", ""),
                        "features_scanned": stats.get("features_scanned", 0),
                        "elapsed_time": get_elapsed_str()
                    })
                if current_label:
                    SYSTEM_STATE["current_school"] = current_label

            broadcast_event("status_update", SYSTEM_STATE)
            if event:
                broadcast_event("log", event)

        run_refinement(callback=callback, stop_event=pipeline_stop_event)

    except Exception as e:
        broadcast_event("log", {
            "time": datetime.now().strftime("%H:%M:%S"),
            "code": "ERR",
            "name": "Refinement",
            "status": "FAIL",
            "details": str(e)
        })
    finally:
        with state_lock:
            SYSTEM_STATE["status"] = "COMPLETE"
            SYSTEM_STATE["current_school"] = "Done"
        broadcast_event("status_update", SYSTEM_STATE)

# ── API Handlers ──────────────────────────────────────────────────────────────
async def handle_index(request):
    """Serves the main refinement dashboard page."""
    html_path = PROJECT_ROOT / "scratch" / "templates" / "refine.html"
    if not html_path.exists():
        return web.Response(text="Dashboard HTML template not found. Build refine.html first.", status=404)
    return web.FileResponse(html_path)

async def handle_status(request):
    """Returns current refinement stats."""
    return web.json_response(SYSTEM_STATE)

async def handle_schools(request):
    """Returns school list with geographic shapes (original & refined) and boards."""
    if not CSV_PATH.exists():
        return web.json_response([], status=404)
    
    df = pd.read_csv(CSV_PATH)
    schools = []
    
    for _, row in df.iterrows():
        lat = row.get("Latitude")
        lon = row.get("Longitude")
        poly = row.get("Boundary_Polygon")
        orig_perim = row.get("Original_Perimeter")
        new_perim = row.get("Perimeter_Meters")
        refined = row.get("Refined_Stage2")
        cands_count = row.get("Candidates_Merged")
        area_pct = row.get("Area_Increase_Pct")

        has_poly = pd.notna(poly) and isinstance(poly, str) and len(poly) > 10
        schools.append({
            "code": str(row["School_Code"]),
            "name": str(row["Name"]),
            "board": str(row.get("Board", "Unknown")),
            "address": str(row.get("Address", "")),
            "lat": float(lat) if pd.notna(lat) else None,
            "lon": float(lon) if pd.notna(lon) else None,
            "has_polygon": has_poly,
            "polygon": json.loads(poly) if has_poly else None,
            "perimeter": float(new_perim) if pd.notna(new_perim) else None,
            "original_perimeter": float(orig_perim) if pd.notna(orig_perim) else None,
            "refined": bool(refined) if pd.notna(refined) else False,
            "candidates_count": int(cands_count) if pd.notna(cands_count) else 0,
            "area_increase_pct": float(area_pct) if pd.notna(area_pct) else 0.0
        })
    return web.json_response(schools)

async def handle_start(request):
    """Starts the refinement thread."""
    global pipeline_thread
    with state_lock:
        if SYSTEM_STATE["status"] in ["SCANNING", "MERGING"]:
            return web.json_response({"error": "A refinement task is already running."}, status=400)
    
    pipeline_thread = threading.Thread(target=run_refinement_pipeline_thread, daemon=True)
    pipeline_thread.start()
    return web.json_response({"status": "SUCCESS", "message": "Campus refinement process started."})

async def handle_stop(request):
    """Requests the active pipeline to pause/stop."""
    pipeline_stop_event.set()
    return web.json_response({"status": "SUCCESS", "message": "Stop request sent."})

async def handle_reset(request):
    """Resets Stage 2 column fields in the database CSV so that campus refinement can be re-run."""
    with state_lock:
        if SYSTEM_STATE["status"] in ["SCANNING", "MERGING"]:
            return web.json_response({"error": "Cannot reset database while pipeline is running."}, status=400)
    
    try:
        df = pd.read_csv(CSV_PATH)
        reset_cols = ["Refined_Stage2", "Candidates_Merged", "Area_Increase_Pct", "Original_Perimeter"]
        for col in reset_cols:
            if col in df.columns:
                df[col] = None
        
        # Reset back Boundary_Polygon to their original shape if needed, but wait:
        # Original_Perimeter was stored. If we reset, do we keep the current footprints?
        # Let's keep them and let the search run over them again, or restore perimeter.
        df.to_csv(CSV_PATH, index=False)
        
        broadcast_event("log", {
            "time": datetime.now().strftime("%H:%M:%S"),
            "code": "SYS",
            "name": "Database",
            "status": "SUCCESS",
            "details": "Successfully reset all Stage 2 refinement attributes in school CSV."
        })
        return web.json_response({"status": "SUCCESS", "message": "Database attributes reset."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

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
    app.router.add_post('/api/reset', handle_reset)
    app.router.add_get('/api/stream', handle_stream)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8081)
    
    print("\n" + "="*80)
    print(" 🛡️ STAGE 2 — K12 BANGALORE CAMPUS BOUNDARY REFINEMENT MISSION CONTROL ")
    print("="*80)
    print(" * Local Refinement Server launched successfully!")
    print(" * Open in browser: http://localhost:8081")
    print("="*80 + "\n", flush=True)
    
    await site.start()
    
    # Keep server running infinitely
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping Web Refinement Server...", flush=True)
