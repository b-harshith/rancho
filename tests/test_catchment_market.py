import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catchment_market import (  # noqa: E402
    CatchmentConfigurationError,
    CatchmentProviderError,
    CatchmentValidationError,
    build_market_ledger,
    build_portfolio_result,
    capacity_scenarios,
    clear_geometry_cache,
    get_live_drive_isochrone,
    google_maps_api_key,
    parse_market_options,
    validate_catchment_city,
    validate_city_coordinates,
    validate_google_maps_api_key,
    validate_live_request,
)


def school(campus_id, lat, lon, zone, *, quartile="Q4", fee_max=160000, enrollment=100, sub="Q4-Sub-Q1"):
    return {
        "entity_id": f"entity-{campus_id}",
        "campus_id": campus_id,
        "name": campus_id,
        "lat": lat,
        "lon": lon,
        "zone": zone,
        "fee_min_inr": fee_max,
        "fee_max_inr": fee_max,
        "fee_quartile": quartile,
        "q4_subquartile": sub,
        "q4_tier_label": "Premium Elite",
        "boards": ["CBSE"],
        "grade_2_9_enrollment": enrollment,
        "enrollment_source": "udise",
        "udise_codes": [],
        "source_row_ids": [],
    }


class MarketLedgerTests(unittest.TestCase):
    def setUp(self):
        # Center is north of the 5 km Central radius. Polygon includes its boundary.
        self.geometry = {
            "type": "Polygon",
            "coordinates": [[[77.50, 13.05], [77.70, 13.05], [77.70, 13.20], [77.50, 13.20], [77.50, 13.05]]],
        }
        self.options = {
            "fee_sensitivity_thresholds": [175000, 200000],
            "capture_rates": [0.05, 0.10, 0.20],
            "center_capacity": 200,
            "target_utilization": 0.8,
        }

    def test_q4_default_point_and_zone_rules_are_evidence_only(self):
        data = {
            "schools": [
                school("direct", 13.10, 77.59, "North", fee_max=160000, enrollment=100),
                school("adjacent", 13.11, 77.61, "North-East", fee_max=180000, enrollment=80),
                school("nonadjacent", 13.12, 77.62, "South", fee_max=220000, enrollment=60),
                school("alternate-only", 13.13, 77.63, "North", quartile="Q3", fee_max=250000, enrollment=40),
                # Exact polygon boundary must count via covers(), not contains().
                school("boundary", 13.05, 77.50, "North-West", fee_max=180000, enrollment=20),
                school("outside", 13.30, 77.59, "North", fee_max=500000, enrollment=999),
            ],
            "societies": [{
                "society_id": "society-1", "name": "Society", "lat": 13.10, "lon": 77.60,
                "zone": "North", "tier": "Luxury", "family_proxy": 75, "units": 100,
            }],
            "data_revision": "test",
        }
        result = build_market_ledger(
            geometry=self.geometry, center_lat=13.10, center_lon=77.5946,
            market_data=data, options=self.options,
        )

        market = result["school_market"]
        self.assertEqual(market["direct"]["entity_count"], 1)
        self.assertEqual(market["reachable"]["entity_count"], 3)
        self.assertEqual(market["reachable"]["campus_count"], 3)
        self.assertEqual(market["reachable"]["grade_2_9_enrollment"], 200)
        self.assertEqual(market["excluded"]["non_adjacent_inside_isochrone"]["entity_count"], 1)
        self.assertEqual(result["residential_market"]["inside_isochrone"]["family_proxy"], 75)

        # Fee sensitivity is an alternate cohort, not an intersection with Q4.
        threshold_175 = market["absolute_fee_sensitivity"]["items"][0]
        self.assertEqual(threshold_175["reachable"]["entity_count"], 3)
        self.assertEqual(threshold_175["reachable"]["grade_2_9_enrollment"], 140)
        self.assertEqual(len(threshold_175["entities"]), 3)
        self.assertEqual(len(threshold_175["campuses"]), 3)
        self.assertEqual(threshold_175["cohort"]["id"], "fee_max_gte_175000")
        # The below-threshold Q4 campus remains in the primary market.
        self.assertIn("direct", {row["campus_id"] for row in market["campuses"]})

    def test_colocated_entities_are_unique_demand_but_one_map_campus(self):
        first = school("shared-campus", 13.10, 77.59, "North", enrollment=70)
        second = school("shared-campus", 13.10, 77.59, "North", enrollment=30)
        second["entity_id"] = "entity-shared-campus-2"
        data = {"schools": [first, second], "societies": [], "data_revision": "test"}
        result = build_market_ledger(
            geometry=self.geometry, center_lat=13.10, center_lon=77.5946,
            market_data=data, options=self.options,
        )
        reachable = result["school_market"]["reachable"]
        self.assertEqual(reachable["entity_count"], 2)
        self.assertEqual(reachable["campus_count"], 1)
        self.assertEqual(reachable["grade_2_9_enrollment"], 100)

    def test_bucket_category_cohort_does_not_require_annual_fee(self):
        premium = school("premium", 13.10, 77.59, "North", fee_max=None, enrollment=90)
        premium["fee_bucket"] = "premium"
        budget = school("budget", 13.11, 77.61, "North-East", fee_max=None, enrollment=400)
        budget["fee_bucket"] = "budget"
        options = {**self.options, "category": "premium_plus", "fee_sensitivity_thresholds": []}
        result = build_market_ledger(
            geometry=self.geometry,
            center_lat=13.10,
            center_lon=77.5946,
            market_data={"schools": [premium, budget], "societies": [], "data_revision": "test"},
            options=options,
        )
        market = result["school_market"]
        self.assertEqual(market["cohort"]["id"], "premium_plus")
        self.assertFalse(market["cohort"]["annual_fee_filter_supported"])
        self.assertEqual(market["reachable"]["grade_2_9_enrollment"], 90)
        self.assertEqual(market["absolute_fee_sensitivity"]["items"], [])

    def test_capacity_formulas(self):
        expected = {
            0: (0, 0, 0, 0, 0.0, False),
            160: (0, 160, 1, 1, 0.8, False),
            200: (1, 0, 1, 1, 1.0, False),
            250: (1, 50, 2, 1, 0.625, True),
        }
        for students, values in expected.items():
            scenario = capacity_scenarios(students, [1.0], 200, 0.8)[0]
            actual = (
                scenario["packed_full_centers"], scenario["packed_residual_students"],
                scenario["minimum_centers_required"], scenario["maximum_centers_at_target_utilization"],
                scenario["utilization_at_minimum_centers"], scenario["below_target_utilization"],
            )
            self.assertEqual(actual, values)

    def test_portfolio_union_overlap_and_request_order_increment(self):
        def entity(entity_id, campus_id, enrollment):
            return {"entity_id": entity_id, "campus_id": campus_id, "grade_2_9_enrollment": enrollment}

        centers = [
            {"center_id": "A", "school_market": {"entities": [entity("e1", "c1", 10), entity("e2", "c2", 20)]}},
            {"center_id": "B", "school_market": {"entities": [entity("e2", "c2", 20), entity("e3", "c3", 30)]}},
        ]
        result = build_portfolio_result(centers, self.options)
        self.assertEqual(result["unique_reachable_entity_count"], 3)
        self.assertEqual(result["unique_reachable_campus_count"], 3)
        self.assertEqual(result["unique_reachable_grade_2_9_enrollment"], 60)
        self.assertEqual(result["shared_entity_touchpoints"][0]["entity_id"], "e2")
        self.assertEqual(result["shared_campus_touchpoints"][0]["campus_id"], "c2")
        self.assertEqual(result["pairwise_overlap"][0]["shared_grade_2_9_enrollment"], 20)
        self.assertEqual(result["incremental_by_request_order"][0]["incremental_grade_2_9_enrollment"], 30)
        self.assertEqual(result["incremental_by_request_order"][1]["incremental_grade_2_9_enrollment"], 30)
        self.assertIn("no student is allocated", result["methodology"])
        self.assertEqual(result["capacity"]["basis"], "portfolio_unique_reachable_entity_enrollment")

    def test_portfolio_aggregates_absolute_fee_cohorts_separately(self):
        def entity(entity_id, campus_id, enrollment):
            return {"entity_id": entity_id, "campus_id": campus_id, "grade_2_9_enrollment": enrollment}

        cohort = {"id": "fee_max_q4", "quartile": "Q4"}
        absolute = {"id": "fee_max_gte_200000", "threshold_inr": 200000}
        centers = [
            {
                "center_id": "A",
                "school_market": {
                    "cohort": cohort,
                    "entities": [entity("q1", "c1", 10)],
                    "absolute_fee_sensitivity": {"items": [{
                        "threshold_inr": 200000, "cohort": absolute,
                        "entities": [entity("f1", "fc1", 40), entity("shared", "fc2", 20)],
                    }]},
                },
            },
            {
                "center_id": "B",
                "school_market": {
                    "cohort": cohort,
                    "entities": [entity("q2", "c2", 30)],
                    "absolute_fee_sensitivity": {"items": [{
                        "threshold_inr": 200000, "cohort": absolute,
                        "entities": [entity("shared", "fc2", 20), entity("f2", "fc3", 60)],
                    }]},
                },
            },
        ]
        result = build_portfolio_result(centers, self.options)
        self.assertEqual(result["cohort"]["id"], "fee_max_q4")
        fee_portfolio = result["absolute_fee_sensitivity"]["items"][0]["portfolio"]
        self.assertEqual(fee_portfolio["cohort"]["id"], "fee_max_gte_200000")
        self.assertEqual(fee_portfolio["unique_reachable_entity_count"], 3)
        self.assertEqual(fee_portfolio["unique_reachable_campus_count"], 3)
        self.assertEqual(fee_portfolio["unique_reachable_grade_2_9_enrollment"], 120)
        self.assertEqual(fee_portfolio["shared_entity_touchpoints"][0]["entity_id"], "shared")
        self.assertEqual(fee_portfolio["capacity"]["cohort_id"], "fee_max_gte_200000")

    def test_portfolio_rejects_mixed_primary_cohorts(self):
        centers = [
            {"center_id": "A", "school_market": {"cohort": {"id": "q4"}, "entities": []}},
            {"center_id": "B", "school_market": {"cohort": {"id": "fee"}, "entities": []}},
        ]
        with self.assertRaises(CatchmentValidationError):
            build_portfolio_result(centers, self.options)

    def test_portfolio_center_cap(self):
        centers = [{"center_id": str(i), "school_market": {"entities": []}} for i in range(11)]
        with self.assertRaises(CatchmentValidationError):
            build_portfolio_result(centers, self.options)


class ValidationAndCacheTests(unittest.TestCase):
    VALID_SERVER_KEY = "AIza" + "S" * 35
    VALID_CLIENT_KEY = "AIza" + "C" * 35

    def test_live_drive_only_validation(self):
        with self.assertRaises(CatchmentValidationError):
            validate_live_request(lat=13, lon=77, catchment_mode="distance", travel_mode="DRIVE", live_traffic="true", duration=30)
        with self.assertRaises(CatchmentValidationError):
            validate_live_request(lat=13, lon=77, catchment_mode="time", travel_mode="WALK", live_traffic="true", duration=30)
        with self.assertRaises(CatchmentValidationError):
            validate_live_request(lat=13, lon=77, catchment_mode="time", travel_mode="DRIVE", live_traffic="false", duration=30)
        with self.assertRaises(CatchmentValidationError):
            validate_live_request(lat=13, lon=77, catchment_mode="time", travel_mode="DRIVE", live_traffic="true", duration=20)

    def test_option_caps_and_precision(self):
        options = parse_market_options({"fee_sensitivity_thresholds": ["175000,180000,200000"]})
        self.assertEqual(options["fee_sensitivity_thresholds"], [175000, 180000, 200000])
        with self.assertRaises(CatchmentValidationError):
            parse_market_options({"fee_sensitivity_thresholds": ["175000.5"]})
        with self.assertRaises(CatchmentValidationError):
            parse_market_options({"capture_rates": ["5"]})

    def test_geometry_cache_and_fixed_google_request(self):
        clear_geometry_cache()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"geometry": {
            "type": "Polygon",
            "coordinates": [[[77.5, 13.0], [77.6, 13.0], [77.6, 13.1], [77.5, 13.1], [77.5, 13.0]]],
        }}
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": self.VALID_SERVER_KEY}, clear=False), patch(
            "catchment_market.requests.post", return_value=response
        ) as post:
            _, first = get_live_drive_isochrone(13.01, 77.51, 30, now=1000)
            _, second = get_live_drive_isochrone(13.01, 77.51, 30, now=1001)
        self.assertFalse(first["hit"])
        self.assertTrue(second["hit"])
        self.assertEqual(post.call_count, 1)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["travel_mode"], "DRIVE")
        self.assertEqual(kwargs["json"]["routing_preference"], "TRAFFIC_AWARE")
        self.assertEqual(kwargs["headers"]["X-Goog-Api-Key"], self.VALID_SERVER_KEY)

    def test_client_key_is_validated_preferred_strict_and_not_cached(self):
        clear_geometry_cache()
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"geometry": {
            "type": "Polygon",
            "coordinates": [[[77.5, 13.0], [77.6, 13.0], [77.6, 13.1], [77.5, 13.1], [77.5, 13.0]]],
        }}
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": self.VALID_SERVER_KEY}, clear=False), patch(
            "catchment_market.requests.post", return_value=response
        ) as post:
            _, first = get_live_drive_isochrone(
                13.01, 77.51, 30, now=1000, api_key=self.VALID_CLIENT_KEY
            )
            _, second = get_live_drive_isochrone(
                13.01, 77.51, 30, now=1001, api_key=self.VALID_CLIENT_KEY
            )
        self.assertFalse(first["hit"])
        self.assertFalse(second["hit"])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["headers"]["X-Goog-Api-Key"], self.VALID_CLIENT_KEY)

        clear_geometry_cache()
        with patch("catchment_market.requests.post", side_effect=RuntimeError("provider down")):
            with self.assertRaises(CatchmentProviderError):
                get_live_drive_isochrone(
                    13.01, 77.51, 30, now=2000, api_key=self.VALID_CLIENT_KEY
                )

    def test_google_key_and_city_validation(self):
        self.assertEqual(validate_google_maps_api_key(self.VALID_CLIENT_KEY), self.VALID_CLIENT_KEY)
        self.assertEqual(google_maps_api_key(self.VALID_CLIENT_KEY), self.VALID_CLIENT_KEY)
        for invalid in ("", "short", "contains space", "../secret"):
            with self.subTest(key=invalid), self.assertRaises(CatchmentValidationError):
                validate_google_maps_api_key(invalid)
        for city in ("delhi_ncr", "bengaluru", "hyderabad", "mumbai"):
            self.assertEqual(validate_catchment_city(city), city)
        with self.assertRaises(CatchmentValidationError):
            validate_catchment_city("../bengaluru")
        self.assertEqual(validate_city_coordinates("mumbai", 19.08, 72.88), (19.08, 72.88))
        with self.assertRaises(CatchmentValidationError):
            validate_city_coordinates("mumbai", 12.97, 77.59)

    def test_missing_environment_key_is_structured_configuration_error(self):
        clear_geometry_cache()
        with patch.dict(os.environ, {}, clear=True):
            geometry, metadata = get_live_drive_isochrone(13.01, 77.51, 30, now=2000)
        self.assertEqual(geometry["type"], "Polygon")
        self.assertEqual(metadata["provider"], "circular_travel_speed_proxy")

    def test_serverless_catchment_defaults_to_one_band(self):
        from api import catchment

        geometry = {
            "type": "Polygon",
            "coordinates": [[[77.5, 13.0], [77.6, 13.0], [77.6, 13.1], [77.5, 13.1], [77.5, 13.0]]],
        }
        catchment.HEXES = []
        catchment.HEX_GEOMS = []
        catchment.HEX_TREE = STRtree([])
        catchment.HEX_LOOKUP = {}
        catchment.HEX_TO_SOCIETIES = {}
        catchment.HEX_TO_HOSPITALS = {}
        catchment.HEX_TO_OFFICES = {}
        catchment.Q3_HEX_TREE = STRtree([])
        catchment.Q3_HEX_RECORDS = []
        with patch("api.catchment.get_live_drive_isochrone", return_value=(geometry, {"hit": False})) as provider:
            catchment._build_google_time_catchment(
                13.05, 77.55, 30, 10, self.VALID_CLIENT_KEY,
                include_bands=False, strict_provider=True,
            )
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(provider.call_args.kwargs["api_key"], self.VALID_CLIENT_KEY)
            self.assertTrue(provider.call_args.kwargs["strict"])
            provider.reset_mock()
            catchment._build_google_time_catchment(
                13.05, 77.55, 30, 10, self.VALID_CLIENT_KEY,
                include_bands=True, strict_provider=True,
            )
            self.assertEqual(provider.call_count, 4)


class ServerlessCityRuntimeTests(unittest.TestCase):
    def _write_fixture(self, root, city):
        city_dir = Path(root) / city
        city_dir.mkdir(parents=True)
        payloads = {
            "hexes.geojson": {"type": "FeatureCollection", "features": []},
            "hexes_master.json": {"hexes": []},
            "societies.json": [],
            "hospitals.json": [],
            "sez_zones.geojson": {"type": "FeatureCollection", "features": []},
            "sez_offices.json": [],
            "q3_below_hex_counts.json": {"hexes": []},
            "school_entities.json": [],
            "metro_stations.json": [{"name": f"{city} station", "lat": 1, "lon": 1}],
        }
        for name, payload in payloads.items():
            (city_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_city_runtime_reloads_and_uses_normalized_metro_filename(self):
        from api import catchment

        with tempfile.TemporaryDirectory() as temporary:
            for city in ("delhi_ncr", "bengaluru", "hyderabad", "mumbai"):
                self._write_fixture(temporary, city)
            with patch.object(catchment, "DATA_DIR", Path(temporary)):
                catchment.LOADED_CITY_ID = None
                catchment.HEXES = None
                catchment.HEX_TREE = None
                for city in ("delhi_ncr", "bengaluru", "hyderabad", "mumbai"):
                    catchment.load_catchment_data(city)
                    self.assertEqual(catchment.LOADED_CITY_ID, city)
                    self.assertEqual(catchment.MARKET_DATA["city_id"], city)
                    self.assertEqual(catchment.METRO_STATIONS[0]["name"], f"{city} station")

    def test_header_transport_and_query_key_rejection(self):
        from api import catchment

        key = ValidationAndCacheTests.VALID_CLIENT_KEY
        self.assertEqual(
            catchment._request_maps_api_key({"X-Google-Maps-Api-Key": key}), key
        )
        with self.assertRaises(CatchmentValidationError):
            catchment._request_maps_api_key({"X-Google-Maps-Api-Key": "bad key"})
        with self.assertRaises(CatchmentValidationError):
            catchment._reject_query_api_keys({"google_maps_api_key": [key]})


if __name__ == "__main__":
    unittest.main()
