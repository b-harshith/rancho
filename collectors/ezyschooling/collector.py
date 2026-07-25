#!/usr/bin/env python3
"""Configuration-driven, resumable Ezyschooling page -> detail collector.

The collector refuses unverified city mappings. Raw responses are append-only JSONL;
checkpoints only record completed work and may safely be resumed.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import random
import re
import tempfile
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator, FormatChecker, RefResolver
from src.multicity.config import load_city_registry
from src.multicity.validators import validate_entity

VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
DEFAULT_API = "https://api.main.ezyschooling.com/api/v1/schools/document/"
SITE = "https://ezyschooling.com"
CHALLENGE_MARKERS = ("captcha", "cf-chl-", "cloudflare", "access denied", "verify you are human")


class CollectionFailure(RuntimeError):
    def __init__(self, message: str, *, stage: str, source_url: str | None = None, body_sha256: str | None = None, challenge: str | None = None):
        super().__init__(message)
        self.stage, self.source_url, self.body_sha256, self.challenge = stage, source_url, body_sha256, challenge


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, indent=2, ensure_ascii=False, sort_keys=True)
            out.write("\n")
            out.flush(); os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(canonical_json(value).decode() + "\n")
        out.flush(); os.fsync(out.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    with path.open(encoding="utf-8") as src:
        return [json.loads(line) for line in src if line.strip()]


def _yaml_city_block(text: str, city: str) -> dict[str, Any]:
    """Minimal fallback reader; JSON config is preferred for production."""
    marker = f"canonical_city_id: {city}"
    if marker not in text: raise ValueError(f"city {city!r} absent from config")
    block = text[text.index(marker):]
    nxt = block.find("\n  - canonical_city_id:", 1)
    if nxt >= 0: block = block[:nxt]
    result: dict[str, Any] = {"canonical_city_id": city}
    for key in ("display_name", "state", "country"):
        match = re.search(rf"^\s*{key}:\s*([^#\n]+)", block, re.M)
        if match: result[key] = match.group(1).strip().strip('"\'')
    # Ezyschooling must be added explicitly; never reuse YellowSlate mappings.
    em = re.search(r"ezyschooling:\s*\{([^}]+)\}", block)
    if em:
        mapping = {}
        for k, v in re.findall(r"([a-z_]+):\s*([^,}]+)", em.group(1)):
            val = v.strip().strip('"\'')
            mapping[k] = None if val in {"null", "~", ""} else val
        result["source_mappings"] = {"ezyschooling": mapping}
    return result


def load_city_config(path: Path, city: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        doc = json.loads(text); cities = doc.get("cities", doc)
        item = cities.get(city) if isinstance(cities, dict) else next((x for x in cities if x.get("canonical_city_id") == city), None)
        if not item: raise ValueError(f"city {city!r} absent from config")
        return item
    return _yaml_city_block(text, city)


def verified_mapping(city_cfg: dict[str, Any]) -> dict[str, Any]:
    mapping = (city_cfg.get("source_mappings") or {}).get("ezyschooling") or city_cfg.get("ezyschooling")
    if not isinstance(mapping, dict):
        raise ValueError("BLOCKED: Ezyschooling mapping missing; source slug must not be guessed")
    required = ("city_slug", "city_name", "verified_url", "verified_at")
    missing = [key for key in required if not mapping.get(key)]
    if missing or mapping.get("verified") is not True:
        raise ValueError(f"BLOCKED: unverified Ezyschooling mapping ({', '.join(missing) or 'verified != true'})")
    components = mapping.get("components") or [mapping]
    for component in components:
        if not component.get("city_slug") or not component.get("city_name"):
            raise ValueError("BLOCKED: each NCR component needs evidenced city_slug and city_name")
    return mapping


def detect_challenge(text: str) -> str | None:
    lowered = text.lower()
    return next((marker for marker in CHALLENGE_MARKERS if marker in lowered), None)


class JSONLDParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.capture = False; self.parts: list[str] = []; self.docs: list[Any] = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json": self.capture = True; self.parts = []
    def handle_data(self, data):
        if self.capture: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == "script" and self.capture:
            try: self.docs.append(json.loads(html.unescape("".join(self.parts))))
            except json.JSONDecodeError: pass
            self.capture = False


def parse_page_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    rows = payload.get("results") or payload.get("schools") or []
    if not isinstance(rows, list): raise ValueError("page payload has no result list")
    return rows, payload.get("count")


def school_url(row: dict[str, Any]) -> str:
    candidate = row.get("url") or row.get("absolute_url")
    if candidate: return urljoin(SITE, str(candidate))
    slug = row.get("slug")
    if not slug: raise ValueError("school record missing detail URL/slug")
    return f"{SITE}/school/{slug}"


def parse_detail_document(text: str, url: str) -> dict[str, Any]:
    challenge = detect_challenge(text)
    if challenge:
        raise CollectionFailure(f"challenge page detected: {challenge}", stage="detail", source_url=url, body_sha256=hashlib.sha256(text.encode()).hexdigest(), challenge=challenge)
    parser = JSONLDParser(); parser.feed(text)
    school_docs: list[dict[str, Any]] = []
    def visit(value):
        if isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, dict):
            if value.get("@type") in {"School", "EducationalOrganization", "Organization"}: school_docs.append(value)
            visit(value.get("@graph", []))
    visit(parser.docs)
    selected = school_docs[0] if school_docs else {}
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return {"url": url, "jsonld": selected, "page_title": html.unescape(re.sub(r"\s+", " ", title.group(1))).strip() if title else None}


def _number(value: Any) -> float | None:
    try: return float(value) if value not in (None, "", "NA") else None
    except (TypeError, ValueError): return None


def annual_fees(row: dict[str, Any]) -> tuple[float | None, float | None]:
    fees = row.get("avg_fees") or {}; sessions = [v for v in fees.values() if isinstance(v, dict)]
    values: list[float] = []
    for session in sessions:
        for info in (session.get("class_wise") or {}).values():
            value = _number(info.get("fees_numbers"))
            if value is not None: values.append(value * {"monthly": 12, "quarterly": 4}.get(str(info.get("tenure", "monthly")).lower(), 1))
        rng = session.get("range") or {}
        multiplier = {"monthly": 12, "quarterly": 4}.get(str(rng.get("tenure", "monthly")).lower(), 1)
        values += [v * multiplier for v in (_number(rng.get("lowest_fee")), _number(rng.get("highest_fee"))) if v is not None]
    return (min(values), max(values)) if values else (None, None)


def normalize_school(row: dict[str, Any], detail: dict[str, Any], city: str, scraped_at: str) -> dict[str, Any]:
    source_id = str(row.get("id") or row.get("slug") or hashlib.sha256(school_url(row).encode()).hexdigest()[:16])
    source_city = row.get("school_city") or {}; geo = row.get("geocoords") or {}; ld = detail.get("jsonld") or {}
    address_obj = ld.get("address") if isinstance(ld.get("address"), dict) else {}
    lat, lon = _number(geo.get("lat")), _number(geo.get("lon"))
    fee_min, fee_max = annual_fees(row)
    url = school_url(row)
    flags = []
    if lat is None or lon is None: flags.append("missing_coordinates")
    if not row.get("street_address") and not address_obj: flags.append("missing_address")
    return {
        "canonical_city_id": city, "entity_kind": "school", "entity_id": f"{city}:school:ezyschooling:{source_id}",
        "source": "ezyschooling", "source_entity_id": source_id,
        "source_city_id": source_city.get("id"), "source_city_name": source_city.get("name"), "name": row.get("name") or ld.get("name"),
        "lat": lat, "lon": lon, "coordinate_source": "ezyschooling" if lat is not None else None,
        "coordinate_precision": "source_point" if lat is not None else None, "source_url": url, "scraped_at": scraped_at,
        "schema_version": SCHEMA_VERSION, "udise_code": None, "enrollment": None,
        "annual_fee_min": fee_min, "annual_fee_max": fee_max,
        "address": row.get("street_address") or address_obj.get("streetAddress"), "pincode": row.get("zipcode") or address_obj.get("postalCode"),
        "area": (row.get("school_area") or {}).get("name") if isinstance(row.get("school_area"), dict) else row.get("school_area"),
        "boards": sorted({str(x.get("name")) for x in row.get("school_boardss", []) if x.get("name")}),
        "quality_flags": sorted(flags),
        "lineage": {"collector_version": VERSION, "page_raw_sha256": row.get("_page_raw_sha256"), "detail_raw_sha256": detail.get("_raw_sha256"), "detail_stage": "visited"},
    }


def fetch(url: str, timeout: float, retries: int) -> tuple[int, bytes]:
    req = Request(url, headers={"User-Agent": "BangaloreRancho-research/1.0", "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=timeout) as response: return response.status, response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
            if attempt < retries: time.sleep(min(8, 0.5 * (2 ** attempt)) + random.random() / 4)
    raise CollectionFailure(f"request failed after {retries + 1} attempts: {type(last).__name__}", stage="request", source_url=url)


def validate_normalized(records: list[dict[str, Any]], city: str, cities_path: Path) -> None:
    registry = load_city_registry(cities_path, cities_path.parent / "source_city_registry.json")
    schema_root = Path(__file__).resolve().parents[2] / "schemas" / "multicity" / "v1"
    common = json.loads((schema_root / "common_entity.schema.json").read_text())
    school = json.loads((schema_root / "school.schema.json").read_text())
    resolver = RefResolver.from_schema(school, store={"common_entity.schema.json": common, common["$id"]: common})
    schema_validator = Draft202012Validator(school, resolver=resolver, format_checker=FormatChecker())
    for index, record in enumerate(records):
        validate_entity(record, "school", registry)
        errors = sorted(schema_validator.iter_errors(record), key=lambda error: list(error.path))
        if errors:
            raise ValueError(f"normalized record {index} fails school schema: {errors[0].message}")


def persist_failure(output_root: Path, exc: BaseException) -> None:
    now = utcnow()
    evidence = {"status": "QUARANTINED", "occurred_at": now, "error_type": type(exc).__name__, "error": str(exc), "stage": getattr(exc, "stage", "collector"), "source_url": getattr(exc, "source_url", None), "body_sha256": getattr(exc, "body_sha256", None), "challenge_marker": getattr(exc, "challenge", None)}
    digest = hashlib.sha256(canonical_json(evidence)).hexdigest()[:16]
    atomic_json(output_root / "quarantine" / f"failure_{digest}.json", evidence)
    atomic_json(output_root / "manifests" / "ezyschooling_run.json", {"status": "FAILED_QUARANTINED", "collector_version": VERSION, "failed_at": now, "failure_evidence": f"quarantine/failure_{digest}.json", "challenge_detected": bool(evidence["challenge_marker"])})


def run(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_city_config(Path(args.config), args.city); mapping = verified_mapping(cfg)
    if args.city != "delhi_ncr": raise ValueError("PRODUCTION BLOCKED: Delhi NCR is the only active city")
    root = Path(args.output_root); raw = root / "raw" / "ezyschooling"; norm = root / "normalized"
    page_raw, detail_raw = raw / "pages.jsonl", raw / "details.jsonl"
    page_cp, detail_cp = raw / "page_checkpoint.json", raw / "detail_checkpoint.json"
    if not args.resume and any(p.exists() for p in (page_raw, detail_raw, page_cp, detail_cp)):
        raise ValueError("output contains prior state; use --resume or a clean output root")
    if args.dry_run:
        return {"status": "DRY_RUN", "city": args.city, "components": len(mapping.get("components") or [mapping]), "mapping_verified": True}
    completed_pages = set(json.loads(page_cp.read_text()).get("completed", [])) if args.resume and page_cp.exists() else set()
    page_history = {str(e.get("page_key")): e for e in read_jsonl(page_raw)}
    page_rows: dict[str, dict[str, Any]] = {}
    http: dict[str, int] = {}; attempted = succeeded = 0
    components = mapping.get("components") or [mapping]
    page_size = max(1, min(100, args.page_size))
    for component in components:
        offset, total = 0, None
        while total is None or offset < total:
            page_key = f"{component['city_slug']}:{offset}"
            if page_key in completed_pages:
                prior = page_history.get(page_key)
                if prior is None:
                    raise ValueError(f"checkpoint/raw mismatch for completed page {page_key}")
                _, total = parse_page_payload(prior["payload"])
                if total is None:
                    raise ValueError(f"completed page {page_key} has no total count")
                offset += page_size; continue
            if args.sample is not None and attempted >= args.sample: break
            params = {"is_active": "true", "is_verified": "true", "limit": page_size, "offset": offset, "ordering": "-fees", "school_city": component["city_slug"], "session": mapping.get("session", "2026-2027")}
            page_url = f"{mapping.get('api_url', DEFAULT_API)}?{urlencode(params)}"
            status, body = fetch(page_url, args.timeout, args.retries)
            http[str(status)] = http.get(str(status), 0) + 1; attempted += 1
            body_text = body.decode("utf-8", "replace"); challenge = detect_challenge(body_text)
            if challenge:
                raise CollectionFailure(f"challenge page detected: {challenge}", stage="page", source_url=page_url, body_sha256=hashlib.sha256(body).hexdigest(), challenge=challenge)
            payload = json.loads(body); rows, total = parse_page_payload(payload)
            digest = hashlib.sha256(body).hexdigest(); captured = utcnow()
            append_jsonl(page_raw, {"stage": "page", "page_key": page_key, "source_url": mapping.get("verified_url"), "request_params": params, "http_status": status, "scraped_at": captured, "raw_sha256": digest, "payload": payload})
            for row in rows:
                row = dict(row); row["_page_raw_sha256"] = digest; page_rows[str(row.get("id") or school_url(row))] = row
            completed_pages.add(page_key); atomic_json(page_cp, {"completed": sorted(completed_pages)}); succeeded += 1
            offset += page_size; time.sleep(args.sleep)
        if args.sample is not None and attempted >= args.sample: break
    # Reconstruct all rows from immutable history so resume is complete.
    for envelope in read_jsonl(page_raw):
        digest = envelope.get("raw_sha256")
        for row in parse_page_payload(envelope["payload"])[0]:
            row = dict(row); row["_page_raw_sha256"] = digest; page_rows[str(row.get("id") or school_url(row))] = row
    ordered = [page_rows[key] for key in sorted(page_rows)]
    if args.limit is not None: ordered = ordered[:args.limit]
    completed_details = set(json.loads(detail_cp.read_text()).get("completed", [])) if args.resume and detail_cp.exists() else set()
    existing_details = {str(e["source_entity_id"]): e for e in read_jsonl(detail_raw)}
    def detail_job(row):
        sid, url = str(row.get("id") or row.get("slug")), school_url(row)
        status, body = fetch(url, args.timeout, args.retries); text = body.decode("utf-8", "replace")
        parsed = parse_detail_document(text, url); parsed["_raw_sha256"] = hashlib.sha256(body).hexdigest()
        return sid, {"stage": "detail", "source_entity_id": sid, "source_url": url, "http_status": status, "scraped_at": utcnow(), "raw_sha256": parsed["_raw_sha256"], "payload": parsed}
    pending = [r for r in ordered if str(r.get("id") or r.get("slug")) not in completed_details]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        for sid, envelope in pool.map(detail_job, pending):
            append_jsonl(detail_raw, envelope); existing_details[sid] = envelope
            completed_details.add(sid); atomic_json(detail_cp, {"completed": sorted(completed_details)}); time.sleep(args.sleep)
    scraped_at = utcnow(); normalized = [normalize_school(row, (existing_details[str(row.get("id") or row.get("slug"))]["payload"]), args.city, scraped_at) for row in ordered]
    # Leakage gate: all source labels must be approved component names.
    allowed = {str(c["city_name"]).casefold() for c in components}
    leaked = [r for r in normalized if r.get("source_city_name") and str(r["source_city_name"]).casefold() not in allowed]
    if leaked: raise ValueError(f"cross-city leakage detected in {len(leaked)} records")
    validate_normalized(normalized, args.city, Path(args.config))
    atomic_json(norm / "ezyschooling_schools.json", normalized)
    manifest = {"status": "COLLECTED_NOT_ADMITTED", "city": args.city, "collector_version": VERSION, "mapping_verified": True, "pages_attempted": attempted, "pages_succeeded": succeeded, "http_status_distribution": http, "records_unique": len(ordered), "records_normalized": len(normalized), "details_completed": len(completed_details), "challenge_detected": False, "generated_at": scraped_at}
    atomic_json(root / "manifests" / "ezyschooling_run.json", manifest); return manifest


def cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", required=True); p.add_argument("--config", required=True); p.add_argument("--output-root", required=True)
    p.add_argument("--resume", action="store_true"); p.add_argument("--sample", type=int); p.add_argument("--limit", type=int); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--timeout", type=float, default=20); p.add_argument("--retries", type=int, default=3); p.add_argument("--sleep", type=float, default=1.5); p.add_argument("--workers", type=int, default=2); p.add_argument("--page-size", type=int, default=100)
    args = p.parse_args(argv)
    try: print(json.dumps(run(args), sort_keys=True))
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        persist_failure(Path(args.output_root), exc)
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True)); return 2
    return 0


if __name__ == "__main__": raise SystemExit(cli())
