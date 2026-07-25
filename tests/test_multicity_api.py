import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.api.multicity import ApiError, ArtifactNotFound, dispatch


class MulticityApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        (self.data / "cities").mkdir()
        (self.data / "scenarios").mkdir()
        self._write(
            "cities/bengaluru.json",
            {
                "schema_version": "1.0.0",
                "canonical_city_id": "bengaluru",
                "confidence": None,
                "scenarios": {"super_premium": {"students": None, "schools": 12}},
                "lineage": None,
            },
        )
        self._write(
            "city_comparison.json",
            {
                "schema_version": "1.0.0",
                "methodology_version": "school-market-v1",
                "cities": [
                    {
                        "canonical_city_id": "bengaluru",
                        "category_metrics": {
                            "budget": {"students": None, "schools": 100},
                            "premium_plus": {"students": 42, "schools": 3},
                        },
                    }
                ],
                "lineage": None,
            },
        )
        self._write(
            "manifest.json",
            {
                "schema_version": "1.0.0",
                "city_comparison_path": "city_comparison.json",
                "cities": [
                    {"canonical_city_id": "bengaluru", "detail_path": "cities/bengaluru.json"},
                ],
                "artifacts": {
                    "hexes": {"bengaluru": {"path": "hexes/bengaluru.geojson"}},
                    "category_hexes": {
                        "bengaluru": {
                            "premium_plus": {"path": "hexes/bengaluru__premium_plus.geojson"}
                        }
                    },
                    "score": {"path": "score_model.json"},
                },
            },
        )
        self._write(
            "hexes/bengaluru.geojson",
            {"type": "FeatureCollection", "canonical_city_id": "bengaluru", "features": []},
        )
        self._write(
            "hexes/bengaluru__premium_plus.geojson",
            {
                "type": "FeatureCollection",
                "canonical_city_id": "bengaluru",
                "category_id": "premium_plus",
                "features": [{"type": "Feature", "properties": {"hex_id": "abc"}}],
            },
        )
        self._write(
            "score_model.json",
            {
                "schema_version": "1.0.0",
                "model": {"id": "school_led_expansion_fit_v2"},
                "categories": {
                    "premium_plus": {
                        "category_id": "premium_plus",
                        "cities": [{"canonical_city_id": "bengaluru", "weighted_score": 10}],
                    }
                },
            },
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, relative, value):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_summaries_preserve_nulls(self):
        result = dispatch({"action": ["summaries"]}, data_dir=self.data)
        self.assertIsNone(result["cities"][0]["category_metrics"]["budget"]["students"])

    def test_category_scenario_uses_only_canonical_category(self):
        result = dispatch(
            {"action": ["scenario"], "category": ["premium_plus"]}, data_dir=self.data
        )
        self.assertEqual(result["category_id"], "premium_plus")
        with self.assertRaises(ApiError):
            dispatch({"action": ["scenario"], "category": ["premium"]}, data_dir=self.data)

    def test_city_detail_validates_canonical_city(self):
        result = dispatch({"action": ["city"], "city": ["bengaluru"]}, data_dir=self.data)
        self.assertEqual(result["canonical_city_id"], "bengaluru")
        self.assertIsNone(result["confidence"])
        for invalid in ("pune", "Bengaluru", "../bengaluru", "bangalore", "chennai"):
            with self.assertRaises(ApiError):
                dispatch({"action": ["city"], "city": [invalid]}, data_dir=self.data)

    def test_embedded_city_category_scenario_preserves_nulls(self):
        result = dispatch(
            {"action": ["city"], "city": ["bengaluru"], "category": ["super_premium"]},
            data_dir=self.data,
        )
        self.assertEqual(result["category_id"], "super_premium")
        self.assertIsNone(result["data"]["students"])
        self.assertIsNone(result["lineage"])

    def test_custom_fee_inputs_are_always_rejected(self):
        for name in (
            "annual_fee", "fee_threshold", "custom_threshold", "min_fee",
            "custom_annual_fee_threshold",
        ):
            with self.subTest(name=name), self.assertRaises(ApiError):
                dispatch({"action": ["summaries"], name: ["200000"]}, data_dir=self.data)

    def test_category_can_be_projected_from_comparison_artifact(self):
        result = dispatch(
            {"action": ["scenario"], "category": ["budget"]}, data_dir=self.data
        )
        self.assertEqual(result["category_id"], "budget")
        self.assertIsNone(result["cities"][0]["metrics"]["students"])

    def test_missing_artifact_is_404_domain_error(self):
        with self.assertRaises(ArtifactNotFound) as context:
            dispatch({"action": ["city"], "city": ["mumbai"]}, data_dir=self.data)
        self.assertEqual(context.exception.status_code, 404)

    def test_unknown_action_and_repeated_values_are_rejected(self):
        with self.assertRaises(ApiError):
            dispatch({"action": ["delete"]}, data_dir=self.data)
        with self.assertRaises(ApiError):
            dispatch({"action": ["city"], "city": ["bengaluru", "mumbai"]}, data_dir=self.data)

    def test_manifest_path_traversal_is_rejected(self):
        manifest = json.loads((self.data / "manifest.json").read_text())
        manifest["city_comparison_path"] = "../secret.json"
        self._write("manifest.json", manifest)
        with self.assertRaises(RuntimeError):
            dispatch({"action": ["summaries"]}, data_dir=self.data)

    def test_manifest_declared_hash_is_enforced(self):
        path = self.data / "city_comparison.json"
        manifest = json.loads((self.data / "manifest.json").read_text())
        manifest["artifacts"] = {
            "comparison": {
                "path": "city_comparison.json",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        }
        self._write("manifest.json", manifest)
        dispatch({"action": ["summaries"]}, data_dir=self.data)
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            dispatch({"action": ["summaries"]}, data_dir=self.data)

    def test_hexes_action_serves_city_and_category_geojson(self):
        all_hexes = dispatch({"action": ["hexes"], "city": ["bengaluru"]}, data_dir=self.data)
        self.assertEqual(all_hexes["canonical_city_id"], "bengaluru")
        category_hexes = dispatch(
            {"action": ["hexes"], "city": ["bengaluru"], "category": ["premium_plus"]},
            data_dir=self.data,
        )
        self.assertEqual(category_hexes["category_id"], "premium_plus")
        self.assertEqual(category_hexes["features"][0]["properties"]["hex_id"], "abc")

    def test_score_action_serves_full_and_category_model(self):
        full = dispatch({"action": ["score"]}, data_dir=self.data)
        self.assertEqual(full["model"]["id"], "school_led_expansion_fit_v2")
        category = dispatch(
            {"action": ["score"], "category": ["premium_plus"]}, data_dir=self.data
        )
        self.assertEqual(category["category_id"], "premium_plus")
        self.assertEqual(category["score"]["cities"][0]["weighted_score"], 10)

    def test_legacy_status_is_city_scoped_and_read_only(self):
        all_status = dispatch({"action": ["legacy_status"]}, data_dir=self.data)
        self.assertEqual(all_status["legacy_deep_dive_city_id"], "bengaluru")
        bengaluru = dispatch(
            {"action": ["legacy_status"], "city": ["bengaluru"]},
            data_dir=self.data,
        )
        self.assertEqual(bengaluru["canonical_city_id"], "bengaluru")
        self.assertTrue(bengaluru["legacy_deep_dive"]["available"])
        self.assertEqual(bengaluru["legacy_deep_dive"]["path"], "/bangalore?city=bengaluru")
        self.assertEqual(bengaluru["legacy_catchment_api"]["default_city_id"], "bengaluru")
        with self.assertRaises(ApiError):
            dispatch(
                {"action": ["legacy_status"], "city": ["bengaluru"], "category": ["premium_plus"]},
                data_dir=self.data,
            )

    def test_hex_manifest_hash_is_enforced(self):
        path = self.data / "hexes" / "bengaluru__premium_plus.geojson"
        manifest = json.loads((self.data / "manifest.json").read_text())
        manifest["artifacts"]["category_hexes"]["bengaluru"]["premium_plus"]["sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        self._write("manifest.json", manifest)
        dispatch(
            {"action": ["hexes"], "city": ["bengaluru"], "category": ["premium_plus"]},
            data_dir=self.data,
        )
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            dispatch(
                {"action": ["hexes"], "city": ["bengaluru"], "category": ["premium_plus"]},
                data_dir=self.data,
            )


if __name__ == "__main__":
    unittest.main()
