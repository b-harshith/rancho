"""
schema_banglore.py
------------------
Reads banglore.jsonl and outputs its inferred schema:
  - field names
  - observed types (across all records)
  - whether the field is always present or optional
  - sample values (first 3 unique)
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path


# ── Locate the file ──────────────────────────────────────────────────────────

def find_file(filename: str) -> Path:
    """Search common locations for the given filename."""
    candidates = [
        Path(filename),                              # current directory / absolute path
        Path(__file__).parent / filename,            # same dir as this script
        Path.home() / "Desktop" / filename,
        Path.home() / "Downloads" / filename,
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()

    # Recursive search from home (limited depth to avoid being slow)
    home = Path.home()
    for match in home.rglob(filename):
        return match.resolve()

    raise FileNotFoundError(
        f"Could not find '{filename}'. "
        "Pass the full path as the first CLI argument: "
        f"  python schema_banglore.py /path/to/{filename}"
    )


# ── Type helpers ──────────────────────────────────────────────────────────────

def infer_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        inner = {infer_type(v) for v in value} if value else {"<empty>"}
        return f"array[{' | '.join(sorted(inner))}]"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# ── Schema accumulator ────────────────────────────────────────────────────────

class FieldInfo:
    def __init__(self):
        self.types: set[str] = set()
        self.count: int = 0          # number of records containing this field
        self.samples: list = []

    def update(self, value):
        self.types.add(infer_type(value))
        self.count += 1
        if len(self.samples) < 3 and value not in self.samples:
            self.samples.append(value)


def build_schema(path: Path) -> tuple[dict[str, FieldInfo], int]:
    fields: dict[str, FieldInfo] = defaultdict(FieldInfo)
    total = 0

    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  ⚠  Skipping line {lineno} (JSON error: {e})", file=sys.stderr)
                continue

            if not isinstance(record, dict):
                print(f"  ⚠  Line {lineno} is not a JSON object — skipping.", file=sys.stderr)
                continue

            total += 1
            for key, val in record.items():
                fields[key].update(val)

    return fields, total


# ── Pretty printer ────────────────────────────────────────────────────────────

def print_schema(fields: dict[str, FieldInfo], total: int, filepath: Path):
    col_w = max((len(k) for k in fields), default=10) + 2

    print(f"\n{'═' * 70}")
    print(f"  Schema of: {filepath.name}")
    print(f"  Path      : {filepath}")
    print(f"  Records   : {total:,}")
    print(f"{'═' * 70}")
    print(
        f"  {'Field':<{col_w}}  {'Type(s)':<28}  {'Present':<10}  Sample Values"
    )
    print(f"  {'-' * (col_w)}  {'-' * 28}  {'-' * 10}  {'-' * 30}")

    for field, info in sorted(fields.items()):
        types_str = " | ".join(sorted(info.types))
        presence = f"{info.count}/{total}"
        optional_flag = "" if info.count == total else "  (optional)"
        sample_str = ", ".join(repr(s) for s in info.samples[:3])
        # Truncate long sample strings
        if len(sample_str) > 50:
            sample_str = sample_str[:47] + "..."
        print(
            f"  {field:<{col_w}}  {types_str:<28}  {presence:<10}  {sample_str}{optional_flag}"
        )

    print(f"{'═' * 70}\n")
    print(f"  Total fields : {len(fields)}")
    print(f"  Total records: {total:,}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else "banglore.jsonl"

    print(f"\n🔍  Looking for '{filename}' …")
    try:
        filepath = find_file(filename)
    except FileNotFoundError as e:
        print(f"\n❌  {e}\n")
        sys.exit(1)

    print(f"✅  Found: {filepath}")
    print("📊  Analysing schema …\n")

    fields, total = build_schema(filepath)

    if total == 0:
        print("⚠  No valid JSON records found in the file.")
        sys.exit(1)

    print_schema(fields, total, filepath)


if __name__ == "__main__":
    main()
