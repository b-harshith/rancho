from __future__ import annotations

import os
import shutil
import sqlite3
import time
import threading
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download

# Get Hugging Face Configuration from environment variables
HF_TOKEN = os.environ.get("HF_TOKEN")
HF_REPO = os.environ.get("HF_REPO")  # Format: "username/dataset-name"

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("UDISE_DB", ROOT / "data/runtime/udise_data.sqlite3"))
BACKUP_PATH = DB_PATH.parent / "udise_data_backup.sqlite3"

def download_db() -> None:
    if not HF_TOKEN or not HF_REPO:
        print("HF_TOKEN or HF_REPO not set. Skipping initial database download.")
        return
    print(f"Downloading database from Hugging Face Dataset: {HF_REPO}...")
    try:
        # Download database to a temporary location first to avoid locking
        downloaded_file = hf_hub_download(
            repo_id=HF_REPO,
            filename="udise_data.sqlite3",
            repo_type="dataset",
            token=HF_TOKEN
        )
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(downloaded_file, DB_PATH)
        print("Database downloaded and restored successfully.")
    except Exception as e:
        print(f"Failed to download database or no database exists yet: {e}. Starting fresh.")

def backup_db_loop() -> None:
    if not HF_TOKEN or not HF_REPO:
        print("HF_TOKEN or HF_REPO not set. Database backup daemon disabled.")
        return
    
    api = HfApi(token=HF_TOKEN)
    print("Starting background database backup daemon (5-minute interval)...")
    
    while True:
        time.sleep(300)  # Sync every 5 minutes
        if DB_PATH.exists():
            try:
                print("Creating transaction-safe SQLite hot backup...")
                # Open connections and run online backup to prevent database corruption
                src = sqlite3.connect(DB_PATH)
                dest = sqlite3.connect(BACKUP_PATH)
                with dest:
                    src.backup(dest)
                src.close()
                dest.close()
                
                print("Uploading database backup to Hugging Face Dataset...")
                api.upload_file(
                    path_or_fileobj=str(BACKUP_PATH),
                    path_in_repo="udise_data.sqlite3",
                    repo_id=HF_REPO,
                    repo_type="dataset",
                )
                print("Database backup uploaded successfully.")
            except Exception as e:
                print(f"Error during database backup/upload: {e}")

# Run initial download before Flask app imports to ensure database state is restored
download_db()

# Now import the Flask application instance
from app import app

if __name__ == "__main__":
    # Start the background backup daemon thread
    backup_thread = threading.Thread(target=backup_db_loop, daemon=True)
    backup_thread.start()
    
    # Run the Flask app on 0.0.0.0 to expose it inside the container
    port = int(os.environ.get("PORT", "7860"))
    print(f"Starting UDISE+ web scraper on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
