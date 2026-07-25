import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import build_school_market as market


def row(name, lat, lon, *, place=None, udise=None, area="Area", fee_min=100_000, fee_max=100_000,
        students=100, source="estimate", board="CBSE", source_lat=None, source_lon=None):
    return {
        "name": name,
        "lat": lat,
        "lon": lon,
        "source_lat": lat if source_lat is None else source_lat,
        "source_lon": lon if source_lon is None else source_lon,
        "area": area,
        "address": f"{area}, Bengaluru, Karnataka",
        "google_formatted_address": f"{area}, Bengaluru, Karnataka",
        "google_place_id": place,
        "google_geocode_confidence": 0.98,
        "google_geocode_source": "places_text_search",
        "google_types": ["school", "educational_institution"],
        "google_geocode_distance_m": 0,
        "udise_code": udise,
        "fee_min": fee_min,
        "fee_max": fee_max,
        "students_grades_2_9": students,
        "students_total": students + 20,
        "enrollment_source": source,
        "board": board,
        "structural_category": "Secondary / K-10",
    }


class SchoolMarketTests(unittest.TestCase):
    def test_board_normalization(self):
        self.assertEqual(market.normalize_boards("CBSE/Cambridge/IB/NIOS"), ["cbse", "ib", "cambridge", "nios"])
        self.assertEqual(market.normalize_boards("ICSE/CISCE/ISC/ICSE"), ["cisce"])
        self.assertEqual(market.normalize_boards("No Board"), ["no_board"])
        self.assertEqual(market.board_affiliation_status("To be affiliated to CBSE"), "proposed")

    def test_zone_has_no_outside_cutoff(self):
        self.assertEqual(market.classify_zone(12.9716, 77.5946), "Central")
        self.assertIn(market.classify_zone(13.47, 77.23), {"North", "North-East", "East", "South-East", "South", "South-West", "West", "North-West"})

    def test_place_id_alone_does_not_merge(self):
        rows = [
            row("Alpha School", 12.98, 77.60, place="same", area="Indiranagar"),
            row("Completely Different Academy", 12.98, 77.60, place="same", area="Indiranagar"),
        ]
        groups, quarantine, _ = market.resolve_entities(rows)
        self.assertEqual(len(groups), 2)
        self.assertFalse(quarantine)

    def test_proximity_without_place_id_does_not_merge(self):
        rows = [
            row("Alpha School", 12.98, 77.60, place=None, area="Indiranagar"),
            row("Alpha School", 12.98, 77.60, place=None, area="Indiranagar"),
        ]
        groups, quarantine, _ = market.resolve_entities(rows)
        self.assertEqual(len(groups), 2)
        self.assertFalse(quarantine)

    def test_place_match_requires_address_locality_and_source_coordinate_agreement(self):
        base = row("Alpha School", 12.98, 77.60, place="same", area="Indiranagar")
        cases = []
        bad_address = dict(base, address="Different Road, Bengaluru, Karnataka")
        cases.append(bad_address)
        bad_locality = dict(base, area="Whitefield")
        cases.append(bad_locality)
        bad_source = dict(base, source_lat=13.10, source_lon=77.80)
        cases.append(bad_source)
        for conflicting in cases:
            groups, quarantine, _ = market.resolve_entities([base, conflicting])
            self.assertEqual(len(groups), 2)
            self.assertFalse(quarantine)

    def test_same_udise_merges_without_google_place(self):
        rows = [
            row("Alpha School", 12.98, 77.60, place=None, udise="U1", source="udise"),
            row("Alpha School Branch", 13.10, 77.70, place=None, udise="U1", source="udise"),
        ]
        groups, quarantine, _ = market.resolve_entities(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)
        self.assertFalse(quarantine)

    def test_strong_place_name_area_match_merges(self):
        rows = [
            row("Knowledgeum Academy", 12.94, 77.58, place="same", area="Jayanagar", students=250),
            row("Knowledgeum Academy Bengaluru", 12.94, 77.58, place="same", area="Jayanagar", students=260),
        ]
        groups, quarantine, _ = market.resolve_entities(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)
        self.assertFalse(quarantine)

    def test_distinct_udise_identity_conflict_is_quarantined(self):
        rows = [
            row("Same School", 12.98, 77.60, place="same", udise="U1", source="udise"),
            row("Same School", 12.98, 77.60, place="same", udise="U2", source="udise"),
        ]
        groups, quarantine, ambiguous = market.resolve_entities(rows)
        self.assertEqual(groups, [])
        self.assertEqual(set(quarantine), {0, 1})
        self.assertEqual(len(ambiguous), 1)

    def test_q4_is_floor_quarter_and_deterministic(self):
        entities = []
        for index in range(9):
            entities.append({
                "entity_id": f"e{index}", "name": f"School {index}", "fee_min": 100_000,
                "fee_max": 200_000 if index < 3 else 100_000, "quartile": None,
                "q4_subquartile": None, "q4_segment": None,
            })
        market.assign_quartiles(entities)
        q4 = [entity for entity in entities if entity["quartile"] == "Q4"]
        self.assertEqual(len(q4), 2)
        self.assertEqual([entity["entity_id"] for entity in q4], ["e0", "e1"])

    def test_fee_sensitivity_uses_fee_max_inclusively(self):
        entity = {
            "entity_id": "e1", "campus_id": "c1", "name": "Range School", "fee_min": 150_000, "fee_max": 200_000,
            "students_grades_2_9": 100, "enrollment_source": "estimated",
            "quartile": "Q4", "q4_subquartile": "Q4-Sub-Q4", "q4_segment": "Ultra Luxury",
            "zone": "Central", "boards": ["cbse"],
        }
        campus = {"entity_count": 1, "students_grades_2_9": 100}
        summary = market.build_summary([entity], [campus])
        two_lakh = next(item for item in summary["fee_max_sensitivity"] if item["threshold_fee_max"] == 200_000)
        self.assertEqual(two_lakh["school_entity_count_all"], 1)
        self.assertEqual(two_lakh["fee_range_crossing_entity_count"], 1)

    def test_capacity_locked_formulas(self):
        cases = {
            0: (0, 0, 0, 0, 0.0, False),
            160: (0, 160, 1, 1, 0.8, False),
            200: (1, 0, 1, 1, 1.0, False),
            250: (1, 50, 2, 1, 0.625, True),
        }
        for students, expected in cases.items():
            full_rate = next(item for item in market.capacity_summary(students) if item["capture_rate"] == 1.0)
            actual = (
                full_rate["packed_full_centers"], full_rate["packed_residual"],
                full_rate["minimum_centers_required"], full_rate["maximum_centers_at_80pct"],
                full_rate["utilization_at_minimum_centers"], full_rate["below_target_utilization"],
            )
            self.assertEqual(actual, expected)

    def test_locked_raw_preclean_benchmarks(self):
        candidates = (
            ROOT / "DATA" / "raw" / "schools_geocoded.json",
            ROOT / "new data" / "schools_geocoded.json",
        )
        raw_path = next((path for path in candidates if path.exists()), None)
        if raw_path is None:
            self.skipTest("Optional raw school benchmark fixture is intentionally excluded from the minimal workspace")
        rows = json.loads(raw_path.read_text())
        benchmark = market.raw_preclean_benchmarks(rows)
        self.assertEqual(
            benchmark["q4"],
            {
                "row_count_all": 501,
                "row_count_grade_2_9_positive": 461,
                "students_grades_2_9_expanded": 253086.0,
                "description": "Raw source-row Q4 benchmark before quarantine, duplicate collapse, and entity recomputation.",
            },
        )
        self.assertEqual(
            [(item["threshold_fee_max"], item["positive_grade_2_9_row_count"], item["students_grades_2_9_expanded"]) for item in benchmark["fee_max_sensitivity"]],
            [(175_000, 86, 29019.0), (180_000, 81, 26743.0), (200_000, 39, 10021.0)],
        )

    def test_campus_grouping_does_not_sum_colocated_duplicate_entities(self):
        entities = [
            market.make_entity([0], [row("Shared School", 12.98, 77.60, place="p", area="Area", students=600)]),
            market.make_entity([0], [row("Shared School Academy", 12.98, 77.60, place="p", area="Area", students=400)]),
        ]
        campuses = market.group_campuses(entities)
        self.assertEqual(len(campuses), 1)
        self.assertEqual(campuses[0]["students_grades_2_9"], 600)

    def test_end_to_end_outputs_and_reconciliation(self):
        rows = [
            row("Alpha School", 12.98, 77.60, place="p1", udise="U1", source="udise", fee_max=500_000),
            row("Beta School", 13.02, 77.64, place="p2", fee_max=300_000),
            row("Gamma School", 12.90, 77.60, place="p3", fee_max=200_000),
            row("Delta School", 12.88, 77.70, place="p4", fee_max=100_000),
            row("Epsilon School", 13.10, 77.60, place="p5", fee_max=50_000),
            row("Epsilon School Bengaluru", 13.10, 77.60, place="p5", fee_max=50_000),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, output_dir = root / "input.json", root / "out"
            input_path.write_text(json.dumps(rows))
            audit = market.build(input_path, output_dir)
            self.assertTrue(all(audit["validation"].values()))
            self.assertTrue(audit["validation"]["unique_entity_ids"])
            self.assertTrue(audit["validation"]["unique_campus_ids"])
            self.assertEqual(audit["duplicate_rows_collapsed"], 1)
            self.assertEqual(audit["published_campus_count"], 5)
            self.assertEqual(audit["q4"]["school_entity_count_all"], 1)
            entities = json.loads((output_dir / "school_entities.json").read_text())
            self.assertTrue(all(entity["school_entity_id"] == entity["entity_id"] for entity in entities))
            for filename in ("school_entities.json", "school_campuses.json", "school_market_summary.json", "school_market_audit.json"):
                self.assertTrue((output_dir / filename).exists())


if __name__ == "__main__":
    unittest.main()
