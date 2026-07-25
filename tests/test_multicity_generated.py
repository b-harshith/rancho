import hashlib
import json
import unittest
from pathlib import Path

from src.api.multicity import ApiError, dispatch
from src.build_multicity_platform import CITY_COORDINATE_WINDOWS, school_category_metrics


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/public/data/multicity"


class GeneratedMulticityArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((DATA / "manifest.json").read_text())
        cls.comparison = dispatch({"action": ["summaries"]}, data_dir=DATA)

    def test_manifest_artifact_paths_and_hashes(self):
        artifacts = self.manifest["artifacts"]
        records = []

        def collect(node):
            if isinstance(node, dict) and {"path", "bytes", "sha256"} <= set(node):
                records.append(node)
                return
            if isinstance(node, dict):
                for value in node.values():
                    collect(value)

        collect(artifacts)
        for record in records:
            with self.subTest(path=record["path"]):
                path = (DATA / record["path"]).resolve()
                path.relative_to(DATA.resolve())
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_size, record["bytes"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["sha256"])

    def test_manifest_exposes_v3_map_and_score_contracts(self):
        self.assertEqual(self.manifest["schema_version"], "multicity-platform-v3")
        self.assertEqual(self.manifest["map_defaults"]["benchmark_city_id"], "delhi_ncr")
        self.assertEqual(self.manifest["map_defaults"]["selectable_city_ids"], [
            "delhi_ncr", "bengaluru", "hyderabad", "mumbai",
        ])
        self.assertEqual(self.manifest["scoring_model"]["weights"], {
            "school_demand": 0.55,
            "premium_concentration": 0.15,
            "residential_market_depth": 0.15,
            "office_anchor_depth": 0.10,
            "health_locality_confidence": 0.05,
        })
        self.assertFalse(self.manifest["constraints"]["custom_annual_fee_filter_supported"])
        self.assertFalse(self.manifest["constraints"]["modeled_enrollment_in_primary_rankings"])

    def test_category_hex_geojson_matches_occupied_h3_cells(self):
        for item in self.manifest["cities"]:
            city = item["canonical_city_id"]
            detail = dispatch({"action": ["city"], "city": [city]}, data_dir=DATA)
            cells = detail["geographies"]["h3_cells"]
            for category in self.manifest["categories"]:
                category_id = category["id"]
                expected = sum(
                    1 for cell in cells
                    if (cell["category_metrics"][category_id]["reported_students_grade_2_9"] or 0) > 0
                )
                payload = dispatch(
                    {"action": ["hexes"], "city": [city], "category": [category_id]},
                    data_dir=DATA,
                )
                with self.subTest(city=city, category=category_id):
                    self.assertEqual(payload["type"], "FeatureCollection")
                    self.assertEqual(payload["canonical_city_id"], city)
                    self.assertEqual(payload["category_id"], category_id)
                    self.assertEqual(len(payload["features"]), expected)
                    for feature in payload["features"][:10]:
                        self.assertEqual(feature["geometry"]["type"], "Polygon")
                        self.assertIn("context", feature["properties"])
                        self.assertIn("projects", feature["properties"]["context"])
                        self.assertIn("offices", feature["properties"]["context"])
                        self.assertIn("category_scores", feature["properties"])
                        self.assertIn(category_id, feature["properties"]["category_scores"])
                        self.assertIn(
                            "weighted_score",
                            feature["properties"]["category_scores"][category_id],
                        )

    def test_category_rollups_reconcile(self):
        for city in self.comparison["cities"]:
            metrics = city["category_metrics"]
            with self.subTest(city=city["canonical_city_id"]):
                for field in (
                    "school_count", "students_grade_2_9", "reported_enrollment_total",
                    "reported_students_grade_2_9", "modeled_students_grade_2_9",
                ):
                    singles = [metrics[tier][field] for tier in ("super_premium", "premium", "affordable", "budget")]
                    expected = None if all(value is None for value in singles) else sum(value or 0 for value in singles)
                    self.assertEqual(metrics["all_private"][field], expected)
                    self.assertEqual(
                        metrics["premium_plus"][field],
                        None if all(value is None for value in singles[:2]) else sum(value or 0 for value in singles[:2]),
                    )
                    self.assertEqual(
                        metrics["affordable_plus"][field],
                        None if all(value is None for value in singles[:3]) else sum(value or 0 for value in singles[:3]),
                    )

    def test_source_rows_reconcile_without_city_leakage(self):
        for layer in ("schools", "projects", "hospitals", "localities", "offices"):
            admitted = sum(
                city["category_metrics"]["all_private"]["school_count"]
                if layer == "schools" else (
                    city["context_layers"][layer]["source_listing_count"]
                    if layer == "projects" else city["context_layers"][layer]["record_count"]
                )
                for city in self.comparison["cities"]
            )
            excluded = sum(self.manifest["excluded_source_city_labels"][layer].values())
            self.assertEqual(
                admitted + excluded,
                self.manifest["source_provenance"][layer]["row_count"],
                layer,
            )

    def test_api_actions_work_on_every_generated_city_and_category(self):
        for item in self.manifest["cities"]:
            city = item["canonical_city_id"]
            detail = dispatch({"action": ["city"], "city": [city]}, data_dir=DATA)
            self.assertEqual(detail["canonical_city_id"], city)
            for category in self.manifest["categories"]:
                category_id = category["id"]
                projected = dispatch(
                    {"action": ["city"], "city": [city], "category": [category_id]},
                    data_dir=DATA,
                )
                self.assertEqual(projected["category_id"], category_id)

    def test_api_score_model_covers_every_generated_category(self):
        score = dispatch({"action": ["score"]}, data_dir=DATA)
        self.assertEqual(score["model"]["id"], self.manifest["scoring_model"]["id"])
        self.assertEqual(set(score["categories"]), {category["id"] for category in self.manifest["categories"]})
        for category in self.manifest["categories"]:
            category_id = category["id"]
            projected = dispatch({"action": ["score"], "category": [category_id]}, data_dir=DATA)
            with self.subTest(category=category_id):
                self.assertEqual(projected["category_id"], category_id)
                self.assertEqual(projected["score"]["category_id"], category_id)
                self.assertEqual(
                    {row["canonical_city_id"] for row in projected["score"]["cities"]},
                    {"delhi_ncr", "bengaluru", "hyderabad", "mumbai"},
                )

    def test_h3_geojson_is_polygonal_and_reconciles_to_spatial_metrics(self):
        for item in self.manifest["cities"]:
            city = item["canonical_city_id"]
            detail = dispatch({"action": ["city"], "city": [city]}, data_dir=DATA)
            full_hexes = dispatch({"action": ["hexes"], "city": [city]}, data_dir=DATA)
            with self.subTest(city=city, layer="full"):
                self.assertEqual(full_hexes["type"], "FeatureCollection")
                self.assertGreater(len(full_hexes["features"]), 0)
                self.assertTrue(
                    all(feature["geometry"]["type"] == "Polygon" for feature in full_hexes["features"])
                )
                self.assertTrue(
                    any(
                        feature["properties"]["context"]["projects"]["project_count"]
                        or feature["properties"]["context"]["offices"]["office_count"]
                        or feature["properties"]["context"]["hospitals"]["hospital_count"]
                        or feature["properties"]["context"]["localities"]["locality_record_count"]
                        for feature in full_hexes["features"]
                    )
                )
                self.assertTrue(
                    any(
                        feature["properties"]["category_scores"]["premium_plus"]["weighted_score"] is not None
                        for feature in full_hexes["features"]
                    )
                )
                self.assertTrue(
                    all(
                        feature["properties"].get("neighborhood_name")
                        and feature["properties"].get("neighborhood_name_source")
                        and feature["properties"].get("neighborhood_name_confidence")
                        in {"high", "medium", "low"}
                        for feature in full_hexes["features"]
                    )
                )
                self.assertTrue(
                    all(row.get("label") and row["label"] != row["id"] for row in detail["geographies"]["h3_cells"])
                )
                enriched_h3_rows = [
                    row for row in detail["geographies"]["h3_cells"]
                    if row.get("category_scores", {}).get("premium_plus", {}).get("weighted_score") is not None
                ]
                self.assertTrue(enriched_h3_rows)
                self.assertIn("projects", enriched_h3_rows[0]["context"])
            for category in self.manifest["categories"]:
                category_id = category["id"]
                category_hexes = dispatch(
                    {"action": ["hexes"], "city": [city], "category": [category_id]},
                    data_dir=DATA,
                )
                with self.subTest(city=city, category=category_id):
                    expected = detail["spatial_concentration"][category_id]["occupied_h3_res7_cells"]
                    self.assertEqual(len(category_hexes["features"]), expected)
                    self.assertTrue(
                        all(feature["geometry"]["type"] == "Polygon" for feature in category_hexes["features"])
                    )

    def test_map_bounds_are_city_scoped_after_coordinate_cleanup(self):
        for item in self.manifest["cities"]:
            city = item["canonical_city_id"]
            detail = dispatch({"action": ["city"], "city": [city]}, data_dir=DATA)
            bounds = detail["map"]["bounds"]
            window = CITY_COORDINATE_WINDOWS[city]
            with self.subTest(city=city, field="bounds"):
                self.assertIsNotNone(bounds)
                self.assertGreaterEqual(bounds["south"], window["south"])
                self.assertGreaterEqual(bounds["west"], window["west"])
                self.assertLessEqual(bounds["north"], window["north"])
                self.assertLessEqual(bounds["east"], window["east"])
            context = detail["context_layers"]
            for layer, summary in context.items():
                with self.subTest(city=city, layer=layer):
                    self.assertGreaterEqual(summary["raw_coordinate_count"], summary["coordinate_count"])
            if any((summary.get("out_of_market_coordinate_count") or 0) > 0 for summary in context.values()):
                self.assertIn(
                    "out_of_market_coordinates_excluded_from_map",
                    detail["quality"]["warnings"],
                )

    def test_fee_and_threshold_parameters_are_rejected_on_generated_data(self):
        for key in ("annual_fee", "custom_annual_fee", "price_threshold", "feeBand"):
            with self.subTest(key=key), self.assertRaises(ApiError):
                dispatch({"action": ["summaries"], key: ["100000"]}, data_dir=DATA)

    def test_unknown_enrollment_is_not_converted_to_zero(self):
        result = school_category_metrics([
            {
                "enrollment_grade_2_9": "",
                "enrollment_total": "",
                "enrollment_source": "",
                "latitude": "",
                "longitude": "",
            }
        ])
        self.assertIsNone(result["students_grade_2_9"])
        self.assertIsNone(result["enrollment_total"])
        self.assertIsNone(result["reported_enrollment_total"])
        self.assertIsNone(result["reported_students_grade_2_9"])
        empty = school_category_metrics([])
        self.assertEqual(empty["students_grade_2_9"], 0)

    def test_primary_evidence_and_decision_support_are_explicit(self):
        expected_ranks = {"mumbai": 1, "bengaluru": 2, "hyderabad": 3}
        for city in self.comparison["cities"]:
            city_id = city["canonical_city_id"]
            metrics = city["category_metrics"]["premium_plus"]
            score = city["expansion_scores"]["premium_plus"]
            detail = dispatch({"action": ["city"], "city": [city_id]}, data_dir=DATA)
            with self.subTest(city=city_id):
                self.assertEqual(metrics["primary_evidence_metric"], "reported_enrollment_total")
                self.assertGreater(metrics["reported_enrollment_total"], 0)
                self.assertGreater(metrics["reported_students_grade_2_9"], 0)
                self.assertGreaterEqual(metrics["modeled_students_grade_2_9"], 0)
                self.assertEqual(score.get("candidate_rank"), expected_ranks.get(city_id))
                projects = city["context_layers"]["projects"]
                self.assertEqual(projects["record_count"], projects["canonical_project_count"])
                self.assertGreaterEqual(projects["canonical_project_count"], projects["source_project_id_count"])
                support = detail["decision_support"]
                self.assertTrue(support["priority_school_partners"])
                self.assertTrue(support["residential_project_targets"])
                self.assertTrue(support["candidate_catchments"])
                self.assertEqual(
                    [row["capture_rate_pct"] for row in support["campus_scenarios"]],
                    [1, 2, 3],
                )
                self.assertTrue(all(row["seats_per_campus"] == 200 for row in support["campus_scenarios"]))
                self.assertTrue(all(row["target_utilization"] == 0.8 for row in support["campus_scenarios"]))

    def test_source_dates_are_unknown_without_invention(self):
        for metadata in self.manifest["source_provenance"].values():
            self.assertIsNone(metadata["source_observation_as_of"])
            self.assertIsNone(metadata["academic_year"])


if __name__ == "__main__":
    unittest.main()
