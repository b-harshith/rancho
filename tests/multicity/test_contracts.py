import json
import tempfile
import unittest
from pathlib import Path

from src.multicity.config import ConfigError, load_city_registry
from src.multicity.ids import canonical_entity_id
from src.multicity.paths import city_partition_path
from src.multicity.validators import ContractError, validate_entity


ROOT = Path(__file__).resolve().parents[2]


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_city_registry(ROOT / "config/cities.yaml", ROOT / "config/source_city_registry.json")

    def test_registry_loads_and_unknown_city_is_rejected(self):
        self.assertEqual(self.registry.processing_order[0], "bengaluru")
        with self.assertRaises(ConfigError):
            self.registry.require_city("not_a_city")

    def test_registry_versions_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sources.json"
            document = json.loads((ROOT / "config/source_city_registry.json").read_text())
            document["schema_version"] = "9.9.9"
            source.write_text(json.dumps(document))
            with self.assertRaises(ConfigError):
                load_city_registry(ROOT / "config/cities.yaml", source)

    def test_namespaced_ids_do_not_collide_across_cities(self):
        first = canonical_entity_id("bengaluru", "school", "yellowslate", "shared-42")
        second = canonical_entity_id("hyderabad", "school", "yellowslate", "shared-42")
        self.assertNotEqual(first, second)
        with self.assertRaises(ValueError):
            canonical_entity_id("hyderabad", "school", "yellowslate", "../escape")

    def test_two_city_fixture_validates_without_collision(self):
        records = json.loads((ROOT / "tests/multicity/fixtures/two_city_entities.json").read_text())
        for record in records:
            validate_entity(record, "school", self.registry)
        self.assertEqual(len({record["entity_id"] for record in records}), 2)

    def test_lineage_and_namespace_are_mandatory(self):
        record = json.loads((ROOT / "tests/multicity/fixtures/two_city_entities.json").read_text())[0]
        record["lineage"] = {}
        with self.assertRaises(ContractError):
            validate_entity(record, "school", self.registry)

    def test_city_partition_cannot_leak(self):
        expected = Path("/tmp/data/cities/hyderabad/normalized/schools.json").resolve()
        self.assertEqual(city_partition_path("/tmp/data", self.registry, "hyderabad", "normalized", "schools.json"), expected)
        for unsafe in ("../bengaluru/schools.json", "/tmp/leak.json", "..\\bengaluru"):
            with self.assertRaises(ValueError):
                city_partition_path("/tmp/data", self.registry, "hyderabad", "normalized", unsafe)


if __name__ == "__main__":
    unittest.main()
