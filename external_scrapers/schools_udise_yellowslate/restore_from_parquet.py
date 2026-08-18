"""
restore_from_parquet.py

Reconstructs the SQLite database state from Parquet files stored on HF Dataset.
Called at the start of each GitHub Actions batch run instead of downloading the 
full SQLite file. This prevents LFS bloat (no more SQLite uploads to HF).
"""
from __future__ import annotations

import os
import json
import zlib
import sqlite3
from pathlib import Path

import pandas as pd
from huggingface_hub import hf_hub_download

HF_TOKEN = os.environ.get("HF_TOKEN", "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")
HF_REPO  = os.environ.get("HF_REPO", "herseiiii/udise-data")

ROOT    = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("UDISE_DB", ROOT / "data/runtime/udise_data.sqlite3"))

def compress_text(text: str | None) -> bytes | None:
    if not text:
        return None
    return zlib.compress(text.encode("utf-8"), level=6)

def restore() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Download Parquet files
    pin_parquet_path    = None
    school_parquet_path = None
    try:
        print("Downloading pin_tasks.parquet from HF...")
        pin_parquet_path = hf_hub_download(
            repo_id=HF_REPO, filename="parquet/pin_tasks.parquet",
            repo_type="dataset", token=HF_TOKEN
        )
        print("Downloading schools.parquet from HF...")
        school_parquet_path = hf_hub_download(
            repo_id=HF_REPO, filename="parquet/schools.parquet",
            repo_type="dataset", token=HF_TOKEN
        )
    except Exception as e:
        print(f"Could not download Parquet files (first run?): {e}")

    if pin_parquet_path is None:
        print("No Parquet state found. Starting fresh run.")
        return

    pins_df    = pd.read_parquet(pin_parquet_path)
    schools_df = pd.read_parquet(school_parquet_path) if school_parquet_path else pd.DataFrame()

    completed_count = len(pins_df[pins_df["status"] == "completed"])
    total_count     = len(pins_df)
    print(f"Parquet state: {completed_count:,} / {total_count:,} PINs completed.")
    print(f"Parquet state: {len(schools_df):,} school records.")

    # Connect to (or create) the SQLite database
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Check if there's already a valid job in the DB
    try:
        row = conn.execute("SELECT id, status FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            print(f"Existing job found in DB: id={row[0]}, status={row[1]}. Skipping Parquet restore.")
            conn.close()
            return
    except Exception:
        pass  # Table doesn't exist yet — fresh DB

    # Import app to initialize the database schema
    print("Initializing DB schema via app...")
    from app import database, load_pincodes

    pincodes = load_pincodes()
    job_id   = database.create_job(pincodes)
    print(f"Created fresh job {job_id} with {len(pincodes):,} PIN codes.")

    # Bulk-mark completed and failed PINs from Parquet so they won't be re-scraped
    completed_pins = set(pins_df[pins_df["status"] == "completed"]["pincode"].astype(str).tolist())
    failed_pins    = set(pins_df[pins_df["status"] == "failed"]["pincode"].astype(str).tolist())

    print(f"Marking {len(completed_pins):,} PINs as completed in fresh DB...")
    with sqlite3.connect(DB_PATH) as db:
        db.execute("PRAGMA foreign_keys=ON")
        if completed_pins:
            db.executemany(
                "UPDATE pin_tasks SET status='completed', completed_at=datetime('now') "
                "WHERE job_id=? AND pincode=?",
                [(job_id, p) for p in completed_pins]
            )
        if failed_pins:
            db.executemany(
                "UPDATE pin_tasks SET status='failed' WHERE job_id=? AND pincode=?",
                [(job_id, p) for p in failed_pins]
            )

    # Restore school records from Parquet so we don't re-scrape them
    if not schools_df.empty:
        print(f"Restoring {len(schools_df):,} school records from Parquet...")
        with sqlite3.connect(DB_PATH) as db:
            db.execute("PRAGMA foreign_keys=ON")
            for _, row in schools_df.iterrows():
                try:
                    db.execute(
                        "INSERT OR IGNORE INTO schools"
                        "(job_id,pincode,school_id,udise_code,year_id,school_name,"
                        "status,summary_json,error,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            job_id,
                            str(row.get("pincode") or ""),
                            str(row.get("school_id") or ""),
                            str(row.get("udise_code") or ""),
                            str(row.get("year_id") or ""),
                            str(row.get("school_name") or ""),
                            str(row.get("status") or "pending"),
                            str(row.get("summary_json") or "{}"),
                            str(row.get("error") or ""),
                            str(row.get("created_at") or ""),
                            str(row.get("updated_at") or ""),
                        )
                    )
                except Exception:
                    pass

    conn.close()
    print("✅ Database state successfully restored from Parquet files.")
    print(f"   Ready to continue scraping {len(pincodes) - len(completed_pins) - len(failed_pins):,} remaining PINs.")

if __name__ == "__main__":
    restore()
