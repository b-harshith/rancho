"""City-partition path construction with traversal and cross-city guards."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .config import CityRegistry

ALLOWED_LAYERS = frozenset({"raw", "normalized", "derived", "audits"})


def city_partition_path(data_root: str | Path, registry: CityRegistry, canonical_city_id: str,
                        layer: str, *parts: str) -> Path:
    registry.require_city(canonical_city_id)
    if layer not in ALLOWED_LAYERS:
        raise ValueError(f"unsupported city data layer: {layer!r}")
    for part in parts:
        parsed = PurePosixPath(part)
        if parsed.is_absolute() or ".." in parsed.parts or "\\" in part:
            raise ValueError(f"unsafe city path component: {part!r}")
    root = Path(data_root).resolve()
    partition = (root / "cities" / canonical_city_id).resolve()
    candidate = (partition / layer).joinpath(*parts).resolve()
    if candidate != partition and partition not in candidate.parents:
        raise ValueError("path escapes canonical city partition")
    return candidate
