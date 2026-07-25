#!/usr/bin/env python3
import csv
import gzip
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/client_export/udise_schools_client.sqlite3"
OUTPUT = ROOT / "data/client_export/udise_schools_client.csv"
COMPRESSED = ROOT / "data/client_export/udise_schools_client.csv.gz"

COLUMNS = [
    "udise_code", "school_id", "year_id", "school_name", "pincode",
    "state_name", "district_name", "summary_json", "enrollment_json",
]


def main():
    db = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as output:
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(COLUMNS)
        query = f"SELECT {','.join(COLUMNS)} FROM schools ORDER BY udise_code"
        for count, row in enumerate(db.execute(query), 1):
            writer.writerow([row[column] for column in COLUMNS])
            if count % 5000 == 0:
                print(f"Exported {count:,} schools...", flush=True)
    db.close()

    with open(OUTPUT, "rb") as source, gzip.open(COMPRESSED, "wb", compresslevel=9) as target:
        while chunk := source.read(1024 * 1024):
            target.write(chunk)

    print(f"CSV:  {OUTPUT} ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"Gzip: {COMPRESSED} ({COMPRESSED.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
