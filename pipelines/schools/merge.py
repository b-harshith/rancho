#!/usr/bin/env python3
"""Conservative one-to-one reconciliation for Ezyschooling/YellowSlate/UDISE."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STOP = {"school", "the", "of", "and", "public", "private", "international", "academy", "high", "senior", "secondary"}


def atomic_json(path: Path, value: Any) -> None: 
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, indent=2, ensure_ascii=False, sort_keys=True); out.write("\n"); out.flush(); os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise


def normalized_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().casefold()
    return " ".join(x for x in re.findall(r"[a-z0-9]+", text) if x not in STOP)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _coord(row):
    try: return float(row["lat"]), float(row["lon"])
    except (KeyError, TypeError, ValueError): return None


def _pincode(row):
    value = str(row.get("pincode") or row.get("zipcode") or "")
    match = re.search(r"\b[1-9][0-9]{5}\b", value + " " + str(row.get("address") or ""))
    return match.group(0) if match else None


def evidence(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    ln, rn = normalized_name(left.get("name")), normalized_name(right.get("name") or right.get("school_name"))
    name_score = SequenceMatcher(None, ln, rn).ratio() if ln and rn else 0.0
    lc, rc = _coord(left), _coord(right)
    distance = haversine_km(*lc, *rc) if lc and rc else None
    pin_equal = bool(_pincode(left) and _pincode(left) == _pincode(right))
    udise_equal = bool(left.get("udise_code") and str(left.get("udise_code")) == str(right.get("udise_code")))
    return {"name_similarity": round(name_score, 6), "haversine_km": round(distance, 6) if distance is not None else None, "pincode_equal": pin_equal, "udise_equal": udise_equal}


def reconcile(primary: list[dict[str, Any]], candidates: list[dict[str, Any]], candidate_source: str) -> list[dict[str, Any]]:
    """Return decisions without mutating sources or forcing ambiguous matches."""
    proposals = []
    for li, left in enumerate(primary):
        ranked = []
        for ri, right in enumerate(candidates):
            ev = evidence(left, right)
            eligible = ev["udise_equal"] or (ev["name_similarity"] >= .92 and (ev["pincode_equal"] or ev["haversine_km"] is not None and ev["haversine_km"] <= 1.5))
            if eligible:
                score = 2.0 if ev["udise_equal"] else ev["name_similarity"] + (.15 if ev["pincode_equal"] else 0) + (.1 if ev["haversine_km"] is not None and ev["haversine_km"] <= .5 else 0)
                ranked.append((score, ri, ev))
        ranked.sort(key=lambda x: (-x[0], str(candidates[x[1]].get("source_entity_id") or candidates[x[1]].get("udise_code") or x[1])))
        if not ranked: proposals.append({"left": li, "status": "unmatched", "candidate_source": candidate_source, "evidence": []})
        elif len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .08: proposals.append({"left": li, "status": "ambiguous_review", "candidate_source": candidate_source, "evidence": [{"right": x[1], **x[2]} for x in ranked[:3]]})
        else: proposals.append({"left": li, "right": ranked[0][1], "score": round(ranked[0][0], 6), "status": "candidate", "candidate_source": candidate_source, "evidence": ranked[0][2]})
    # Enforce one-to-one: a right-side collision sends all contenders to review.
    reverse: dict[int, list[dict[str, Any]]] = {}
    for item in proposals:
        if item["status"] == "candidate": reverse.setdefault(item["right"], []).append(item)
    for group in reverse.values():
        if len(group) == 1: group[0]["status"] = "auto_matched"
        else:
            for item in group: item["status"] = "collision_review"
    result = []
    for item in proposals:
        left = primary[item.pop("left")]; ri = item.get("right")
        result.append({"primary_source": left.get("source"), "primary_source_entity_id": left.get("source_entity_id"), "candidate_source_entity_id": candidates[ri].get("source_entity_id") if ri is not None else None, **item})
    return result


def geocode_records(records: list[dict[str, Any]], cache_path: Path, bounds: list[float] | None, timeout: float, limit: int | None, *, opener=urlopen, now: datetime | None = None) -> list[dict[str, Any]]:
    """Google geocode only missing points; key stays in environment and never enters output."""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key: raise ValueError("GOOGLE_MAPS_API_KEY is required at runtime")
    now = now or datetime.now(timezone.utc); cutoff = now - timedelta(days=29)
    loaded = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    allowed_cache_fields = {"status", "lat", "lon", "precision", "place_id", "fetched_at"}
    cache = {}
    if isinstance(loaded, dict):
        for key, entry in loaded.items():
            if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(entry, dict):
                continue
            sanitized = {field: value for field, value in entry.items() if field in allowed_cache_fields}
            try:
                fetched_at = datetime.fromisoformat(sanitized["fetched_at"].replace("Z", "+00:00"))
                if fetched_at.tzinfo is None: fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            if fetched_at >= cutoff:
                cache[key] = sanitized
    if cache_path.exists() and cache != loaded:
        atomic_json(cache_path, cache)
    calls = 0
    for row in records:
        if _coord(row): continue
        query = ", ".join(str(x) for x in (row.get("name"), row.get("address"), row.get("pincode"), row.get("canonical_city_id"), "India") if x)
        key = hashlib.sha256(query.casefold().encode()).hexdigest()
        result = cache.get(key)
        try:
            cached_at = datetime.fromisoformat(result["fetched_at"].replace("Z", "+00:00")) if result is not None else None
            if cached_at is not None and cached_at.tzinfo is None: cached_at = cached_at.replace(tzinfo=timezone.utc)
            fresh = cached_at is not None and cached_at >= cutoff
        except (KeyError, TypeError, ValueError): fresh = False
        if not fresh: result = None
        if result is None and (limit is None or calls < limit):
            url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode({"address": query, "key": api_key})
            try:
                with opener(Request(url, headers={"User-Agent": "BangaloreRancho-research/1.0"}), timeout=timeout) as response: payload = json.load(response)
            except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
                row.setdefault("quality_flags", []).append("geocode_network_error"); continue
            calls += 1; status = payload.get("status")
            candidates = payload.get("results") or []; first = candidates[0] if status == "OK" and candidates else None
            result = {"status": status, "lat": first["geometry"]["location"]["lat"] if first else None, "lon": first["geometry"]["location"]["lng"] if first else None, "precision": first["geometry"].get("location_type") if first else None, "place_id": first.get("place_id") if first else None, "fetched_at": now.isoformat().replace("+00:00", "Z")}
            # Transient quota errors are intentionally not cached.
            if status != "OVER_QUERY_LIMIT":
                cache[key] = result; atomic_json(cache_path, cache)
        if result and result.get("status") == "OK" and result.get("lat") is not None:
            lat, lon = float(result["lat"]), float(result["lon"])
            in_bounds = not bounds or (bounds[1] <= lat <= bounds[3] and bounds[0] <= lon <= bounds[2])
            if in_bounds:
                row.update({"lat": lat, "lon": lon, "coordinate_source": "google_geocoding", "coordinate_precision": result.get("precision"), "google_place_id": result.get("place_id")})
            else: row.setdefault("quality_flags", []).append("geocode_out_of_bounds")
        elif result and result.get("status") in {"ZERO_RESULTS", "OVER_QUERY_LIMIT", "REQUEST_DENIED"}:
            row.setdefault("quality_flags", []).append(f"geocode_{result['status'].casefold()}")
    return records


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ezyschooling", required=True); p.add_argument("--candidate", required=True); p.add_argument("--candidate-source", choices=("yellowslate", "udise"), required=True); p.add_argument("--output", required=True)
    p.add_argument("--geocode-cache"); p.add_argument("--bounds", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH")); p.add_argument("--geocode-limit", type=int); p.add_argument("--timeout", type=float, default=20)
    args = p.parse_args(argv); primary = json.loads(Path(args.ezyschooling).read_text()); candidate = json.loads(Path(args.candidate).read_text())
    if isinstance(candidate, dict): candidate = candidate.get("schools") or candidate.get("records") or []
    if args.geocode_cache: primary = geocode_records(primary, Path(args.geocode_cache), args.bounds, args.timeout, args.geocode_limit)
    decisions = reconcile(primary, candidate, args.candidate_source)
    atomic_json(Path(args.output), {"match_policy": "one_to_one_evidence_no_forced_matches_v1", "distance_metric": "haversine", "decisions": decisions})
    return 0


if __name__ == "__main__": raise SystemExit(main())
