from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0.0"
NORMALIZATION_VERSION = "1.0.0"
KNOWN_BENGALURU_MARKERS = {"bangalore", "bengaluru", "3327", "20_location"}
SECRET_KEYS = re.compile(r"cookie|token|authorization|captcha|password|secret", re.I)
SAFE_PART = re.compile(r"^[a-z][a-z0-9_]*$")
SAFE_SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")


class SafetyError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SafetyError("YAML config requires PyYAML; JSON configs work with stdlib only") from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SafetyError("config root must be an object")
    return data


def resolve_city(config: dict[str, Any], city_id: str) -> dict[str, Any]:
    cities = config.get("cities")
    if isinstance(cities, dict):
        # source_city_registry.json is source-centric; retain city id for diagnostics.
        if city_id not in cities:
            raise SafetyError(f"unknown canonical city: {city_id}")
        return {"canonical_city_id": city_id, "source_mappings": cities[city_id]}
    for city in cities or []:
        if city.get("canonical_city_id") == city_id:
            return city
    raise SafetyError(f"unknown canonical city: {city_id}")


def mapping_for(city: dict[str, Any], source: str) -> dict[str, Any]:
    mapping = (city.get("source_mappings") or {}).get(source)
    if not isinstance(mapping, dict):
        raise SafetyError(f"{source} mapping is unverified/missing")
    return mapping


def require_verified_mapping(city: dict[str, Any], source: str) -> dict[str, Any]:
    mapping = mapping_for(city, source)
    if not mapping.get("verified_url"):
        raise SafetyError(f"{source} mapping has no verified_url; refusing to guess")
    required = {
        "yellowslate": ("city_id", "city_name", "city_slug"),
        "magicbricks": ("city_id", "city_name"),
        "99acres": ("city_id", "city_name", "review_url"),
        "practo": ("city_slug",),
    }.get(source, ())
    missing = [key for key in required if mapping.get(key) in (None, "")]
    if missing:
        raise SafetyError(f"{source} verified mapping lacks: {', '.join(missing)}")
    return mapping


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if SECRET_KEYS.search(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def raw_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()


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


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(redact(row), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
        handle.flush()
        os.fsync(handle.fileno())
    return count


@dataclass
class Layout:
    root: Path
    city: str
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            self.root = Path(self.root)
        if not SAFE_PART.fullmatch(self.city):
            raise SafetyError("city must be a canonical identifier without path separators")
        if not SAFE_SOURCE.fullmatch(self.source):
            raise SafetyError("source must be a safe token without path separators")

    def _within(self, base: Path, *parts: str) -> Path:
        resolved_base = base.expanduser().resolve()
        candidate = resolved_base.joinpath(*parts).resolve()
        if candidate != resolved_base and resolved_base not in candidate.parents:
            raise SafetyError("resolved output path escapes its city partition")
        return candidate

    @property
    def city_root(self) -> Path:
        root = self.root.expanduser().resolve()
        return root if root.name == self.city else self._within(root, self.city)

    @property
    def raw(self) -> Path:
        return self._within(self.city_root, "raw", self.source, "records.jsonl")

    @property
    def normalized(self) -> Path:
        return self._within(self.city_root, "normalized", f"{self.source}.json")

    @property
    def checkpoint(self) -> Path:
        return self._within(self.city_root, "checkpoints", f"{self.source}.json")

    @property
    def manifest(self) -> Path:
        return self._within(self.city_root, "manifests", f"{self.source}.json")

    @property
    def quarantine(self) -> Path:
        return self._within(self.city_root, "quarantine", f"{self.source}.jsonl")


@dataclass
class Manifest:
    city: str
    source: str
    dry_run: bool
    started_at: str = field(default_factory=utc_now)
    pages_attempted: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    http_status_distribution: dict[str, int] = field(default_factory=dict)
    records_raw: int = 0
    records_unique: int = 0
    records_normalized: int = 0
    records_rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "finished_at": utc_now(), "schema_version": SCHEMA_VERSION}


def lineage(city: str, entity_type: str, source: str, record_id: str, source_city_id: Any,
            source_city_name: Any, source_url: Any, payload: Any) -> dict[str, Any]:
    from src.multicity.ids import canonical_entity_id

    return {
        "canonical_city_id": city,
        "entity_id": canonical_entity_id(city, entity_type, source, record_id),
        "source": source,
        "source_entity_id": str(record_id),
        "source_city_id": None if source_city_id is None else str(source_city_id),
        "source_city_name": source_city_name,
        "source_url": source_url,
        "scraped_at": utc_now(),
        "schema_version": SCHEMA_VERSION,
        "quality_flags": [],
        "lineage": {
            "raw_payload_hash": raw_hash(payload),
            "scraper_version": "collectors/0.1.0",
            "normalization_version": NORMALIZATION_VERSION,
            "source_observation": {
                "source_city_id": None if source_city_id is None else str(source_city_id),
                "source_city_name": source_city_name,
                "source_url": source_url,
            },
        },
    }


def text_city_match(record: dict[str, Any], aliases: list[str]) -> bool:
    haystack = " ".join(str(record.get(k) or "") for k in
                        ("source_city_name", "city", "cityName", "ctname", "address", "locality", "source_url"))
    folded = haystack.casefold()
    return any(alias.casefold() in folded for alias in aliases)


def validate_preflight(records: list[dict[str, Any]], city: dict[str, Any], threshold: float = .90) -> dict[str, Any]:
    if not records:
        raise SafetyError("preflight sample is empty")
    aliases = [city.get("display_name", ""), *(city.get("aliases") or [])]
    aliases = [a for a in aliases if a]
    matches = sum(text_city_match(r, aliases) for r in records)
    ratio = matches / len(records)
    target = city["canonical_city_id"]
    foreign_bengaluru = target != "bengaluru" and any(
        marker in json.dumps(r, sort_keys=True).casefold()
        for r in records for marker in KNOWN_BENGALURU_MARKERS
    )
    result = {"sample_size": len(records), "matches": matches, "match_pct": round(ratio * 100, 2),
              "threshold_pct": threshold * 100, "repeated_bengaluru_guard": not foreign_bengaluru}
    if ratio < threshold:
        raise SafetyError(f"preflight city match {ratio:.1%} is below {threshold:.0%}")
    if foreign_bengaluru:
        raise SafetyError("preflight contains known Bengaluru marker for a different city")
    return result
