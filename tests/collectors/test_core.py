import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, RefResolver

from collectors.adapters import SOURCE_ENTITY_TYPE, extract_records, normalize
from collectors.cli import main
from collectors.core import Layout, SafetyError, validate_preflight
from src.multicity.config import load_city_registry
from src.multicity.validators import validate_entity


CITY = {"canonical_city_id": "hyderabad", "display_name": "Hyderabad",
        "aliases": ["Hyderabad", "Secunderabad"]}
ROOT = Path(__file__).resolve().parents[2]


class CollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_city_registry(ROOT / "config/cities.yaml", ROOT / "config/source_city_registry.json")

    def test_preflight_requires_ninety_percent(self):
        rows = [{"address": "Hyderabad"}] * 9 + [{"address": "Mumbai"}]
        self.assertEqual(validate_preflight(rows, CITY)["match_pct"], 90.0)
        with self.assertRaises(SafetyError):
            validate_preflight(rows[:-1] + [{"address": "Mumbai"}, {"address": "Mumbai"}], CITY)

    def test_repeated_bengaluru_guard(self):
        with self.assertRaisesRegex(SafetyError, "Bengaluru"):
            validate_preflight([{"address": "Hyderabad", "cityId": 3327}], CITY)

    def test_all_redacted_parser_fixtures(self):
        root = Path(__file__).parent / "fixtures"
        for source in ("yellowslate", "magicbricks", "99acres", "practo", "udise"):
            payload = json.loads((root / f"{source}_hyderabad.json").read_text())
            records = extract_records(source, payload)
            self.assertEqual(len(records), 1)
            mapping = {"city_id": "verified-hyd", "city_name": "Hyderabad"}
            row = normalize(source, "hyderabad", mapping, records[0])
            entity_type = SOURCE_ENTITY_TYPE[source]
            self.assertTrue(row["entity_id"].startswith(f"hyderabad:{entity_type}:{source}:"))
            self.assertEqual(len(row["lineage"]["raw_payload_hash"]), 64)
            self.assertEqual(
                set(row["lineage"]),
                {"raw_payload_hash", "scraper_version", "normalization_version", "source_observation"},
            )
            validate_entity(row, entity_type, self.registry)

            schema_dir = ROOT / "schemas/multicity/v1"
            schema = json.loads((schema_dir / f"{entity_type}.schema.json").read_text())
            common = json.loads((schema_dir / "common_entity.schema.json").read_text())
            resolver = RefResolver(base_uri=schema_dir.as_uri() + "/", referrer=schema,
                                   store={common["$id"]: common,
                                          schema_dir.joinpath("common_entity.schema.json").as_uri(): common})
            Draft202012Validator(schema, resolver=resolver,
                                  format_checker=FormatChecker()).validate(row)

    def test_layout_is_city_partitioned(self):
        layout = Layout(Path("data/cities"), "hyderabad", "practo")
        expected = (Path.cwd() / "data/cities/hyderabad/raw/practo/records.jsonl").resolve()
        self.assertEqual(layout.raw, expected)

    def test_layout_rejects_city_and_source_path_injection(self):
        for city in ("../hyderabad", "/tmp/hyderabad", "foo/bar", "foo\\bar"):
            with self.subTest(city=city), self.assertRaises(SafetyError):
                Layout(Path("data/cities"), city, "practo")
        for source in ("../practo", "/tmp/practo", "foo/bar", "foo\\bar"):
            with self.subTest(source=source), self.assertRaises(SafetyError):
                Layout(Path("data/cities"), "hyderabad", source)

    def test_source_record_id_rejects_path_injection(self):
        mapping = {"city_id": "verified-hyd", "city_name": "Hyderabad"}
        for source_id in ("../escape", "/tmp/escape", "foo/bar", "foo\\bar"):
            record = {"psmid": source_id, "projectName": "Fixture Project",
                      "ctname": "Hyderabad", "projectUrl": "https://example.invalid/project"}
            with self.subTest(source_id=source_id), self.assertRaises(SafetyError):
                normalize("magicbricks", "hyderabad", mapping, record)

    def test_cli_fails_closed_on_unknown_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            config.write_text(json.dumps({"cities": {"hyderabad": {"magicbricks": None}}}))
            code = main(["magicbricks", "--city", "hyderabad", "--config", str(config),
                         "--output-root", temp, "--dry-run"])
            self.assertEqual(code, 2)

    def test_fixture_run_is_atomic_and_resume_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.json"
            config.write_text(json.dumps({"cities": [{
                **CITY,
                "source_mappings": {"magicbricks": {"city_id": "verified-hyd",
                    "city_name": "Hyderabad", "verified_url": "https://example.invalid/verified"}}
            }]}))
            fixture = Path(__file__).parent / "fixtures" / "magicbricks_hyderabad.json"
            args = ["magicbricks", "--city", "hyderabad", "--config", str(config),
                    "--output-root", temp, "--fixture", str(fixture)]
            self.assertEqual(main(args), 0)
            raw = Path(temp) / "hyderabad/raw/magicbricks/records.jsonl"
            self.assertEqual(len(raw.read_text().splitlines()), 1)
            self.assertEqual(main(args + ["--resume"]), 0)
            self.assertEqual(len(raw.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
