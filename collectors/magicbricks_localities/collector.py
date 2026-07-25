from __future__ import annotations

import hashlib
import json
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .parser import canonical_url, is_challenge, parse_detail_page, parse_listing_page

ALLOWED_HOSTS = {"www.magicbricks.com", "magicbricks.com"}
SAFE_CITY = re.compile(r"^[a-z][a-z0-9_]*$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")


def trusted_url(url: str) -> str:
    value = urljoin("https://www.magicbricks.com/", url)
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password:
        raise ValueError("URL must be HTTPS on the MagicBricks allowlist")
    if any(part in {".", ".."} for part in unquote(parts.path).replace("\\", "/").split("/")):
        raise ValueError("URL path traversal is not allowed")
    return urlunsplit(("https", parts.netloc.lower(), parts.path, parts.query, ""))


def contained(base: Path, *parts: str) -> Path:
    root = base.expanduser().resolve()
    candidate = root.joinpath(*parts).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("output path escapes configured root")
    return candidate


def safe_token(value: Any, field: str = "token") -> str:
    token = str(value)
    if not SAFE_TOKEN.fullmatch(token):
        raise ValueError(f"{field} must be a strict path-safe token")
    return token


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@dataclass
class Options:
    output_root: Path
    timeout: float = 30.0
    retries: int = 3
    sleep: float = 3.0
    workers: int = 1
    resume: bool = False
    limit: int | None = None
    sample: int | None = None
    dry_run: bool = False


class Fetcher:
    def __init__(self, options: Options):
        self.options = options

    def get(self, url: str) -> tuple[str, dict[str, Any]]:
        url = trusted_url(url)
        last: Exception | None = None
        from curl_cffi import requests as cf_requests
        for attempt in range(self.options.retries + 1):
            try:
                resp = cf_requests.get(url, impersonate="chrome", timeout=int(self.options.timeout))
                if resp.status_code == 200:
                    return resp.text, {"status": 200, "content_type": resp.headers.get("Content-Type")}
                else:
                    raise RuntimeError(f"HTTP {resp.status_code}")
            except Exception as exc:
                last = exc
                if attempt < self.options.retries:
                    time.sleep(min(60.0, self.options.sleep * (2**attempt) + random.uniform(0, 0.5)))
        raise RuntimeError(f"request failed after retries: {type(last).__name__}") from last



class Collector:
    def __init__(self, city: str, config: dict[str, Any], options: Options, fetcher: Fetcher | None = None):
        if not SAFE_CITY.fullmatch(city):
            raise ValueError("city must be a safe canonical identifier")
        self.city, self.config, self.options = city, config, options
        self.fetcher = fetcher or Fetcher(options)
        output_root = options.output_root.expanduser().resolve()
        self.root = contained(output_root, city, "magicbricks_localities")
        self.raw = contained(self.root, "raw")
        self.checkpoints = contained(self.root, "checkpoints")
        self.quarantine = contained(self.root, "quarantine.jsonl")
        self.components = config.get("components") or []
        if not self.components:
            raise ValueError("configuration must contain at least one verified component")
        for component in self.components:
            safe_token(component.get("source_city_id", ""), "source_city_id")
            trusted_url(str(component.get("verified_url", "")))
            template = str(component.get("pagination_url", "")).replace("{page}", "2").replace("{city_name}", "city")
            trusted_url(template)

    def _save_raw(self, stage: str, key: str, url: str, html: str, metadata: dict[str, Any]) -> None:
        stage = safe_token(stage, "stage")
        key = safe_token(key, "raw key")
        digest = hashlib.sha256(html.encode()).hexdigest()
        path = contained(self.raw, stage, f"{key}-{digest[:12]}.html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path = contained(self.raw, stage, path.name)
        if not path.exists():
            fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(html)
                    handle.flush(); os.fsync(handle.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
        metadata_path = contained(self.raw, "metadata.jsonl")
        append_jsonl(metadata_path, {
            "stage": stage, "key": key, "url": url, "sha256": digest,
            "saved_path": str(path.relative_to(self.root)), "fetched_at": now(), **metadata,
        })

    def _checkpoint(self, name: str) -> dict[str, Any]:
        name = safe_token(name, "checkpoint name")
        path = contained(self.checkpoints, f"{name}.json")
        return json.loads(path.read_text()) if self.options.resume and path.exists() else {}

    def _write_checkpoint(self, name: str, value: dict[str, Any]) -> None:
        name = safe_token(name, "checkpoint name")
        atomic_json(contained(self.checkpoints, f"{name}.json"), value)

    def _quarantine(self, value: dict[str, Any]) -> None:
        append_jsonl(contained(self.root, "quarantine.jsonl"), value)

    def _failure(self, stage: str, reason: str) -> None:
        atomic_json(contained(self.root, "manifest.json"), {
            "status": "failed", "production_complete": False, "canonical_city_id": self.city,
            "source": "magicbricks_localities", "failed_stage": stage, "reason": reason,
            "finished_at": now(),
        })

    def run(self) -> dict[str, Any]:
        if self.options.workers != 1:
            # Accepted for contract compatibility, deliberately serialized by default/site load policy.
            raise ValueError("production collector currently requires --workers 1")
        if self.options.dry_run:
            return {"status": "dry_run", "canonical_city_id": self.city, "components": self.components,
                    "output_root": str(self.root), "stages": ["listing_enumeration", "detail_fetch"]}
        discovered, preflights = self.stage1()
        details = self.stage2(discovered)
        return self.finalize(discovered, details, preflights)

    def stage1(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        all_rows: dict[str, dict[str, Any]] = {}
        preflights: list[dict[str, Any]] = []
        for component in self.components:
            required = ("source_city_id", "source_city_name", "verified_url", "pagination_url")
            if any(not component.get(k) for k in required):
                raise ValueError(f"component mapping incomplete: {component.get('source_city_name')}")
            slug = str(component["source_city_id"])
            checkpoint = self._checkpoint(f"pages-{slug}")
            page = int(checkpoint.get("next_page", 1))
            seen_fingerprints = set(checkpoint.get("fingerprints", []))
            component_rows = {r["link_key"]: r for r in checkpoint.get("records", [])}
            expected_total = checkpoint.get("expected_total")
            while True:
                url = component["verified_url"] if page == 1 else component["pagination_url"].format(
                    page=page, city_name=urlencode({"v": component["source_city_name"]})[2:])
                trusted_url(url)
                html, metadata = self.fetcher.get(url)
                self._save_raw("pages", f"{slug}-p{page:05d}", url, html, metadata)
                parsed = parse_listing_page(html, url)
                if parsed["challenge"]:
                    self._quarantine({"stage": "page", "url": url, "reason": "challenge_detected", "at": now()})
                    raise RuntimeError(f"challenge detected for {component['source_city_name']}; stopped safely")
                if page == 1:
                    observed_id, observed_name = str(parsed.get("source_city_id") or ""), parsed.get("source_city_name")
                    if observed_id != str(component["source_city_id"]) or str(observed_name).casefold() != str(component["source_city_name"]).casefold():
                        raise RuntimeError(f"verified mapping mismatch for {component['source_city_name']}")
                    expected_total = parsed.get("total_localities")
                rows = parsed["records"]
                matches = sum(str(r.get("source_city_name", "")).casefold() == str(component["source_city_name"]).casefold() for r in rows)
                ratio = matches / len(rows) if rows else 0.0
                if page == 1 and ratio < 0.90:
                    raise RuntimeError(f"city preflight {ratio:.1%} below 90% for {component['source_city_name']}")
                if page == 1:
                    preflights.append({"source_city_id": observed_id, "source_city_name": observed_name,
                                       "sample_size": len(rows), "match_pct": round(ratio * 100, 2), "pass": True})
                fingerprint = hashlib.sha256("\n".join(sorted(r["link_key"] for r in rows)).encode()).hexdigest()
                if not rows or fingerprint in seen_fingerprints:
                    break
                seen_fingerprints.add(fingerprint)
                for row in rows:
                    try:
                        row["source_url"] = trusted_url(row["source_url"])
                    except ValueError as exc:
                        self._quarantine({"stage": "page", "url": "[REDACTED_FOREIGN_URL]",
                            "reason": str(exc), "at": now()})
                        continue
                    component_rows.setdefault(row["link_key"], row)
                page += 1
                self._write_checkpoint(f"pages-{slug}", {"next_page": page, "fingerprints": sorted(seen_fingerprints),
                    "expected_total": expected_total, "records": list(component_rows.values()), "updated_at": now()})
                if self.options.sample and page > self.options.sample:
                    break
                if expected_total and len(component_rows) >= expected_total:
                    break
                time.sleep(self.options.sleep)
            for key, row in component_rows.items():
                all_rows.setdefault(key, row)
        rows = list(all_rows.values())
        atomic_json(contained(self.root, "discovered_links.json"), rows)
        return rows, preflights

    def stage2(self, discovered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checkpoint = self._checkpoint("details")
        completed = set(checkpoint.get("completed", []))
        detail_rows = {r["source_url"]: r for r in checkpoint.get("records", [])}
        processed_this_run = 0
        for index, listing in enumerate(discovered, 1):
            try:
                url = trusted_url(listing["source_url"])
            except (KeyError, TypeError, ValueError) as exc:
                reason = f"untrusted resumed detail URL: {exc}"
                self._quarantine({"stage": "detail", "url": "[REDACTED_FOREIGN_URL]", "reason": reason, "at": now()})
                self._failure("detail", reason)
                raise RuntimeError(reason) from exc
            if url in completed:
                continue
            if self.options.limit is not None and processed_this_run >= self.options.limit:
                break
            html, metadata = self.fetcher.get(url)
            self._save_raw("details", f"d{index:06d}", url, html, metadata)
            detail = parse_detail_page(html, url)
            if detail["challenge"]:
                self._quarantine({"stage": "detail", "url": url, "reason": "challenge_detected", "at": now()})
                self._failure("detail", "challenge_detected")
                raise RuntimeError("challenge detected during detail stage; stopped safely")
            if not detail.get("source_entity_id") or not detail.get("name"):
                self._quarantine({"stage": "detail", "url": url, "reason": "missing_identity", "at": now()})
            else:
                merged = {**listing, **{k: v for k, v in detail.items() if v is not None}}
                merged["canonical_city_id"] = self.city
                merged["budget_segment"] = budget_segment(merged.get("price_per_sqft_avg") or merged.get("price_per_sqft_min"))
                detail_rows[url] = merged
            completed.add(url)
            processed_this_run += 1
            self._write_checkpoint("details", {"completed": sorted(completed), "records": list(detail_rows.values()), "updated_at": now()})
            time.sleep(self.options.sleep)
        return list(detail_rows.values())

    def finalize(self, discovered: list[dict[str, Any]], details: list[dict[str, Any]], preflights: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = sorted((normalize_locality(self.city, row) for row in details),
                            key=lambda r: (str(r.get("source_city_id")), str(r.get("source_entity_id"))))
        validate_runtime_contracts(normalized)
        complete_urls = {r["source_url"] for r in normalized}
        missing = [r["source_url"] for r in discovered if canonical_url(r["source_url"]) not in complete_urls]
        atomic_json(contained(self.root, "normalized.json"), normalized)
        diagnostic = self.options.sample is not None or self.options.limit is not None
        manifest = {
            "status": ("diagnostic_complete" if diagnostic else
                       "complete" if not missing else "incomplete"),
            "production_complete": not diagnostic and not missing and len(normalized) == len(discovered),
            "diagnostic_limits": {"sample_pages": self.options.sample, "detail_limit": self.options.limit},
            "canonical_city_id": self.city, "source": "magicbricks_localities", "finished_at": now(),
            "source_components": [{k: c[k] for k in ("source_city_id", "source_city_name", "verified_url")} for c in self.components],
            "preflights": preflights, "discovered_total": len(discovered), "details_required": len(discovered),
            "details_completed": len(normalized), "details_missing": len(missing), "missing_urls": missing,
            "detail_completeness_pct": round(100 * len(normalized) / len(discovered), 2) if discovered else 0.0,
            "normalized_output": str(self.root / "normalized.json"),
        }
        atomic_json(contained(self.root, "manifest.json"), manifest)
        return manifest


def budget_segment(price: float | int | None) -> str | None:
    if price is None: return None
    if price < 5000: return "value"
    if price < 10000: return "mid_market"
    if price < 20000: return "premium"
    return "luxury"


def normalize_locality(city: str, row: dict[str, Any]) -> dict[str, Any]:
    source_id = str(row["source_entity_id"])
    lat, lon = row.get("latitude"), row.get("longitude")
    if (lat is None) != (lon is None):
        lat = lon = None
    scraped_at = row.get("scraped_at") or now()
    price = row.get("price_per_sqft_avg")
    if price is None:
        low, high = row.get("price_per_sqft_min"), row.get("price_per_sqft_max")
        price = (low + high) / 2 if low is not None and high is not None else low
    return {
        "canonical_city_id": city,
        "entity_id": f"{city}:locality:magicbricks:{source_id}",
        "entity_kind": "locality",
        "source": "magicbricks",
        "source_entity_id": source_id,
        "source_city_id": row.get("source_city_id"),
        "source_city_name": row.get("source_city_name"),
        "name": row["name"],
        "lat": lat,
        "lon": lon,
        "coordinate_source": "magicbricks_detail" if lat is not None else None,
        "coordinate_precision": "source_locality_centroid" if lat is not None else None,
        "source_url": trusted_url(row["source_url"]),
        "scraped_at": scraped_at,
        "schema_version": "1.0.0",
        "quality_flags": [],
        "lineage": {
            "collector": "collectors.magicbricks_localities",
            "listing_url": trusted_url(row.get("page_url") or row["source_url"]),
            "source_component": {"id": row.get("source_city_id"), "name": row.get("source_city_name")},
        },
        "price_per_sqft": price,
        "rating": row.get("rating"),
        "review_count": row.get("reviews"),
        "price_per_sqft_min": row.get("price_per_sqft_min"),
        "price_per_sqft_max": row.get("price_per_sqft_max"),
        "budget_segment": row.get("budget_segment") or budget_segment(price),
        "rank": row.get("rank"),
    }


def validate_runtime_contracts(records: list[dict[str, Any]]) -> None:
    from src.multicity.config import load_city_registry
    from src.multicity.validators import validate_entity

    repo = Path(__file__).resolve().parents[2]
    registry = load_city_registry(repo / "config/cities.yaml", repo / "config/source_city_registry.json")
    for record in records:
        validate_entity(record, "locality", registry)
        if record.get("entity_kind") != "locality": raise ValueError("entity_kind must be locality")
        if record.get("price_per_sqft") is not None and record["price_per_sqft"] < 0: raise ValueError("invalid price_per_sqft")
        if record.get("rating") is not None and record["rating"] < 0: raise ValueError("invalid rating")
        if record.get("review_count") is not None and (not isinstance(record["review_count"], int) or record["review_count"] < 0):
            raise ValueError("invalid review_count")
