"""Runtime validators for public multi-city contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .config import CityRegistry


class ContractError(ValueError):
    pass


ENTITY_TYPES = {"school", "project", "locality", "hospital"}


def _iso8601(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be an ISO-8601 string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 string") from exc


def validate_entity(record: Mapping[str, Any], entity_type: str, registry: CityRegistry) -> None:
    if entity_type not in ENTITY_TYPES:
        raise ContractError(f"unsupported entity type: {entity_type}")
    required = {"canonical_city_id", "entity_id", "source", "source_entity_id", "name",
                "source_url", "scraped_at", "schema_version", "quality_flags", "lineage"}
    missing = sorted(required - record.keys())
    if missing:
        raise ContractError(f"missing required fields: {', '.join(missing)}")
    city_id = record["canonical_city_id"]
    registry.require_city(city_id)
    prefix = f"{city_id}:{entity_type}:{record['source']}:"
    if not isinstance(record["entity_id"], str) or not record["entity_id"].startswith(prefix):
        raise ContractError("entity_id does not match canonical namespace")
    if not isinstance(record["lineage"], Mapping) or not record["lineage"]:
        raise ContractError("lineage must be a non-empty object")
    if not isinstance(record["quality_flags"], list):
        raise ContractError("quality_flags must be an array")
    lat, lon = record.get("lat"), record.get("lon")
    if (lat is None) != (lon is None):
        raise ContractError("lat and lon must both be null or both be present")
    if lat is not None and (not isinstance(lat, (int, float)) or not -90 <= lat <= 90):
        raise ContractError("lat is outside valid range")
    if lon is not None and (not isinstance(lon, (int, float)) or not -180 <= lon <= 180):
        raise ContractError("lon is outside valid range")
    _iso8601(record["scraped_at"], "scraped_at")


def validate_city_summary(summary: Mapping[str, Any], registry: CityRegistry) -> None:
    required = {"canonical_city_id", "schema_version", "admission_status", "as_of", "metrics", "lineage"}
    missing = sorted(required - summary.keys())
    if missing:
        raise ContractError(f"missing required fields: {', '.join(missing)}")
    registry.require_city(summary["canonical_city_id"])
    if summary["admission_status"] not in {"admitted", "pending", "rejected"}:
        raise ContractError("invalid admission_status")
    if not isinstance(summary["lineage"], Mapping) or not summary["lineage"]:
        raise ContractError("lineage must be a non-empty object")
    if not isinstance(summary["metrics"], Mapping):
        raise ContractError("metrics must be an object")
    _iso8601(summary["as_of"], "as_of")
    for metric_id, metric in summary["metrics"].items():
        if not isinstance(metric, Mapping) or "value" not in metric or "coverage_pct" not in metric:
            raise ContractError(f"metric {metric_id!r} lacks value or coverage_pct")
        coverage = metric["coverage_pct"]
        if coverage is not None and (not isinstance(coverage, (int, float)) or not 0 <= coverage <= 100):
            raise ContractError(f"metric {metric_id!r} has invalid coverage_pct")
