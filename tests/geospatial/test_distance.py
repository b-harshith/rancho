import math
import unittest

from pipelines.geospatial.distance import haversine_km, haversine_m


class HaversineTests(unittest.TestCase):
    def test_same_point_is_zero(self):
        self.assertEqual(haversine_km(28.6139, 77.2090, 28.6139, 77.2090), 0)

    def test_known_delhi_to_gurugram_distance(self):
        self.assertAlmostEqual(haversine_km(28.6139, 77.2090, 28.4595, 77.0266), 24.9, delta=0.3)

    def test_metres_and_kilometres_agree(self):
        km = haversine_km(28.6139, 77.2090, 28.5355, 77.3910)
        self.assertAlmostEqual(haversine_m(28.6139, 77.2090, 28.5355, 77.3910), km * 1000)

    def test_invalid_latitudes_rejected(self):
        for value in (math.nan, math.inf, -math.inf, 91, -91):
            with self.subTest(value=value), self.assertRaises(ValueError):
                haversine_km(value, 77, 28, 77)

    def test_invalid_longitudes_rejected(self):
        for value in (181, -181):
            with self.subTest(value=value), self.assertRaises(ValueError):
                haversine_km(28, value, 28, 77)


if __name__ == "__main__":
    unittest.main()
