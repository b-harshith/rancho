from __future__ import annotations

import os
import json
import zlib
import sqlite3
from pathlib import Path
import pandas as pd
from huggingface_hub import HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("UDISE_DB", ROOT / "data/runtime/udise_data.sqlite3"))
PARQUET_DIR = ROOT / "data/output/parquet"
PARQUET_DIR.mkdir(parents=True, exist_ok=True)

HF_TOKEN = os.environ.get("HF_TOKEN", "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")
HF_REPO = os.environ.get("HF_REPO", "herseiiii/udise-data")

def decompress_text(val: any) -> str | None:
    if val is None:
        return None
    if isinstance(val, bytes):
        try:
            return zlib.decompress(val).decode("utf-8", errors="replace")
        except Exception:
            return str(val)
    return str(val)

def export_schools(conn: sqlite3.Connection) -> Path:
    print("Exporting schools table to Parquet...")
    query = "SELECT id, job_id, pincode, school_id, udise_code, year_id, school_name, status, summary_json, error, created_at, updated_at FROM schools"
    df = pd.read_sql_query(query, conn)
    out_path = PARQUET_DIR / "schools.parquet"
    df.to_parquet(out_path, compression="zstd", index=False)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  - Created {out_path.name} ({len(df):,} rows, {size_mb:.2f} MB)")
    return out_path

def export_pin_tasks(conn: sqlite3.Connection) -> Path:
    print("Exporting pin_tasks table to Parquet...")
    query = "SELECT id, job_id, pincode, position, status, captcha_attempts, school_count, error, started_at, completed_at FROM pin_tasks"
    df = pd.read_sql_query(query, conn)
    out_path = PARQUET_DIR / "pin_tasks.parquet"
    df.to_parquet(out_path, compression="zstd", index=False)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  - Created {out_path.name} ({len(df):,} rows, {size_mb:.2f} MB)")
    return out_path

def export_network_responses(conn: sqlite3.Connection) -> Path:
    print("Exporting network_responses table to Parquet (ZSTD Columnar Compression)...")
    cursor = conn.cursor()
    cursor.execute("SELECT id, job_id, pincode, school_id, year_id, phase, request_id, method, url, status_code, mime_type, body_json, body_text, body_sha256, captured_at FROM network_responses")
    
    rows = []
    count = 0
    while True:
        batch = cursor.fetchmany(10000)
        if not batch:
            break
        for r in batch:
            body_j = decompress_text(r[11])
            body_t = decompress_text(r[12])
            rows.append({
                "id": r[0], "job_id": r[1], "pincode": r[2], "school_id": r[3],
                "year_id": r[4], "phase": r[5], "request_id": r[6], "method": r[7],
                "url": r[8], "status_code": r[9], "mime_type": r[10],
                "body": body_j if body_j else body_t,
                "body_sha256": r[13], "captured_at": r[14]
            })
        count += len(batch)
        print(f"  - Parsed {count:,} response payloads...")
            
    df = pd.DataFrame(rows)
    out_path = PARQUET_DIR / "network_responses.parquet"
    df.to_parquet(out_path, compression="zstd", index=False)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"  - Created {out_path.name} ({len(df):,} rows, {size_mb:.2f} MB)")
    return out_path

def export_all() -> None:
    if Path("data/runtime/udise_data_compressed.sqlite3").exists():
        target_db = Path("data/runtime/udise_data_compressed.sqlite3")
    elif DB_PATH.exists() and DB_PATH.stat().st_size > 100000:
        target_db = DB_PATH
    else:
        print("Downloading DB from HF...")
        target_db = Path(hf_hub_download(repo_id=HF_REPO, filename="udise_data.sqlite3", repo_type="dataset", token=HF_TOKEN))
        
    print(f"Source Database: {target_db} ({target_db.stat().st_size / (1024*1024):.2f} MB)")
    
    conn = sqlite3.connect(target_db)
    
    export_pin_tasks(conn)
    export_schools(conn)
    export_network_responses(conn)
    
    conn.close()
    
    print("\n--- UPLOADING PARQUET FILES TO HF DATASET ---")
    api = HfApi(token=HF_TOKEN)
    api.upload_folder(
        folder_path=str(PARQUET_DIR),
        path_in_repo="parquet",
        repo_id=HF_REPO,
        repo_type="dataset"
    )
    print("✅ All Parquet files uploaded to Hugging Face Dataset under 'parquet/' folder!")

if __name__ == "__main__":
    export_all()
