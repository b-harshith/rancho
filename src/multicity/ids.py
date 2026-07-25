"""Stable namespaced identifiers; raw source identifiers are never guessed."""

from __future__ import annotations

import re

_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")


def canonical_entity_id(canonical_city_id: str, entity_type: str, source: str, source_id: str | int) -> str:
    parts = (canonical_city_id, entity_type, source, str(source_id))
    if any(not part or not _PART_RE.fullmatch(part) for part in parts):
        raise ValueError("ID parts must be non-empty URL-safe tokens without ':' or path separators")
    return ":".join(parts)
