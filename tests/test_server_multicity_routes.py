import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import server  # noqa: E402


class ServerMulticityRouteTests(unittest.TestCase):
    def setUp(self):
        self.handler = object.__new__(server.CustomHandler)

    def test_city_routes_serve_multicity_portal(self):
        for route in ("/", "/city/hyderabad", "/cities/mumbai"):
            with self.subTest(route=route):
                self.assertTrue(
                    server.CustomHandler.translate_path(self.handler, route).endswith(
                        "public/multicity.html"
                    )
                )

    def test_legacy_bengaluru_routes_serve_existing_deep_dive(self):
        for route in ("/bangalore", "/bengaluru"):
            with self.subTest(route=route):
                self.assertTrue(
                    server.CustomHandler.translate_path(self.handler, route).endswith(
                        "public/index.html"
                    )
                )

    def test_unknown_city_route_is_not_translated_to_static_file(self):
        path = server.CustomHandler.translate_path(self.handler, "/city/chennai")
        self.assertTrue(path.endswith("public/__invalid_path__"))

    def test_city_scoped_catchment_validation(self):
        self.assertEqual(server.validate_portal_city(None), "bengaluru")
        self.assertEqual(server.validate_portal_city("mumbai"), "mumbai")
        for invalid in ("pune", "../pune"):
            with self.subTest(city=invalid), self.assertRaises(ValueError):
                server.validate_portal_city(invalid)
        self.assertEqual(server.validate_city_coordinates("mumbai", 19.08, 72.88), (19.08, 72.88))
        with self.assertRaises(server.CatchmentValidationError):
            server.validate_city_coordinates("mumbai", 12.97, 77.59)

    def test_retired_pune_city_urls_redirect_to_portal_home(self):
        for route in ("/city/pune", "/cities/pune"):
            with self.subTest(route=route):
                handler = object.__new__(server.CustomHandler)
                handler.path = route
                responses = []
                headers = []
                handler.send_response = responses.append
                handler.send_header = lambda name, value: headers.append((name, value))
                handler.end_headers = lambda: None
                server.CustomHandler.do_GET(handler)
                self.assertEqual(responses, [308])
                self.assertIn(("Location", "/"), headers)

    def test_fee_threshold_parameters_are_rejected(self):
        with self.assertRaises(server.CatchmentValidationError):
            server.reject_fee_thresholds({"fee_threshold": ["200000"]})
        server.reject_fee_thresholds({"category": ["premium_plus"]})

    def test_every_city_has_a_generated_catchment_bundle(self):
        for city in server.SUPPORTED_CITY_IDS:
            with self.subTest(city=city):
                path = server._city_catchment_data_dir(city)
                self.assertEqual(path.name, city)
                self.assertTrue((path / "hexes.geojson").is_file())


if __name__ == "__main__":
    unittest.main()
