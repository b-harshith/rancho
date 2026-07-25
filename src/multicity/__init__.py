"""Canonical contracts and utilities for the multi-city pipeline."""

from .config import CityConfig, CityRegistry, ConfigError, load_city_registry
from .ids import canonical_entity_id
from .paths import city_partition_path

__all__ = [
    "CityConfig",
    "CityRegistry",
    "ConfigError",
    "canonical_entity_id",
    "city_partition_path",
    "load_city_registry",
]
