import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from collectors.ezyschooling.collector import CollectionFailure, normalize_school, parse_detail_document, parse_page_payload, persist_failure, validate_normalized, verified_mapping
from pipelines.schools.merge import geocode_records, haversine_km, reconcile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "collectors" / "fixtures"


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.payload).encode()


class EzyschoolingTests(unittest.TestCase):
    def normalized_fixture(self):
        page = json.loads((FIXTURES / "ezyschooling_page_delhi_ncr.json").read_text())
        detail_fixture = json.loads((FIXTURES / "ezyschooling_detail_delhi_ncr.json").read_text())
        rows, total = parse_page_payload(page)
        detail = parse_detail_document(detail_fixture["html"], detail_fixture["url"])
        detail["_raw_sha256"] = "detailhash"; rows[0]["_page_raw_sha256"] = "pagehash"
        return total, normalize_school(rows[0], detail, "delhi_ncr", "2026-06-30T00:00:00Z")

    def test_runtime_and_school_schema_validation(self):
        total, result = self.normalized_fixture()
        self.assertEqual(total, 2)
        self.assertEqual(result["entity_id"], "delhi_ncr:school:ezyschooling:101")
        self.assertEqual((result["annual_fee_min"], result["annual_fee_max"]), (120000, 144000))
        validate_normalized([result], "delhi_ncr", ROOT / "config" / "cities.yaml")

    def test_challenge_evidence_and_failed_manifest_are_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failure = CollectionFailure("challenge page detected: captcha", stage="detail", source_url="https://example.invalid/school/a", body_sha256="abc", challenge="captcha")
            persist_failure(root, failure)
            manifest = json.loads((root / "manifests" / "ezyschooling_run.json").read_text())
            evidence = json.loads((root / manifest["failure_evidence"]).read_text())
            self.assertEqual(manifest["status"], "FAILED_QUARANTINED")
            self.assertTrue(manifest["challenge_detected"])
            self.assertEqual(evidence["body_sha256"], "abc")

    def test_unverified_mapping_remains_blocked(self):
        with self.assertRaisesRegex(ValueError, "unverified"):
            verified_mapping({"source_mappings": {"ezyschooling": {"city_slug": "do-not-trust"}}})

    def test_google_cache_expiration_redaction_and_bounds(self):
        now = datetime(2026, 6, 30, tzinfo=timezone.utc)
        query = "Alpha, Delhi, delhi_ncr, India"
        import hashlib
        key = hashlib.sha256(query.casefold().encode()).hexdigest()
        stale_other_key = hashlib.sha256(b"unrelated stale query").hexdigest()
        stale = {key: {"status": "OK", "lat": 1, "lon": 1, "fetched_at": (now - timedelta(days=30)).isoformat(), "query": query, "url": "secret"}, stale_other_key: {"status": "ZERO_RESULTS", "lat": None, "lon": None, "fetched_at": (now - timedelta(days=30)).isoformat()}, "api-key": {"key": "secret"}}
        payload = {"status": "OK", "results": [{"place_id": "p1", "geometry": {"location": {"lat": 28.6, "lng": 77.2}, "location_type": "ROOFTOP"}}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "runtime-secret"}):
            cache = Path(directory) / "cache.json"; cache.write_text(json.dumps(stale))
            rows = [{"name": "Alpha", "address": "Delhi", "canonical_city_id": "delhi_ncr", "lat": None, "lon": None, "quality_flags": []}]
            geocode_records(rows, cache, [76.8, 28.3, 77.5, 29.0], 1, None, opener=lambda *a, **k: FakeResponse(payload), now=now)
            saved_text = cache.read_text(); saved = json.loads(saved_text)
            self.assertEqual(rows[0]["coordinate_precision"], "ROOFTOP")
            self.assertNotIn("query", saved[key]); self.assertNotIn("url", saved[key]); self.assertNotIn("runtime-secret", saved_text); self.assertNotIn("api-key", saved)
            self.assertNotIn(stale_other_key, saved)

            outside = [{"name": "Beta", "address": "Delhi", "canonical_city_id": "delhi_ncr", "lat": None, "lon": None, "quality_flags": []}]
            out_payload = {"status": "OK", "results": [{"place_id": "p2", "geometry": {"location": {"lat": 19.0, "lng": 72.8}, "location_type": "APPROXIMATE"}}]}
            geocode_records(outside, cache, [76.8, 28.3, 77.5, 29.0], 1, None, opener=lambda *a, **k: FakeResponse(out_payload), now=now)
            self.assertIsNone(outside[0]["lat"]); self.assertIn("geocode_out_of_bounds", outside[0]["quality_flags"])

    def test_one_to_one_merge_collision_is_review_only(self):
        primary = [{"source": "ezyschooling", "source_entity_id": x, "name": "North Star School", "lat": 28.5355, "lon": 77.391, "pincode": "201301"} for x in ("e1", "e2")]
        candidates = [{"source_entity_id": "y1", "name": "North Star School", "lat": 28.5355, "lon": 77.391, "pincode": "201301"}]
        decisions = reconcile(primary, candidates, "yellowslate")
        self.assertEqual({x["status"] for x in decisions}, {"collision_review"})
        self.assertEqual(haversine_km(28.5355, 77.391, 28.5355, 77.391), 0)


if __name__ == "__main__": unittest.main()
