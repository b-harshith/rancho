from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .collector import Collector, Options


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-stage MagicBricks localities collector")
    p.add_argument("--city", required=True)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--output-root", required=True, type=Path)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--sample", type=int, help="maximum listing pages per component")
    p.add_argument("--limit", type=int, help="maximum unique locality details (testing only)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--sleep", type=float, default=3.0)
    p.add_argument("--workers", type=int, default=1)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0 or args.retries < 0 or args.sleep < 0 or args.workers < 1 or args.workers > 4:
        print(json.dumps({"status": "blocked", "reason": "invalid timeout/retries/sleep/workers"}), file=sys.stderr)
        return 2
    if (args.sample is not None and args.sample < 1) or (args.limit is not None and args.limit < 1):
        print(json.dumps({"status": "blocked", "reason": "sample/limit must be positive"}), file=sys.stderr)
        return 2
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        city_config = (config.get("cities") or {}).get(args.city)
        if not city_config:
            raise ValueError("city missing from config; refusing to guess a mapping")
        result = Collector(args.city, city_config, Options(
            output_root=args.output_root, timeout=args.timeout, retries=args.retries, sleep=args.sleep,
            workers=args.workers, resume=args.resume, sample=args.sample, limit=args.limit, dry_run=args.dry_run,
        )).run()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("status") in {"complete", "diagnostic_complete", "dry_run"} else 3
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
