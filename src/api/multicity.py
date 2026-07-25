"""Read-only API for generated multi-city decision artifacts.

The API intentionally serves precomputed evidence rather than calculating market
metrics at request time.  Fee bands are categorical because the source data has
no comparable annual-fee values.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

try:
    from portal_auth import is_authorized
except ImportError:  # pragma: no cover - package import in tests/tooling
    from src.portal_auth import is_authorized


SCHEMA_VERSION = "1.0.0"
SERVER_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DATA_DIR = SERVER_DIR / "public" / "data" / "multicity"
RUNTIME_DATA_DIR = SERVER_DIR / "runtime_data" / "multicity"
DATA_DIR = (
    PUBLIC_DATA_DIR
    if (PUBLIC_DATA_DIR / "manifest.json").is_file()
    else RUNTIME_DATA_DIR
)

CANONICAL_CITIES = frozenset({"bengaluru", "delhi_ncr", "mumbai", "hyderabad"})
LEGACY_DEEP_DIVE_CITY = "bengaluru"
CATEGORY_IDS = frozenset(
    {
        "super_premium", "premium", "affordable", "budget",
        "premium_plus", "affordable_plus", "all_private",
    }
)
FORBIDDEN_FEE_PARAMETERS = frozenset(
    {
        "fee", "fees", "annual_fee", "fee_threshold", "fee_thresholds",
        "custom_fee", "custom_threshold", "min_fee", "max_fee",
    }
)


class ApiError(ValueError):
    status_code = 400
    code = "invalid_request"


class ArtifactNotFound(ApiError):
    status_code = 404
    code = "artifact_not_found"


def error_payload(exc: Exception) -> dict:
    return {
        "status": "error",
        "schema_version": SCHEMA_VERSION,
        "error": {"code": getattr(exc, "code", "internal_error"), "message": str(exc)},
    }


def _single(params: dict, key: str, default=None):
    value = params.get(key, [default])
    if isinstance(value, (list, tuple)):
        if len(value) > 1:
            raise ApiError(f"{key} must be supplied once")
        return value[0] if value else default
    return value


def validate_params(params: dict) -> None:
    lowered = {str(key).lower() for key in params}
    forbidden = sorted(
        key for key in lowered
        if key in FORBIDDEN_FEE_PARAMETERS or "fee" in key or "threshold" in key
    )
    if forbidden:
        raise ApiError(
            "Custom fee thresholds are unavailable; use one of the canonical category IDs"
        )


def validate_city(value, *, required=True):
    if value in (None, ""):
        if required:
            raise ApiError("city is required")
        return None
    city = str(value).strip()
    if city not in CANONICAL_CITIES:
        raise ApiError(f"Unknown canonical city ID: {city}")
    return city


def validate_category(value, *, required=True):
    if value in (None, ""):
        if required:
            raise ApiError("category is required")
        return None
    category = str(value).strip()
    if category not in CATEGORY_IDS:
        raise ApiError(f"Unknown category ID: {category}")
    return category


def _read_json(path: Path, *, root=None, expected_sha256=None):
    root = Path(root or DATA_DIR)
    try:
        # Every candidate path is constructed from validated constants, but keep
        # this containment check as a second line of defence.
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ApiError("Invalid artifact path") from exc
    if not path.is_file():
        raise ArtifactNotFound(f"Generated artifact is unavailable: {path.name}")
    if expected_sha256:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise RuntimeError(f"Generated artifact failed integrity check: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read generated artifact: {path.name}") from exc


def load_manifest(data_dir=None):
    root = Path(data_dir or DATA_DIR)
    return _read_json(root / "manifest.json", root=root)


def _manifest_artifact(manifest: dict, *keys, root=None):
    """Return a safe manifest-declared relative path when one is present."""
    node = manifest.get("artifacts", manifest)
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if isinstance(node, dict):
        node = node.get("path") or node.get("file")
    if not isinstance(node, str) or not node.strip():
        return None
    root = Path(root or DATA_DIR)
    candidate = (root / node).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError("Manifest contains an unsafe artifact path") from exc
    return candidate


def _manifest_artifact_hash(manifest: dict, *keys):
    node = manifest.get("artifacts", manifest)
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if not isinstance(node, dict):
        return None
    value = node.get("sha256")
    return value if isinstance(value, str) and len(value) == 64 else None


def _first_existing(*paths):
    for path in paths:
        if path is not None and path.is_file():
            return path
    return next((path for path in paths if path is not None), None)


def _declared_comparison_path(manifest, root):
    value = manifest.get("city_comparison_path") if isinstance(manifest, dict) else None
    if not isinstance(value, str):
        return None
    return _safe_declared_path(value, root)


def _declared_city_path(manifest, city, root):
    catalog = manifest.get("cities") if isinstance(manifest, dict) else None
    if not isinstance(catalog, list):
        return None
    for item in catalog:
        if isinstance(item, dict) and item.get("canonical_city_id") == city:
            value = item.get("detail_path")
            return _safe_declared_path(value, root) if isinstance(value, str) else None
    return None


def _safe_declared_path(value, root):
    candidate = (Path(root) / value).resolve()
    try:
        candidate.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise RuntimeError("Manifest contains an unsafe artifact path") from exc
    return candidate


def get_summaries(*, category=None, data_dir=None):
    """Load the city comparison artifact, optionally selecting a scenario."""
    root = Path(data_dir or DATA_DIR)
    category = validate_category(category, required=False)
    manifest = _read_json(root / "manifest.json", root=root)
    if category:
        path = _first_existing(
            _manifest_artifact(manifest, "scenarios", category, root=root),
            root / "scenarios" / f"{category}.json",
        )
        if path is not None and path.is_file():
            return _read_json(path, root=root)
    declared_summary = _manifest_artifact(manifest, "summary", root=root)
    declared_comparison = _manifest_artifact(manifest, "comparison", root=root)
    path = _first_existing(
        declared_summary,
        declared_comparison,
        _declared_comparison_path(manifest, root),
        root / "city_comparison.json",
        root / "summary.json",
        root / "city_summaries.json",
    )
    expected_hash = None
    if path == declared_summary:
        expected_hash = _manifest_artifact_hash(manifest, "summary")
    elif path == declared_comparison:
        expected_hash = _manifest_artifact_hash(manifest, "comparison")
    comparison = _read_json(path, root=root, expected_sha256=expected_hash)
    if not category:
        return comparison
    return _project_category(comparison, category)


def _project_category(comparison, category):
    """Select a generated category from a comparison without recomputing it."""
    if not isinstance(comparison, dict):
        raise RuntimeError("City comparison artifact must be an object")
    source_rows = comparison.get("cities")
    row_key = "cities"
    if not isinstance(source_rows, list):
        source_rows = comparison.get("rows")
        row_key = "rows"
    if not isinstance(source_rows, list):
        raise RuntimeError("City comparison artifact has no city rows")

    rows = []
    for source in source_rows:
        if not isinstance(source, dict):
            continue
        category_metrics = source.get("category_metrics")
        if not isinstance(category_metrics, dict) or category not in category_metrics:
            raise ArtifactNotFound(f"Category scenario {category} is incomplete")
        identity = {
            key: value for key, value in source.items()
            if key not in {"category_metrics"}
        }
        identity["category_id"] = category
        identity["metrics"] = category_metrics[category]
        rows.append(identity)
    return {
        "schema_version": comparison.get("schema_version", SCHEMA_VERSION),
        "methodology_version": comparison.get("methodology_version"),
        "category_id": category,
        row_key: rows,
        "lineage": comparison.get("lineage"),
    }


def get_city_detail(city, *, category=None, data_dir=None):
    root = Path(data_dir or DATA_DIR)
    city = validate_city(city)
    category = validate_category(category, required=False)
    manifest = _read_json(root / "manifest.json", root=root)
    declared_city = _manifest_artifact(manifest, "cities", city, root=root)
    path = _first_existing(
        declared_city,
        _declared_city_path(manifest, city, root),
        root / "cities" / f"{city}.json",
    )
    detail = _read_json(
        path,
        root=root,
        expected_sha256=(
            _manifest_artifact_hash(manifest, "cities", city)
            if path == declared_city else None
        ),
    )
    artifact_city = detail.get("canonical_city_id") if isinstance(detail, dict) else None
    if artifact_city is not None and artifact_city != city:
        raise RuntimeError("City artifact does not match its canonical city ID")
    if not category:
        return detail

    # Prefer a complete generated category view embedded in the city detail.
    scenarios = detail.get("category_metrics") if isinstance(detail, dict) else None
    if not isinstance(scenarios, dict):
        scenarios = detail.get("scenarios") if isinstance(detail, dict) else None
    if isinstance(scenarios, dict) and category in scenarios:
        return {
            "schema_version": detail.get("schema_version", SCHEMA_VERSION),
            "methodology_version": detail.get("methodology_version"),
            "canonical_city_id": city,
            "category_id": category,
            "data": scenarios[category],
            "lineage": detail.get("lineage"),
        }
    raise ArtifactNotFound(f"Category scenario {category} is unavailable for {city}")


def get_hexes(city, *, category=None, data_dir=None):
    root = Path(data_dir or DATA_DIR)
    city = validate_city(city)
    category = validate_category(category, required=False)
    manifest = _read_json(root / "manifest.json", root=root)
    if category:
        declared = _manifest_artifact(manifest, "category_hexes", city, category, root=root)
        path = _first_existing(declared, root / "hexes" / f"{city}__{category}.geojson")
        expected_hash = (
            _manifest_artifact_hash(manifest, "category_hexes", city, category)
            if path == declared else None
        )
    else:
        declared = _manifest_artifact(manifest, "hexes", city, root=root)
        path = _first_existing(declared, root / "hexes" / f"{city}.geojson")
        expected_hash = (
            _manifest_artifact_hash(manifest, "hexes", city)
            if path == declared else None
        )
    payload = _read_json(path, root=root, expected_sha256=expected_hash)
    artifact_city = payload.get("canonical_city_id") if isinstance(payload, dict) else None
    if artifact_city is not None and artifact_city != city:
        raise RuntimeError("Hex artifact does not match its canonical city ID")
    artifact_category = payload.get("category_id") if isinstance(payload, dict) else None
    if category and artifact_category is not None and artifact_category != category:
        raise RuntimeError("Hex artifact does not match its category ID")
    return payload


def get_score(*, category=None, data_dir=None):
    root = Path(data_dir or DATA_DIR)
    category = validate_category(category, required=False)
    manifest = _read_json(root / "manifest.json", root=root)
    declared = _manifest_artifact(manifest, "score", root=root)
    path = _first_existing(declared, root / "score_model.json")
    payload = _read_json(
        path,
        root=root,
        expected_sha256=(
            _manifest_artifact_hash(manifest, "score") if path == declared else None
        ),
    )
    if category:
        categories = payload.get("categories") if isinstance(payload, dict) else None
        if not isinstance(categories, dict) or category not in categories:
            raise ArtifactNotFound(f"Score scenario {category} is unavailable")
        return {
            "schema_version": payload.get("schema_version", SCHEMA_VERSION),
            "methodology_version": payload.get("methodology_version"),
            "generated_at": payload.get("generated_at"),
            "model": payload.get("model"),
            "category_id": category,
            "score": categories[category],
        }
    return payload


def get_legacy_status(city=None, *, data_dir=None):
    manifest = load_manifest(data_dir=data_dir)
    city = validate_city(city, required=False)
    city_ids = [
        item.get("canonical_city_id")
        for item in manifest.get("cities", [])
        if isinstance(item, dict) and item.get("canonical_city_id") in CANONICAL_CITIES
    ]
    city_ids = city_ids or sorted(CANONICAL_CITIES)

    def status_for(city_id):
        has_legacy_deep_dive = city_id in city_ids
        warnings = []
        return {
            "canonical_city_id": city_id,
            "multicity_portal_path": f"/?city={city_id}",
            "legacy_deep_dive": {
                "available": has_legacy_deep_dive,
                "path": f"/bangalore?city={city_id}" if has_legacy_deep_dive else None,
                "label": (
                    f"{city_id.replace('_', ' ').title()} full market deep dive"
                ),
            },
            "legacy_catchment_api": {
                "available": has_legacy_deep_dive,
                "path": f"/api/catchment?city={city_id}" if has_legacy_deep_dive else None,
                "default_city_id": city_id,
            },
            "warnings": warnings,
        }

    if city:
        return status_for(city)
    return {
        "schema_version": manifest.get("schema_version", SCHEMA_VERSION),
        "methodology_version": manifest.get("methodology_version"),
        "supported_city_ids": city_ids,
        "legacy_deep_dive_city_id": LEGACY_DEEP_DIVE_CITY,
        "legacy_deep_dive_city_ids": city_ids,
        "cities": [status_for(city_id) for city_id in city_ids],
    }


def dispatch(params: dict, *, data_dir=None):
    """Pure request dispatcher used by both the Vercel handler and unit tests."""
    validate_params(params)
    action = str(_single(params, "action", "summaries") or "summaries").strip()
    category = _single(params, "category")
    if action in {"summaries", "summary", "scenario"}:
        if action == "scenario" and category in (None, ""):
            raise ApiError("category is required")
        return get_summaries(category=category, data_dir=data_dir)
    if action in {"city", "detail"}:
        return get_city_detail(_single(params, "city"), category=category, data_dir=data_dir)
    if action in {"hexes", "hex"}:
        return get_hexes(_single(params, "city"), category=category, data_dir=data_dir)
    if action == "score":
        return get_score(category=category, data_dir=data_dir)
    if action in {"legacy", "legacy_status", "portal"}:
        if category not in (None, ""):
            raise ApiError("legacy status does not accept category")
        return get_legacy_status(_single(params, "city"), data_dir=data_dir)
    if action == "manifest":
        if category not in (None, "") or _single(params, "city") not in (None, ""):
            raise ApiError("manifest does not accept city or category")
        return load_manifest(data_dir=data_dir)
    raise ApiError(f"Unknown action: {action}")


def static_artifact_location(params: dict) -> str | None:
    """Return the authenticated static route for a large API artifact.

    Serverless Python bundles retain only the compact API indexes.  City-detail
    and H3 payloads are served by Vercel's static layer, behind the same signed
    session middleware, so the browser downloads each large artifact only once.
    """
    validate_params(params)
    action = str(_single(params, "action", "summaries") or "summaries").strip()
    category = validate_category(_single(params, "category"), required=False)
    if action in {"city", "detail"}:
        city = validate_city(_single(params, "city"))
        return f"/data/multicity/cities/{city}.json"
    if action in {"hexes", "hex"}:
        city = validate_city(_single(params, "city"))
        suffix = f"__{category}" if category else ""
        return f"/data/multicity/hexes/{city}{suffix}.geojson"
    return None


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        if not is_authorized(self.headers):
            self.send_json(
                {"status": "error", "error": {"code": "authentication_required"}},
                401,
            )
            return
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            result = dispatch(params)
            self.send_json({"status": "success", "data": result})
        except ArtifactNotFound as exc:
            location = static_artifact_location(params)
            if location:
                self.send_response(307)
                self.send_header("Location", location)
                self.send_header("Cache-Control", "private, no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
            self.send_json(error_payload(exc), exc.status_code)
        except ApiError as exc:
            self.send_json(error_payload(exc), exc.status_code)
        except Exception as exc:  # pragma: no cover - transport safety net
            self.send_json(error_payload(exc), 500)

    def do_POST(self):
        if not is_authorized(self.headers):
            self.send_json(
                {"status": "error", "error": {"code": "authentication_required"}},
                401,
            )
            return
        exc = ApiError("Multi-city artifacts are read-only; use GET")
        self.send_json(error_payload(exc), 405)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
