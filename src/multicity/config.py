"""Strict, dependency-free loader for the canonical city registries."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


CITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ConfigError(ValueError):
    """Raised when city configuration is malformed or inconsistent."""


@dataclass(frozen=True)
class CityConfig:
    canonical_city_id: str
    display_name: str
    status: str


@dataclass(frozen=True)
class CityRegistry:
    schema_version: str
    processing_order: tuple[str, ...]
    cities: Mapping[str, CityConfig]
    source_mappings: Mapping[str, Mapping[str, Any]]

    def require_city(self, canonical_city_id: str) -> CityConfig:
        try:
            return self.cities[canonical_city_id]
        except KeyError as exc:
            raise ConfigError(f"unknown canonical_city_id: {canonical_city_id!r}") from exc

    def require_verified_source(self, canonical_city_id: str, source: str) -> Mapping[str, Any]:
        self.require_city(canonical_city_id)
        mapping = self.source_mappings[canonical_city_id].get(source)
        if not isinstance(mapping, Mapping) or not mapping.get("verified_url"):
            raise ConfigError(f"source mapping is not verified: {canonical_city_id}/{source}")
        return mapping


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_cities_yaml(text: str) -> tuple[str, tuple[str, ...], dict[str, CityConfig]]:
    version_match = re.search(r"(?m)^schema_version:\s*(.+?)\s*$", text)
    order_match = re.search(r"(?m)^processing_order:\s*\[([^]]*)\]\s*$", text)
    if not version_match or not order_match:
        raise ConfigError("cities.yaml is missing schema_version or processing_order")
    version = _scalar(version_match.group(1))
    order = tuple(item.strip() for item in order_match.group(1).split(",") if item.strip())
    starts = list(re.finditer(r"(?m)^  - canonical_city_id:\s*(\S+)\s*$", text))
    cities: dict[str, CityConfig] = {}
    for index, match in enumerate(starts):
        city_id = _scalar(match.group(1))
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.end():end]
        display = re.search(r"(?m)^    display_name:\s*(.+?)\s*$", block)
        status = re.search(r"(?m)^    status:\s*(.+?)\s*$", block)
        if not display or not status:
            raise ConfigError(f"city {city_id!r} is missing display_name or status")
        if not CITY_ID_RE.fullmatch(city_id) or city_id in cities:
            raise ConfigError(f"invalid or duplicate canonical_city_id: {city_id!r}")
        cities[city_id] = CityConfig(city_id, _scalar(display.group(1)), _scalar(status.group(1)))
    if not cities or set(order) != set(cities) or len(order) != len(cities):
        raise ConfigError("processing_order must contain every configured city exactly once")
    return version, order, cities


def load_city_registry(cities_path: str | Path, source_registry_path: str | Path) -> CityRegistry:
    cities_file, source_file = Path(cities_path), Path(source_registry_path)
    version, order, cities = _parse_cities_yaml(cities_file.read_text(encoding="utf-8"))
    try:
        source_doc = json.loads(source_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid source registry JSON: {exc}") from exc
    if source_doc.get("schema_version") != version:
        raise ConfigError("city and source registry schema versions differ")
    mappings = source_doc.get("cities")
    if not isinstance(mappings, dict) or set(mappings) != set(cities):
        raise ConfigError("source registry city set differs from cities.yaml")
    for city_id, mapping in mappings.items():
        if not isinstance(mapping, dict):
            raise ConfigError(f"source mappings for {city_id!r} must be an object")
    return CityRegistry(version, order, cities, mappings)
