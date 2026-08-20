from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from flask import Flask, jsonify

# 1. First restore state from Hugging Face Parquet dataset
print("=== RENDER STARTUP: Restoring progress from Hugging Face Parquet ===")
try:
    from restore_from_parquet import restore
    restore()
except Exception as e:
    print(f"Warning: Could not restore state from Parquet: {e}")

# 2. Initialize Flask Healthcheck App for Render
app = Flask(__name__)

@app.route("/")
def healthcheck():
    return jsonify({
        "status": "healthy",
        "service": "udise-scraper-render",
        "timestamp": time.time()
    }), 200

@app.route("/status")
def status_endpoint():
    try:
        from app import database
        return jsonify(database.status()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_scraper_thread():
    print("=== STARTING BACKGROUND SCRAPER LOOP ===")
    try:
        from run_cli_batch import main as batch_main
        batch_main()
    except Exception as e:
        print(f"Background scraper thread error: {e}")

if __name__ == "__main__":
    # Start scraper in background thread
    scraper_thread = threading.Thread(target=run_scraper_thread, daemon=True)
    scraper_thread.start()
    
    # Run HTTP server for Render health checks
    port = int(os.environ.get("PORT", "10000"))
    print(f"Starting Render health check server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
