from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from huggingface_hub import HfApi

from app import database, collector, load_pincodes, DB_PATH
from app_hf import HF_TOKEN, HF_REPO, BACKUP_PATH

CHECKPOINT_INTERVAL_SECONDS = max(
    60, int(os.environ.get("UDISE_CHECKPOINT_INTERVAL_SECONDS", "1800"))
)


def upload_parquet_final() -> None:
    """Export Parquet once, after every PIN task has reached a terminal state."""
    try:
        print("Exporting final Parquet files from the completed database...")
        from export_to_parquet import export_all
        export_all()
        print("Final Parquet files exported and uploaded successfully.")
    except Exception as pe:
        print(f"Final Parquet export failed: {pe}")


def upload_sqlite_checkpoint(api: "HfApi", label: str = "checkpoint") -> bool:
    """Upload a transaction-safe database snapshot that the next runner can resume."""
    if not DB_PATH.exists():
        return False
    try:
        print(f"Creating safe SQLite hot backup for {label}...")
        with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(BACKUP_PATH)) as dest:
            with dest:
                src.backup(dest)
        print(f"Uploading SQLite {label} to Hugging Face Dataset...")
        api.upload_file(
            path_or_fileobj=str(BACKUP_PATH),
            path_in_repo="udise_data.sqlite3",
            repo_id=HF_REPO,
            repo_type="dataset",
        )
        print(f"SQLite {label} upload complete.")
        return True
    except Exception as e:
        print(f"SQLite {label} upload failed: {e}")
        return False


def main() -> None:
    print("Initializing CLI headless scraping batch...")
    
    # Check if there is an active job already in progress
    status = database.status()
    job = status.get("job")
    
    unfinished_statuses = {"pending", "retry", "claimed", "running"}
    has_unfinished_pins = bool(
        job and any(pin["status"] in unfinished_statuses for pin in status["pins"])
    )

    if job and has_unfinished_pins:
        job_id = int(job["id"])
        print(f"Resuming existing scraping job {job_id}...")
        recovered = database.recover_interrupted_job(job_id)
        if any(recovered.values()):
            print(
                "Recovered interrupted state: "
                f"{recovered['pincodes']} PINs, {recovered['schools']} schools, "
                f"{recovered['challenges']} CAPTCHA challenges."
            )
        collector.start(job_id)
    elif job:
        print(
            f"Job {job['id']} has no unfinished PIN tasks "
            f"(status: {job['status']}). Nothing to run."
        )
        return
    else:
        print("Starting a new scraping job...")
        pincodes = load_pincodes()
        job_id = database.create_job(pincodes)
        print(f"Created job {job_id} with {len(pincodes)} PIN codes.")
        collector.start(job_id)
    
    # Monitor execution and persist lightweight resumable checkpoints. Rebuilding
    # all Parquet files while eight browsers are active exhausted the hosted runner.
    last_checkpoint = time.monotonic()
    api = HfApi(token=HF_TOKEN) if HF_TOKEN else None

    if not api or not HF_REPO:
        print("Warning: HF_TOKEN or HF_REPO not set. Backups are disabled.")
    
    print(f"Scraper is active. Monitoring job {job_id}...")
    print(
        f"Strategy: resumable SQLite checkpoint every "
        f"{CHECKPOINT_INTERVAL_SECONDS // 60} min; Parquet once after completion."
    )
    
    try:
        while True:
            time.sleep(10)
            
            # Check if collector pool is still running
            if not collector.running:
                print("All scheduled PIN tasks completed or pool stopped.")
                break
                
            if api and HF_REPO and time.monotonic() - last_checkpoint >= CHECKPOINT_INTERVAL_SECONDS:
                # Advance the clock before uploading so a slow upload cannot cause
                # an immediate second checkpoint when control returns.
                last_checkpoint = time.monotonic()
                upload_sqlite_checkpoint(api)
                        
    except KeyboardInterrupt:
        print("Manual interrupt received. Stopping collector...")
        collector.stop()
        
    # A normally completed pool gets one final resumable DB and one final Parquet export.
    if api and HF_REPO:
        upload_sqlite_checkpoint(api, label="final")
        final_job = database.status(job_id).get("job") or {}
        if final_job.get("status") in {"completed", "completed_with_errors"}:
            upload_parquet_final()

if __name__ == "__main__":
    main()
