"""Build one deduplicated UDISE PIN input from selected city candidate files."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CITY_IDS = ("mumbai", "hyderabad", "chennai", "kolkata", "pune", "ahmedabad")
OUTPUT = ROOT / "data/input/udise_combined_six_cities_pincodes.json"
MANIFEST = ROOT / "data/input/udise_combined_six_cities_manifest.json"


def main() -> None:
    pins_by_city: dict[str, list[str]] = {}
    all_pins: set[str] = set()
    for city_id in CITY_IDS:
        source = ROOT / f"data/reference/pincodes/{city_id}_pin_candidates.csv"
        with source.open(newline="", encoding="utf-8") as handle:
            pins = sorted({row["pincode"].strip() for row in csv.DictReader(handle)})
        if not pins or any(len(pin) != 6 or not pin.isdigit() for pin in pins):
            raise ValueError(f"Invalid PIN data for {city_id}")
        pins_by_city[city_id] = pins
        all_pins.update(pins)

    combined = sorted(all_pins)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(
        json.dumps(
            {
                "included_cities": list(CITY_IDS),
                "excluded_cities": ["bengaluru", "delhi_ncr"],
                "source_files": {
                    city_id: f"data/reference/pincodes/{city_id}_pin_candidates.csv"
                    for city_id in CITY_IDS
                },
                "source_counts": {city_id: len(pins) for city_id, pins in pins_by_city.items()},
                "combined_unique_pincode_count": len(combined),
                "deduplication_rule": "six-digit PIN retained once across all included cities",
                "output_file": str(OUTPUT.relative_to(ROOT)),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(combined)} unique PINs to {OUTPUT}")


if __name__ == "__main__":
    main()
