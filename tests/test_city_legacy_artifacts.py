import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.build_city_legacy_artifacts import SCHEMA_VERSION, TARGET_CITIES, build


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "final_data" / "multicity_source"


def tree_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


class CityLegacyArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DATA_ROOT.exists():
            raise unittest.SkipTest(f"Final data folder not available: {DATA_ROOT}")
        cls.tmp1 = tempfile.TemporaryDirectory()
        cls.tmp2 = tempfile.TemporaryDirectory()
        cls.out1 = Path(cls.tmp1.name) / "city_legacy"
        cls.out2 = Path(cls.tmp2.name) / "city_legacy"
        build(DATA_ROOT, cls.out1)
        build(DATA_ROOT, cls.out2)
        cls.manifest = json.loads((cls.out1 / "manifest.json").read_text())

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp1"):
            cls.tmp1.cleanup()
        if hasattr(cls, "tmp2"):
            cls.tmp2.cleanup()

    def test_rebuild_is_deterministic(self):
        self.assertEqual(tree_hashes(self.out1), tree_hashes(self.out2))

    def test_manifest_and_city_contracts(self):
        self.assertEqual(self.manifest["schema_version"], SCHEMA_VERSION)
        self.assertFalse(self.manifest["constraints"]["custom_annual_fee_filter_supported"])
        self.assertFalse(self.manifest["constraints"]["school_fee_amounts_available"])
        self.assertEqual({city["canonical_city_id"] for city in self.manifest["cities"]}, set(TARGET_CITIES))
        for city in self.manifest["cities"]:
            with self.subTest(city=city["canonical_city_id"]):
                for required in (
                    "hexes.geojson",
                    "hexes_master.json",
                    "client_summary.json",
                    "decision_support.json",
                    "report.json",
                    "zones.json",
                    "micromarket_suggestions_8hex.json",
                    "school_market_summary.json",
                    "localities.json",
                    "societies.json",
                    "hospitals.json",
                    "sez_offices.json",
                    "project_assets_by_quartile.json",
                    "school_entities.json",
                    "school_campuses.json",
                    "school_market_audit.json",
                    "q3_below_hex_counts.json",
                    "commute_scores.json",
                    "metro_stations.json",
                    "graph_network.json",
                    "sez_zones.geojson",
                ):
                    self.assertIn(required, city["artifacts"])
                    artifact = self.out1 / city["artifacts"][required]["path"]
                    self.assertTrue(artifact.is_file())
                    self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), city["artifacts"][required]["sha256"])

    def test_each_city_has_named_ranked_h3_polygons(self):
        for city_id in TARGET_CITIES:
            with self.subTest(city=city_id):
                master = json.loads((self.out1 / city_id / "hexes_master.json").read_text())
                geojson = json.loads((self.out1 / city_id / "hexes.geojson").read_text())
                rows = master["hexes"]
                features = geojson["features"]
                self.assertGreater(len(rows), 0)
                self.assertEqual(len(rows), len(features))
                self.assertEqual([row["rank"] for row in rows], list(range(1, len(rows) + 1)))
                self.assertEqual({row["hex_id"] for row in rows}, {feature["properties"]["hex_id"] for feature in features})
                self.assertTrue(all(feature["geometry"]["type"] == "Polygon" for feature in features))
                self.assertTrue(all(row["name"] and row["neighbourhood_name"] for row in rows))
                self.assertTrue(all(0 <= row["name_confidence"] <= 1 for row in rows))
                self.assertTrue(all("school_demand" in row["component_scores"] for row in rows))
                for key in (
                    "centroid_lat",
                    "centroid_lon",
                    "direct_total_units",
                    "known_units",
                    "residential_project_count",
                    "premium_plus_reported_enrollment_total",
                    "premium_plus_modeled_students_grade_2_9",
                    "direct_hospital_count",
                    "direct_office_count",
                    "q3_and_below_property_count",
                    "category",
                    "type",
                    "pagerank_personalized",
                    "pagerank_node_type",
                    "community_id",
                ):
                    self.assertTrue(all(key in row for row in rows), key)

    def test_client_summary_rollups_are_populated_for_every_city(self):
        for city_id in TARGET_CITIES:
            with self.subTest(city=city_id):
                summary = json.loads((self.out1 / city_id / "client_summary.json").read_text())
                zones = json.loads((self.out1 / city_id / "zones.json").read_text())["zones"]
                master = json.loads((self.out1 / city_id / "hexes_master.json").read_text())

                for key in (
                    "executive_metrics",
                    "coverage",
                    "quartile_breakdown",
                    "project_type_breakdown",
                    "recommendations",
                    "validation",
                    "handoff_links",
                    "category_hex_shortlists",
                ):
                    self.assertIn(key, summary)

                self.assertGreater(summary["executive_metrics"]["premium_plus_students_grade_2_9"], 0)
                self.assertGreater(summary["executive_metrics"]["premium_plus_reported_enrollment_total"], 0)
                self.assertGreaterEqual(summary["executive_metrics"]["premium_plus_modeled_students_grade_2_9"], 0)
                self.assertGreater(summary["executive_metrics"]["total_projects"], 0)
                self.assertGreater(len(summary["quartile_breakdown"]), 0)
                self.assertGreater(len(summary["project_type_breakdown"]), 0)
                self.assertGreater(len(summary["recommendations"]["micro_markets"]), 0)
                self.assertGreater(len(summary["category_hex_shortlists"]["premium_plus"]), 0)
                self.assertTrue(all(link["href"].startswith(f"data/city_legacy/{city_id}/") for link in summary["handoff_links"]))

                top_hex_ids = {row["hex_id"] for row in master["hexes"][:10]}
                recommended_hex_ids = {
                    row["hex_id"]
                    for row in summary["recommendations"]["micro_markets"]
                    if row.get("hex_id")
                }
                self.assertTrue(recommended_hex_ids & top_hex_ids)

                self.assertGreater(len(zones), 0)
                self.assertTrue(all(zone["top_hexes"] for zone in zones))
                self.assertTrue(all("top_score" in zone for zone in zones))
                self.assertTrue(all("premium_plus_students_grade_2_9" in zone for zone in zones))
                for zone in zones:
                    for hex_row in zone["top_hexes"]:
                        self.assertIn("name", hex_row)
                        self.assertIn("direct_total_units", hex_row)
                        self.assertIn("premium_plus_students_grade_2_9", hex_row)
                        self.assertIn("premium_plus_reported_enrollment_total", hex_row)

    def test_source_reconciliation_and_no_fee_surface(self):
        source_layers = {"schools", "projects", "offices", "hospitals", "localities"}
        for city_id in TARGET_CITIES:
            with self.subTest(city=city_id):
                report = json.loads((self.out1 / city_id / "report.json").read_text())
                school = json.loads((self.out1 / city_id / "school_market_summary.json").read_text())
                entities = json.loads((self.out1 / city_id / "school_entities.json").read_text())
                campuses = json.loads((self.out1 / city_id / "school_campuses.json").read_text())
                audit = json.loads((self.out1 / city_id / "school_market_audit.json").read_text())
                self.assertFalse(school["custom_annual_fee_filter_supported"])
                self.assertIn("annual fee values", school["reason"])
                for record in entities[:100] + campuses[:100]:
                    self.assertIn("fee_tier", record)
                    self.assertIn("fee_bucket", record)
                    self.assertIsNone(record["fee_min"])
                    self.assertIsNone(record["fee_max"])
                    if record["fee_tier"] in {"Super-Premium", "Premium"}:
                        self.assertEqual(record["fee_quartile"], "Q4")
                    elif record["fee_tier"] == "Affordable":
                        self.assertEqual(record["fee_quartile"], "Q3")
                    elif record["fee_tier"] == "Budget":
                        self.assertEqual(record["fee_quartile"], "Q2")
                    else:
                        self.assertEqual(record["fee_quartile"], "Q1")
                self.assertEqual(len(entities), len({record["entity_id"] for record in entities}))
                self.assertEqual(len(campuses), len({record["campus_id"] for record in campuses}))
                self.assertEqual(audit["published_entity_count"], len(entities))
                self.assertEqual(audit["published_campus_count"], len(campuses))
                self.assertEqual(audit["campus_rows_merged"], len(entities) - len(campuses))
                reconciliation = report["source_reconciliation"]
                for layer in source_layers:
                    self.assertGreaterEqual(reconciliation[layer]["source_rows"], reconciliation[layer]["mapped_to_h3_rows"])
                    self.assertEqual(
                        reconciliation[layer]["source_rows"],
                        reconciliation[layer]["mapped_to_h3_rows"] + reconciliation[layer]["unmapped_rows"],
                    )

    def test_legacy_sidecars_are_honest_and_reconcile(self):
        for city_id in TARGET_CITIES:
            with self.subTest(city=city_id):
                master = json.loads((self.out1 / city_id / "hexes_master.json").read_text())
                records = master["hexes"]
                graph = json.loads((self.out1 / city_id / "graph_network.json").read_text())
                q3 = json.loads((self.out1 / city_id / "q3_below_hex_counts.json").read_text())
                commute = json.loads((self.out1 / city_id / "commute_scores.json").read_text())
                sez = json.loads((self.out1 / city_id / "sez_zones.geojson").read_text())
                localities = json.loads((self.out1 / city_id / "localities.json").read_text())
                societies = json.loads((self.out1 / city_id / "societies.json").read_text())
                offices = json.loads((self.out1 / city_id / "sez_offices.json").read_text())
                entities = json.loads((self.out1 / city_id / "school_entities.json").read_text())
                self.assertEqual(len(graph["nodes"]), len(records))
                self.assertEqual({node["id"] for node in graph["nodes"]}, {row["hex_id"] for row in records})
                self.assertEqual(len(q3["hexes"]), len(records))
                self.assertEqual(commute["status"], "unavailable")
                self.assertIsNone(commute["provider"])
                self.assertIn("No travel time or routing score has been fabricated", commute["warning"])
                self.assertEqual(set(commute["by_hex"]), {row["hex_id"] for row in records})
                self.assertEqual(sez["type"], "FeatureCollection")
                self.assertEqual(sez["status"], "unavailable")
                self.assertEqual(sez["features"], [])
                self.assertIsInstance(localities, list)
                self.assertTrue(all("units" in society for society in societies))
                self.assertEqual(len(societies), len({society["project_id"] for society in societies}))
                self.assertTrue(all(society["entity_type"] == "residential_project" for society in societies))
                self.assertTrue(all("tam" not in society and "family_proxy" not in society for society in societies))
                self.assertTrue(all("boards" in entity and "board" in entity for entity in entities[:100]))
                allowed_tiers = {
                    "Tier 1 - MNC/GCC anchor",
                    "Tier 2 - Enterprise/tech anchor",
                    "Tier 3 - Regional/SMB office",
                    "Tier 4 - Local/generic office",
                    "Unclassified office",
                }
                self.assertTrue(all(office["company_prominence_tier"] in allowed_tiers for office in offices))

    def test_client_summary_rollups_are_populated_for_every_city(self):
        required_metric_keys = {
            "total_projects",
            "q4_total_units",
            "micro_markets",
            "premium_plus_reported_enrollment_total",
            "premium_plus_students_grade_2_9",
            "premium_plus_modeled_students_grade_2_9",
        }
        for city_id in TARGET_CITIES:
            with self.subTest(city=city_id):
                summary = json.loads((self.out1 / city_id / "client_summary.json").read_text())
                metrics = summary.get("executive_metrics") or {}
                self.assertTrue(required_metric_keys.issubset(metrics), metrics)
                self.assertGreater(metrics["total_projects"], 0)
                self.assertGreater(metrics["q4_total_units"], 0)
                self.assertGreater(metrics["micro_markets"], 0)
                self.assertGreater(metrics["premium_plus_students_grade_2_9"], 0)
                self.assertGreater(metrics["premium_plus_reported_enrollment_total"], 0)
                self.assertGreaterEqual(metrics["premium_plus_modeled_students_grade_2_9"], 0)
                self.assertGreater(len(summary.get("quartile_breakdown") or []), 0)
                self.assertGreater(len(summary.get("project_type_breakdown") or []), 0)
                self.assertGreater(len(summary.get("validation", {}).get("checks") or []), 0)
                recommendations = summary.get("recommendations", {}).get("micro_markets") or []
                self.assertGreater(len(recommendations), 0)
                self.assertTrue(all(row.get("name") and row.get("hex_id") for row in recommendations))
                self.assertEqual(recommendations[0]["status"], "Launch now")

                support = summary["decision_support"]
                self.assertTrue(support["priority_school_partners"])
                self.assertTrue(support["residential_project_targets"])
                self.assertTrue(support["candidate_catchments"])
                self.assertEqual(
                    [row["capture_rate_pct"] for row in support["campus_scenarios"]],
                    [1, 2, 3],
                )
                self.assertTrue(all(row["seats_per_campus"] == 200 for row in support["campus_scenarios"]))
                self.assertTrue(all(row["target_utilization"] == 0.8 for row in support["campus_scenarios"]))

    def test_report_zones_include_school_led_rollups(self):
        for city_id in TARGET_CITIES:
            with self.subTest(city=city_id):
                report = json.loads((self.out1 / city_id / "report.json").read_text())
                zones = report.get("zones") or {}
                self.assertGreater(len(zones), 0)
                self.assertTrue(
                    any((zone.get("premium_plus_students_grade_2_9") or 0) > 0 for zone in zones.values())
                )
                for zone in zones.values():
                    self.assertIn("school_count", zone)
                    self.assertIn("students_grade_2_9", zone)
                    self.assertIn("premium_plus_students_grade_2_9", zone)
                    self.assertIn("top_score", zone)
                    self.assertIn("top_10_avg_score", zone)
                    self.assertTrue(zone.get("top_hexes"))
                    top_hex = zone["top_hexes"][0]
                    self.assertIn("premium_plus_students_grade_2_9", top_hex)
                    self.assertIn("score", top_hex)

    def test_client_summary_rollups_are_populated_for_dashboard(self):
        required_summary_keys = {
            "executive_metrics",
            "coverage",
            "quartile_breakdown",
            "project_type_breakdown",
            "recommendations",
            "validation",
            "handoff_links",
            "localized_insight",
            "category_hex_shortlists",
            "decision_support",
        }
        for city_id in TARGET_CITIES:
            with self.subTest(city=city_id):
                summary = json.loads((self.out1 / city_id / "client_summary.json").read_text())
                report = json.loads((self.out1 / city_id / "report.json").read_text())
                master = json.loads((self.out1 / city_id / "hexes_master.json").read_text())

                self.assertTrue(required_summary_keys <= set(summary))
                self.assertGreater(summary["executive_metrics"]["total_projects"], 0)
                self.assertGreater(summary["executive_metrics"]["premium_plus_students_grade_2_9"], 0)
                self.assertGreater(summary["coverage"]["final_h3_hexes"], 0)
                self.assertTrue(summary["quartile_breakdown"])
                self.assertTrue(summary["project_type_breakdown"])
                self.assertTrue(summary["recommendations"]["micro_markets"])
                self.assertTrue(summary["category_hex_shortlists"]["premium_plus"])

                top_recommendation = summary["recommendations"]["micro_markets"][0]
                self.assertIn(top_recommendation["hex_id"], {row["hex_id"] for row in master["hexes"]})
                self.assertGreater(top_recommendation["reported_enrollment_total"], 0)
                self.assertIn("Premium+ students", top_recommendation["rationale"])

                zones = report["zones"]
                self.assertTrue(zones)
                for zone_name, zone in zones.items():
                    with self.subTest(city=city_id, zone=zone_name):
                        self.assertIn("premium_plus_students_grade_2_9", zone)
                        self.assertIn("top_score", zone)
                        self.assertIn("top_10_avg_score", zone)
                        self.assertTrue(zone["top_hexes"])
                        top_hex = zone["top_hexes"][0]
                        self.assertIn("name", top_hex)
                        self.assertIn("direct_total_units", top_hex)
                        self.assertIn("premium_plus_students_grade_2_9", top_hex)


if __name__ == "__main__":
    unittest.main()
