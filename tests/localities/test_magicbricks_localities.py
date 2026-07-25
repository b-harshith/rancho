import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from collectors.magicbricks_localities.collector import (
    Collector, Options, budget_segment, contained, normalize_locality, trusted_url,
    validate_runtime_contracts,
)
from collectors.magicbricks_localities.parser import is_challenge, parse_detail_page, parse_listing_page


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "collectors" / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def listing(city="New delhi", city_id="2624", total=2, links=None):
    links = links or [
        ("https://www.magicbricks.com/A-in-New-Delhi-Overview", "A, New delhi"),
        ("https://www.magicbricks.com/B-in-New-Delhi-Overview", "B, New delhi"),
    ]
    cards = "".join(f'<div class="loc-card"><a class="loc-card__title" href="{u}">{n}</a> ₹5,000 4.0 2 reviews</div>' for u, n in links)
    return f'<span id="domcache_locality_detail" data-cityname="{city}" data-cityid="{city_id}" data-totallocality="{total}" data-currentpage="1"></span>{cards}'


def detail(name, locid):
    return f'<span id="domcache_locality_detail" data-cityid="2624" data-locid="{locid}" data-locname="{name}" data-cityname="New Delhi" data-latitude="28.5" data-longitude="77.2" data-lmtavgprice="5000"></span>{name} is rated as 4.0/5 basis 2 reviews'


class FakeFetcher:
    def __init__(self, responses): self.responses = responses; self.calls = []
    def get(self, url):
        self.calls.append(url)
        return self.responses[url], {"status": 200, "content_type": "text/html"}


class MagicBricksLocalitiesTests(unittest.TestCase):
    def test_listing_parser_enumerates_links_and_lineage(self):
        data = fixture("magicbricks_localities_listing.json")
        parsed = parse_listing_page(data["html"], data["url"])
        self.assertEqual(parsed["source_city_id"], "2624")
        self.assertEqual(len(parsed["records"]), 2)
        first = parsed["records"][0]
        self.assertEqual(first["source_url"], "https://www.magicbricks.com/Saket-in-New-Delhi-Overview")
        self.assertEqual(first["price_per_sqft_max"], 102778)
        self.assertEqual(first["rating"], 4.3)
        self.assertEqual(first["reviews"], 605)

    def test_detail_parser_and_runtime_contract(self):
        data = fixture("magicbricks_localities_detail.json")
        parsed = parse_detail_page(data["html"], data["url"])
        row = normalize_locality("delhi_ncr", parsed)
        validate_runtime_contracts([row])
        self.assertEqual(row["entity_id"], "delhi_ncr:locality:magicbricks:78191")
        self.assertEqual(row["entity_kind"], "locality")
        self.assertEqual(row["lat"], 28.523548126220703)
        self.assertEqual(row["price_per_sqft"], 25615.0)
        self.assertEqual(row["review_count"], 523)

    def test_all_five_verified_mappings(self):
        config = json.loads((ROOT / "collectors/magicbricks_localities/delhi_ncr.example.json").read_text())
        observed = {(x["source_city_name"], x["source_city_id"]) for x in config["cities"]["delhi_ncr"]["components"]}
        self.assertEqual(observed, {("New delhi", "2624"), ("Noida", "6403"), ("Gurgaon", "2951"),
                                    ("Ghaziabad", "6146"), ("Faridabad", "2944")})

    def test_preflight_evidence_hashes_resolve_to_retained_artifacts(self):
        evidence_root = ROOT / "collectors/magicbricks_localities/evidence"
        evidence = json.loads((evidence_root / "delhi_ncr_preflight_20260630.json").read_text())
        observations = [*evidence["components"], *evidence["sampled_details"]]
        self.assertEqual(len(observations), 10)
        for observation in observations:
            artifact = (evidence_root / observation["artifact_path"]).resolve()
            self.assertIn(evidence_root.resolve(), artifact.parents)
            self.assertTrue(artifact.is_file())
            self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), observation["artifact_sha256"])

    def test_limit_preserves_page_to_detail_accounting(self):
        component = {"source_city_id": "2624", "source_city_name": "New delhi",
                     "verified_url": "https://www.magicbricks.com/localities-in-new-delhi",
                     "pagination_url": "https://www.magicbricks.com/mbutility/localitySearchPage?page={page}&cityName={city_name}"}
        responses = {component["verified_url"]: listing(),
                     "https://www.magicbricks.com/A-in-New-Delhi-Overview": detail("A", "1")}
        with tempfile.TemporaryDirectory() as tmp:
            result = Collector("delhi_ncr", {"components": [component]},
                Options(Path(tmp), sleep=0, retries=0, limit=1), FakeFetcher(responses)).run()
        self.assertEqual(result["discovered_total"], 2)
        self.assertEqual(result["details_required"], 2)
        self.assertEqual(result["details_completed"], 1)
        self.assertEqual(result["details_missing"], 1)
        self.assertFalse(result["production_complete"])
        self.assertEqual(result["status"], "diagnostic_complete")

    def test_repeated_page_stops_enumeration(self):
        first = "https://www.magicbricks.com/localities-in-new-delhi"
        second = "https://www.magicbricks.com/mbutility/localitySearchPage?page=2&cityName=New+delhi"
        comp = {"source_city_id": "2624", "source_city_name": "New delhi", "verified_url": first,
                "pagination_url": "https://www.magicbricks.com/mbutility/localitySearchPage?page={page}&cityName={city_name}"}
        html = listing(total=99, links=[("https://www.magicbricks.com/A-in-New-Delhi-Overview", "A, New delhi")])
        fake = FakeFetcher({first: html, second: html})
        with tempfile.TemporaryDirectory() as tmp:
            collector = Collector("delhi_ncr", {"components": [comp]}, Options(Path(tmp), sleep=0), fake)
            rows, _ = collector.stage1()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(fake.calls), 2)

    def test_challenge_quarantine(self):
        comp = {"source_city_id": "2624", "source_city_name": "New delhi",
                "verified_url": "https://www.magicbricks.com/localities-in-new-delhi",
                "pagination_url": "https://www.magicbricks.com/mbutility/localitySearchPage?page={page}&cityName={city_name}"}
        with tempfile.TemporaryDirectory() as tmp:
            collector = Collector("delhi_ncr", {"components": [comp]}, Options(Path(tmp)),
                                  FakeFetcher({comp["verified_url"]: "Access Denied"}))
            with self.assertRaises(RuntimeError): collector.stage1()
            self.assertIn("challenge_detected", collector.quarantine.read_text())

    def test_traversal_and_foreign_urls_rejected(self):
        for url in ("https://evil.example/locality", "https://www.magicbricks.com/a/%2e%2e/b",
                    "http://www.magicbricks.com/locality"):
            with self.assertRaises(ValueError): trusted_url(url)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): Collector("../escape", {"components": [{}]}, Options(Path(tmp)))
            with self.assertRaises(ValueError): contained(Path(tmp), "..", "escape")
            bad = {"components": [{"source_city_id": "1", "source_city_name": "X",
                    "verified_url": "https://evil.example/localities", "pagination_url": "https://www.magicbricks.com/x?page={page}&city={city_name}"}]}
            with self.assertRaises(ValueError): Collector("delhi_ncr", bad, Options(Path(tmp)))

    def test_untrusted_component_ids_never_reach_paths(self):
        template = {"source_city_name": "X", "verified_url": "https://www.magicbricks.com/localities-in-x",
                    "pagination_url": "https://www.magicbricks.com/x?page={page}&city={city_name}"}
        for value in ("../../../../escape", "%2e%2e%2fescape", "/tmp/escape", "C:\\escape", "a\\..\\escape"):
            bad = {"components": [{**template, "source_city_id": value}]}
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError, msg=value):
                    Collector("delhi_ncr", bad, Options(Path(tmp)))

    def test_resumed_foreign_detail_state_is_quarantined_and_failed(self):
        comp = {"source_city_id": "2624", "source_city_name": "New delhi",
                "verified_url": "https://www.magicbricks.com/localities-in-new-delhi",
                "pagination_url": "https://www.magicbricks.com/x?page={page}&city={city_name}"}
        with tempfile.TemporaryDirectory() as tmp:
            collector = Collector("delhi_ncr", {"components": [comp]}, Options(Path(tmp), resume=True), FakeFetcher({}))
            bad = [{"source_url": "https://evil.example/stolen", "link_key": "foreign"}]
            with self.assertRaises(RuntimeError): collector.stage2(bad)
            self.assertIn("REDACTED_FOREIGN_URL", collector.quarantine.read_text())
            manifest = json.loads((collector.root / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["failed_stage"], "detail")
            self.assertFalse(manifest["production_complete"])

    def test_foreign_discovered_link_is_quarantined(self):
        first = "https://www.magicbricks.com/localities-in-new-delhi"
        comp = {"source_city_id": "2624", "source_city_name": "New delhi", "verified_url": first,
                "pagination_url": "https://www.magicbricks.com/mbutility/localitySearchPage?page={page}&cityName={city_name}"}
        html = listing(total=1, links=[
            ("https://www.magicbricks.com/A-in-New-Delhi-Overview", "A, New delhi"),
            ("https://evil.example/B", "B, New delhi"),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            collector = Collector("delhi_ncr", {"components": [comp]}, Options(Path(tmp), sleep=0), FakeFetcher({first: html}))
            rows, _ = collector.stage1()
            self.assertEqual(len(rows), 1)
            self.assertIn("REDACTED_FOREIGN_URL", collector.quarantine.read_text())

    def test_challenge_and_budget_segments(self):
        self.assertTrue(is_challenge("<title>Access Denied</title>"))
        self.assertEqual([budget_segment(x) for x in (4500, 7500, 15000, 25000)],
                         ["value", "mid_market", "premium", "luxury"])


if __name__ == "__main__":
    unittest.main()
