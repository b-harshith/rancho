from __future__ import annotations

import os
import time
import sqlite3
from pathlib import Path
from huggingface_hub import HfApi

from app import database, collector, load_pincodes, DB_PATH
from app_hf import HF_TOKEN, HF_REPO, BACKUP_PATH

def main() -> None:
    print("Initializing CLI headless scraping batch...")
    
    # Check if there is an active job already in progress
    status = database.status()
    job = status.get("job")
    
    if job and job["status"] in ["running", "starting", "queued", "waiting_captcha"]:
        job_id = int(job["id"])
        print(f"Resuming existing scraping job {job_id}...")
        collector.start(job_id)
    else:
        print("Starting a new scraping job...")
        pincodes = load_pincodes()
        job_id = database.create_job(pincodes)
        print(f"Created job {job_id} with {len(pincodes)} PIN codes.")
        collector.start(job_id)
    
    # Monitor execution and perform backups to Hugging Face
    start_time = time.monotonic()
    last_backup = time.monotonic()
    api = HfApi(token=HF_TOKEN) if HF_TOKEN else None

    if not api or not HF_REPO:
        print("Warning: HF_TOKEN or HF_REPO not set. Backups are disabled.")
    
    print(f"Scraper is active. Monitoring job {job_id}...")
    
    try:
        while True:
            time.sleep(10)
            
            # Check if collector pool is still running
            if not collector.running:
                print("All scheduled PIN tasks completed or pool stopped.")
                break
                
            # Stop cleanly before the 6-hour GitHub Actions job timeout (limit to 5 hours)
            elapsed = time.monotonic() - start_time
            if elapsed > 18000:  # 5 hours
                print("5-hour time limit reached. Gracefully stopping the collector pool...")
                collector.stop()
                while collector.running:
                    time.sleep(2)
                break
                
            # Trigger backup upload to Hugging Face every 5 minutes
            if time.monotonic() - last_backup > 300:
                last_backup = time.monotonic()
                if DB_PATH.exists() and api and HF_REPO:
                    try:
                        print("Creating safe SQLite hot backup...")
                        src = sqlite3.connect(DB_PATH)
                        dest = sqlite3.connect(BACKUP_PATH)
                        with dest:
                            src.backup(dest)
                        src.close()
                        dest.close()
                        
                        print("Uploading database to Hugging Face Dataset...")
                        api.upload_file(
                            path_or_fileobj=str(BACKUP_PATH),
                            path_in_repo="udise_data.sqlite3",
                            repo_id=HF_REPO,
                            repo_type="dataset",
                        )
                        print("Backup uploaded successfully.")
                        try:
                            from export_to_parquet import export_all
                            export_all()
                        except Exception as pe:
                            print(f"Parquet export failed: {pe}")
                    except Exception as e:
                        print(f"Backup upload failed: {e}")
                        
    except KeyboardInterrupt:
        print("Manual interrupt received. Stopping collector...")
        collector.stop()
        
    # Final backup database upload
    if DB_PATH.exists() and api and HF_REPO:
        try:
            print("Performing final database upload...")
            src = sqlite3.connect(DB_PATH)
            dest = sqlite3.connect(BACKUP_PATH)
            with dest:
                src.backup(dest)
            src.close()
            dest.close()
            
            api.upload_file(
                path_or_fileobj=str(BACKUP_PATH),
                path_in_repo="udise_data.sqlite3",
                repo_id=HF_REPO,
                repo_type="dataset",
            )
            print("Final database upload complete.")
            try:
                from export_to_parquet import export_all
                export_all()
            except Exception as pe:
                print(f"Final Parquet export failed: {pe}")
        except Exception as e:
            print(f"Final upload failed: {e}")

if __name__ == "__main__":
    main()
