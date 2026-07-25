import unittest
from pathlib import Path

from src.multicity.config import load_city_registry
from src.multicity.ranking import build_ranking


ROOT = Path(__file__).resolve().parents[2]


def summary(city, value, coverage, status="admitted"):
    return {
        "canonical_city_id": city,
        "schema_version": "1.0.0",
        "admission_status": status,
        "as_of": "2026-06-30T00:00:00Z",
        "lineage": {"manifest": f"{city}.json"},
        "metrics": {"known_beds": {"value": value, "coverage_pct": coverage,
                                    "source_count": 10, "lineage": {"field": "bed_count"}}},
    }


class RankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_city_registry(ROOT / "config/cities.yaml", ROOT / "config/source_city_registry.json")

    def rank(self, summaries, minimum=0):
        return build_ranking(summaries, "known_beds", label="Known hospital beds", unit="beds",
                             methodology_version="1.0.0", as_of="2026-06-30T00:00:00Z",
                             registry=self.registry, minimum_coverage_pct=minimum)

    def test_competition_ties_are_1_2_2_4(self):
        result = self.rank([summary("bengaluru", 400, 90), summary("mumbai", 300, 90),
                            summary("hyderabad", 300, 90), summary("chennai", 200, 90)])
        self.assertEqual([row["rank"] for row in result["rows"]], [1, 2, 2, 4])
        self.assertEqual([row["canonical_city_id"] for row in result["rows"]][1:3], ["hyderabad", "mumbai"])

    def test_null_is_visible_and_never_ranked_as_zero(self):
        result = self.rank([summary("bengaluru", 100, 90), summary("hyderabad", None, 90)])
        null_row = result["rows"][1]
        self.assertIsNone(null_row["value"])
        self.assertIsNone(null_row["rank"])
        self.assertEqual(null_row["quality_status"], "unavailable")

    def test_low_coverage_is_visible_but_unranked(self):
        result = self.rank([summary("bengaluru", 100, 80), summary("hyderabad", 999, 49)], minimum=50)
        low = result["rows"][1]
        self.assertEqual(low["value"], 999)
        self.assertEqual(low["coverage_pct"], 49)
        self.assertIsNone(low["rank"])
        self.assertEqual(low["quality_status"], "insufficient_coverage")

    def test_non_admitted_summary_is_excluded(self):
        result = self.rank([summary("bengaluru", 100, 80), summary("hyderabad", 999, 99, "pending")])
        self.assertEqual([row["canonical_city_id"] for row in result["rows"]], ["bengaluru"])


if __name__ == "__main__":
    unittest.main()
