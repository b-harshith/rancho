import csv
import json

from pipelines.geospatial.prepare_delhi_ncr import component_for_postal_row


def test_delhi_state_always_maps_to_delhi_component():
    assert component_for_postal_row({"statename": "DELHI", "Districtname": "South Delhi"}) == "delhi_nct"


def test_historical_and_current_gurugram_names_map_together():
    assert component_for_postal_row({"statename": "HARYANA", "Districtname": "Gurgaon"}) == "gurugram"
    assert component_for_postal_row({"statename": "HARYANA", "Districtname": "Gurugram"}) == "gurugram"


def test_out_of_scope_district_is_not_silently_included():
    assert component_for_postal_row({"statename": "HARYANA", "Districtname": "Sonipat"}) is None


def test_generated_pin_ledger_is_unique_and_well_formed():
    path = "data/reference/pincodes/delhi_ncr_pin_candidates.csv"
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    pins = [row["pincode"] for row in rows]
    assert rows
    assert len(pins) == len(set(pins))
    assert all(len(pin) == 6 and pin.isdigit() for pin in pins)
    assert {"delhi_nct", "gurugram", "faridabad", "ghaziabad", "noida_greater_noida"} <= {
        component for row in rows for component in row["components"].split(";")
    }


def test_candidate_and_exclusion_ledgers_are_disjoint_and_reproducible():
    with open("data/reference/pincodes/delhi_ncr_pin_candidates.csv", encoding="utf-8", newline="") as handle:
        candidates = list(csv.DictReader(handle))
    with open("data/reference/pincodes/delhi_ncr_pin_exclusions.csv", encoding="utf-8", newline="") as handle:
        exclusions = list(csv.DictReader(handle))
    candidate_pins = {row["pincode"] for row in candidates}
    exclusion_pins = {row["pincode"] for row in exclusions}
    assert candidate_pins.isdisjoint(exclusion_pins)
    assert len(candidates) == 194
    assert len(exclusions) == 101
    membership_counts = {
        component: sum(component in row["components"].split(";") for row in candidates)
        for component in ("delhi_nct", "faridabad", "ghaziabad", "gurugram", "noida_greater_noida")
    }
    assert membership_counts == {
        "delhi_nct": 97,
        "faridabad": 15,
        "ghaziabad": 26,
        "gurugram": 29,
        "noida_greater_noida": 28,
    }


def test_generated_boundaries_retain_all_components():
    data = json.load(open("data/reference/boundaries/delhi_ncr_components.geojson", encoding="utf-8"))
    assert len(data["features"]) == 15
    assert sum(f["properties"]["component_id"] == "delhi_nct" for f in data["features"]) == 11
