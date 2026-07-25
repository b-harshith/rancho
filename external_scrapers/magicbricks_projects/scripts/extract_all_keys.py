"""
extract_all_keys.py
-------------------
Recursively walks every record in bangalore.jsonl and collects
ALL JSON keys at every nesting depth (including inside arrays).

Output:
  - Printed to stdout (sorted, deduplicated, with dot-path notation)
  - Saved to  scripts/all_json_keys.txt
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────

JSONL_PATH = Path(__file__).parent.parent / "data" / "raw" / "bangalore.jsonl"
OUTPUT_PATH = Path(__file__).parent / "all_json_keys.txt"


# ── Recursive key extractor ───────────────────────────────────────────────────

def extract_keys(obj, prefix: str, keys: set):
    """Recursively collect every key in obj, using dot-path notation."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            keys.add(full_key)
            extract_keys(v, full_key, keys)
    elif isinstance(obj, list):
        for item in obj:
            extract_keys(item, prefix, keys)
    # scalars → no more keys


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else JSONL_PATH

    if not path.exists():
        print(f"❌  File not found: {path}")
        sys.exit(1)

    print(f"📂  Reading: {path}")

    all_keys: set[str] = set()
    total = 0
    skipped = 0

    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  ⚠  Line {lineno}: JSON error — {e}", file=sys.stderr)
                skipped += 1
                continue
            total += 1
            extract_keys(record, "", all_keys)

    sorted_keys = sorted(all_keys, key=lambda k: k.lower())

    # ── Print to stdout ───────────────────────────────────────────────────────
    print(f"\n✅  Processed {total:,} records ({skipped} skipped)")
    print(f"🔑  Found {len(sorted_keys):,} unique keys\n")
    print("=" * 60)
    for key in sorted_keys:
        print(f"  {key}")
    print("=" * 60)

    # ── Save to file ──────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
        out.write(f"# All JSON keys in: {path.name}\n")
        out.write(f"# Records: {total:,}  |  Unique keys: {len(sorted_keys):,}\n")
        out.write(f"# Keys use dot-path notation for nested fields\n")
        out.write("#\n")
        for key in sorted_keys:
            out.write(key + "\n")

    print(f"\n💾  Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
