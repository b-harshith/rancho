"""School address geocoding with SQLite query caching."""

from __future__ import annotations

import json
import sqlite3
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config import GEOCODE_CACHE_DB, LOGS_DIR, PipelineConfig
from src.progress import ProgressLogger

ssl._create_default_https_context = ssl._create_unverified_context

DELAYS = {"google": 0.05, "arcgis": 0.1, "osm": 1.0}


class GeocodeCache:
    def __init__(self, db_path: Path = GEOCODE_CACHE_DB):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS geocode_cache (
                query TEXT PRIMARY KEY,
                latitude REAL,
                longitude REAL,
                success INTEGER,
                timestamp TEXT
            )
        """)
        self.conn.commit()

    def get(self, query: str) -> tuple[float | None, float | None, bool]:
        q = query.strip().lower()
        row = self.conn.execute(
            "SELECT latitude, longitude, success FROM geocode_cache WHERE query=?", (q,)
        ).fetchone()
        if row:
            lat, lon, ok = row
            return (lat, lon, True) if ok else (None, None, True)
        return None, None, False

    def set(self, query: str, lat, lon, success: bool):
        q = query.strip().lower()
        self.conn.execute(
            "INSERT OR REPLACE INTO geocode_cache (query, latitude, longitude, success, timestamp) "
            "VALUES (?,?,?,?,?)",
            (q, lat, lon, 1 if success else 0, datetime.now().isoformat()),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


def _log_api(log_dir: Path, provider: str, query: str, response):
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "api_responses.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "provider": provider,
                "query": query,
                "response": response,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def query_google(query: str, api_key: str, log_dir: Path) -> tuple[float | None, float | None]:
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode(
        {"address": query, "key": api_key}
    )
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
        data = json.loads(r.read().decode())
    _log_api(log_dir, "Google Maps", query, data)
    if data.get("status") == "OK" and data.get("results"):
        loc = data["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    if data.get("status") == "OVER_QUERY_LIMIT":
        raise RuntimeError("Google Maps OVER_QUERY_LIMIT")
    return None, None


def query_osm(query: str, log_dir: Path) -> tuple[float | None, float | None]:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1}
    )
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "K12-Unified-Spatial-Pipeline/1.0")
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    _log_api(log_dir, "OpenStreetMap", query, data)
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None, None


def query_arcgis(query: str, log_dir: Path) -> tuple[float | None, float | None]:
    url = (
        "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
        "findAddressCandidates?"
        + urllib.parse.urlencode({"f": "json", "singleLine": query, "maxLocations": 1})
    )
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
        data = json.loads(r.read().decode())
    _log_api(log_dir, "ArcGIS", query, data)
    candidates = data.get("candidates") or []
    if candidates:
        loc = candidates[0]["location"]
        return float(loc["y"]), float(loc["x"])
    return None, None


def geocode_query(
    query: str,
    provider: str,
    api_key: str | None,
    log_dir: Path,
) -> tuple[float | None, float | None]:
    if provider == "google" and api_key:
        return query_google(query, api_key, log_dir)
    if provider == "osm":
        return query_osm(query, log_dir)
    lat, lon = query_arcgis(query, log_dir)
    if lat is not None:
        return lat, lon
    return query_osm(query, log_dir)


def _build_query(row: pd.Series, city: str) -> str:
    gq = str(row.get("Geocode_Query", "") or "")
    if gq and gq != "nan":
        return gq
    name = str(row.get("Name", ""))
    pin = str(row.get("Pincode", "") or "")
    if pin and pin != "nan":
        return f"{name} {pin} {city}".strip()
    return f"{name} {city}".strip()


def run_geocoding(
    df: pd.DataFrame,
    config: PipelineConfig,
    cache: GeocodeCache | None = None,
    log: ProgressLogger | None = None,
) -> pd.DataFrame:
    """Geocode schools in the DataFrame. Returns updated DataFrame."""
    log = log or ProgressLogger("Geocode")
    cache = cache or GeocodeCache()
    provider = config.default_provider()
    delay = DELAYS.get(provider, 0.1)
    log_dir = LOGS_DIR

    if "Latitude" not in df.columns:
        df["Latitude"] = None
    if "Longitude" not in df.columns:
        df["Longitude"] = None

    total = len(df)
    pending = df["Latitude"].isna().sum()
    log.stage("School Geocoding", f"{pending}/{total} to process via {provider}")

    stats = {"success": 0, "fail": 0, "cache_hit": 0, "api_query": 0}

    for idx, row in df.iterrows():
        if pd.notna(row.get("Latitude")) and pd.notna(row.get("Longitude")):
            continue

        code = str(row.get("School_Code", idx))
        name = str(row.get("Name", ""))
        query = _build_query(row, config.city)

        lat, lon, in_cache = cache.get(query)
        if in_cache:
            stats["cache_hit"] += 1
            if lat is not None:
                df.at[idx, "Latitude"] = lat
                df.at[idx, "Longitude"] = lon
                stats["success"] += 1
                log.event(code, name, "CACHED", f"({lat:.5f}, {lon:.5f})")
                continue

        time.sleep(delay)
        stats["api_query"] += 1
        try:
            lat, lon = geocode_query(query, provider, config.google_api_key, log_dir)
            if lat is not None:
                cache.set(query, lat, lon, True)
                df.at[idx, "Latitude"] = lat
                df.at[idx, "Longitude"] = lon
                stats["success"] += 1
                log.event(code, name, "SUCCESS", f"({lat:.5f}, {lon:.5f})")
                continue

            fallback = f"{name}, {config.city}"
            lat, lon = geocode_query(fallback, provider, config.google_api_key, log_dir)
            if lat is not None:
                cache.set(fallback, lat, lon, True)
                df.at[idx, "Latitude"] = lat
                df.at[idx, "Longitude"] = lon
                stats["success"] += 1
                log.event(code, name, "SUCCESS", f"fallback ({lat:.5f}, {lon:.5f})")
            else:
                cache.set(query, 0, 0, False)
                stats["fail"] += 1
                log.event(code, name, "FAIL", "No results")
        except Exception as exc:
            stats["fail"] += 1
            log.event(code, name, "ERROR", str(exc)[:60])

    log.success(
        f"Geocoding complete: {stats['success']} found, {stats['fail']} failed, "
        f"{stats['cache_hit']} cache hits, {stats['api_query']} API calls"
    )
    return df
