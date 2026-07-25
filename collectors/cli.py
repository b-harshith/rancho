from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .adapters import extract_records, normalize
from .core import (Layout, Manifest, SafetyError, append_jsonl, atomic_json,
                   load_config, mapping_for, require_verified_mapping,
                   resolve_city, validate_preflight)

SOURCES = ("yellowslate", "udise", "magicbricks", "99acres", "practo")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fail-closed multi-city collector adapter")
    p.add_argument("source", choices=SOURCES)
    p.add_argument("--city", required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--sample", "--limit", dest="limit", type=int)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--fixture", type=Path, help="redacted local JSON fixture; no network")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--sleep", type=float, default=3.0)
    p.add_argument("--workers", type=int, default=1)
    return p


def validate_args(args: argparse.Namespace) -> None:
    from .core import SAFE_PART

    if not SAFE_PART.fullmatch(args.city):
        raise SafetyError("city must be a canonical identifier without path separators")
    if args.workers < 1 or args.workers > 4:
        raise SafetyError("workers must be 1..4; default is 1")
    if args.timeout <= 0 or args.retries < 0 or args.sleep < 0:
        raise SafetyError("timeout must be positive; retries/sleep cannot be negative")
    if args.limit is not None and args.limit < 1:
        raise SafetyError("sample/limit must be positive")


def run(args: argparse.Namespace) -> dict[str, Any]:
    validate_args(args)
    config = load_config(args.config)
    city = resolve_city(config, args.city)
    layout = Layout(args.output_root, args.city, args.source)
    manifest = Manifest(args.city, args.source, args.dry_run)

    if args.source == "udise":
        # UDISE intentionally has no automated request path. This writes only a human-entry job plan.
        udise = city.get("udise") or mapping_for(city, "udise")
        pin_file = udise.get("pincode_file") if isinstance(udise, dict) else None
        if not pin_file:
            raise SafetyError("UDISE requires an approved pincode_file; human entry only")
        plan = {"canonical_city_id": args.city, "mode": "human_entry_only", "pincode_file": pin_file,
                "captcha": "must be entered by a human; never stored or logged"}
        atomic_json(layout.manifest, {**manifest.as_dict(), "human_entry_plan": plan})
        return plan

    mapping = require_verified_mapping(city, args.source)
    if args.source == "99acres" and not os.environ.get("ACRES99_SESSION"):
        raise SafetyError("99acres requires ACRES99_SESSION at runtime; no default session exists")

    resolved = {"city": args.city, "source": args.source, "mapping": mapping,
                "output": str(layout.city_root), "network_collection": False,
                "timeout": args.timeout, "retries": args.retries, "sleep": args.sleep, "workers": args.workers}
    if args.dry_run and not args.fixture:
        atomic_json(layout.manifest, {**manifest.as_dict(), "resolved": resolved})
        return resolved
    if not args.fixture:
        raise SafetyError("network collection is intentionally disabled in this safe adapter; use --fixture for preflight")

    if args.resume and layout.checkpoint.exists():
        checkpoint = json.loads(layout.checkpoint.read_text(encoding="utf-8"))
        if checkpoint.get("complete") and checkpoint.get("fixture") == str(args.fixture):
            return {"status": "already_complete", "checkpoint": str(layout.checkpoint),
                    "records": checkpoint.get("records", 0)}

    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    records = extract_records(args.source, payload)
    if args.limit:
        records = records[:args.limit]
    manifest.pages_attempted = 1
    manifest.records_raw = len(records)
    if args.preflight or args.dry_run:
        preflight_rows = [{**r, "source_city_name": r.get("source_city_name") or r.get("cityName") or r.get("ctname"),
                           "source_url": r.get("source_url") or r.get("url")} for r in records]
        result = validate_preflight(preflight_rows, city)
        manifest.pages_succeeded = 1
        atomic_json(layout.manifest, {**manifest.as_dict(), "preflight": result, "resolved": resolved})
        return result

    normalized, rejected = [], []
    seen: set[str] = set()
    for record in records:
        try:
            row = normalize(args.source, args.city, mapping, record)
            if row["entity_id"] not in seen:
                seen.add(row["entity_id"])
                normalized.append(row)
        except SafetyError as exc:
            rejected.append({"reason": str(exc), "record": record})
            manifest.rejection_reasons[str(exc)] = manifest.rejection_reasons.get(str(exc), 0) + 1
    append_jsonl(layout.raw, records)
    if rejected:
        append_jsonl(layout.quarantine, rejected)
    atomic_json(layout.normalized, normalized)
    manifest.pages_succeeded = 1
    manifest.records_unique = len(seen)
    manifest.records_normalized = len(normalized)
    manifest.records_rejected = len(rejected)
    atomic_json(layout.checkpoint, {"fixture": str(args.fixture), "complete": True, "records": len(records)})
    atomic_json(layout.manifest, manifest.as_dict())
    return manifest.as_dict()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        print(json.dumps(run(args), indent=2, sort_keys=True))
        return 0
    except (SafetyError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
