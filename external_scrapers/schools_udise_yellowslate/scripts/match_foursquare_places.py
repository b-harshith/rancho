#!/usr/bin/env python3
"""Match the classified school dataset to Foursquare Bangalore places."""

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[1]
SCHOOLS_INPUT = ROOT / "data/output/schools_analysis_classified.json"
FSQ_INPUT = Path("/Users/malleswararao/Desktop/foursquare categories/foursquare_bangalore_places.json")
OUTPUT = ROOT / "data/output/schools_analysis_with_foursquare.json"
REPORT = ROOT / "data/output/foursquare_match_report.json"
AUDIT = ROOT / "data/output/foursquare_match_audit.json"

GENERIC = {
    "school", "public", "english", "medium", "high", "higher", "primary", "secondary",
    "academy", "international", "education", "educational", "institution", "institutions",
    "vidyalaya", "vidya", "mandir", "the", "of", "and", "bangalore", "bengaluru",
    "kannada", "convent", "nursery", "lps", "hps", "hs", "eps", "college", "pu",
}
SCHOOL_WORDS = {
    "school", "vidyalaya", "academy", "convent", "primary", "secondary", "high school",
    "nursery", "preschool", "public school", "college", "vidya mandir",
}


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def meaningful_tokens(value):
    return {x for x in normalize(value).split() if x not in GENERIC and len(x) > 1}


def name_similarity(a, b):
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    sequence = SequenceMatcher(None, na, nb).ratio()
    sa, sb = " ".join(sorted(na.split())), " ".join(sorted(nb.split()))
    token_sort = SequenceMatcher(None, sa, sb).ratio()
    ta, tb = meaningful_tokens(a), meaningful_tokens(b)
    overlap = len(ta & tb) / max(1, len(ta | tb))
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(sequence, token_sort, 0.65 * containment + 0.35 * overlap)


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def is_school_candidate(place):
    category = normalize(place.get("fsq_category_labels"))
    name = normalize(place.get("name"))
    education = "education" in category
    name_signal = any(normalize(word) in name for word in SCHOOL_WORDS)
    school_category = any(
        x in category for x in ("primary and secondary school", "private school", "nursery school", "preschool")
    )
    # General education entries are retained only when the name also looks school-like.
    return school_category or (education and name_signal)


def load_places():
    places = []
    raw_count = 0
    with FSQ_INPUT.open() as stream:
        for line in stream:
            raw_count += 1
            try:
                place = json.loads(line)
            except json.JSONDecodeError:
                continue
            if place.get("date_closed") or not is_school_candidate(place):
                continue
            try:
                place["latitude"] = float(place["latitude"])
                place["longitude"] = float(place["longitude"])
            except (TypeError, ValueError):
                continue
            places.append(place)
    return raw_count, places


def evaluate(school, place):
    metadata = school["metadata"]
    location = metadata.get("location") or {}
    lat, lon = location.get("latitude"), location.get("longitude")
    distance = haversine(float(lat), float(lon), place["latitude"], place["longitude"])
    similarity = name_similarity(metadata.get("school_name"), place.get("name"))
    school_name_normalized = normalize(metadata.get("school_name"))
    place_name_normalized = normalize(place.get("name"))
    distinctive_overlap = meaningful_tokens(metadata.get("school_name")) & meaningful_tokens(place.get("name"))
    exact_name = school_name_normalized == place_name_normalized
    school_pin = str(metadata.get("reported_pincode") or metadata.get("searched_pincode") or "")
    place_pin = str(place.get("postcode") or "")
    pincode_match = bool(school_pin and place_pin and school_pin == place_pin)
    address_text = " ".join(
        str(x or "") for x in (metadata.get("address"), location.get("village_or_ward"), school_pin)
    )
    fsq_address = " ".join(
        str(place.get(x) or "") for x in ("address", "locality", "region", "postcode")
    )
    address_similarity = name_similarity(address_text, fsq_address)

    has_distinctive_overlap = bool(distinctive_overlap)
    if exact_name and (distance <= 1000 or pincode_match):
        confidence = "confident"
    elif similarity >= 0.90 and distance <= 500 and has_distinctive_overlap:
        confidence = "confident"
    elif similarity >= 0.80 and distance <= 150 and has_distinctive_overlap:
        confidence = "confident"
    elif similarity >= 0.88 and distance <= 2000 and pincode_match and has_distinctive_overlap:
        confidence = "confident"
    elif similarity >= 0.80 and distance <= 500 and has_distinctive_overlap:
        confidence = "probable"
    elif similarity >= 0.90 and distance <= 1500 and pincode_match and has_distinctive_overlap:
        confidence = "probable"
    else:
        confidence = "rejected"

    distance_score = max(0.0, 1.0 - min(distance, 3000) / 3000)
    score = 0.72 * similarity + 0.18 * distance_score + 0.07 * int(pincode_match) + 0.03 * address_similarity
    return {
        "confidence": confidence,
        "score": round(score, 4),
        "name_similarity": round(similarity, 4),
        "address_similarity": round(address_similarity, 4),
        "distance_meters": round(distance, 1),
        "pincode_match": pincode_match,
        "exact_name": exact_name,
        "distinctive_tokens_shared": sorted(distinctive_overlap),
    }


def main():
    document = json.loads(SCHOOLS_INPUT.read_text())
    raw_count, places = load_places()
    coords = [(p["latitude"], p["longitude"]) for p in places]
    tree = cKDTree(coords)
    statuses = Counter()
    matches = []
    ambiguities = []
    mapped_students = Counter()

    for school in document["schools"]:
        location = school["metadata"].get("location") or {}
        try:
            lat, lon = float(location["latitude"]), float(location["longitude"])
        except (KeyError, TypeError, ValueError):
            school["foursquare"] = {"match_status": "no_coordinates", "place": None}
            statuses["no_coordinates"] += 1
            continue

        # Roughly 3 km latitude/longitude window; exact distance is evaluated later.
        indexes = tree.query_ball_point((lat, lon), r=0.03)
        ranked = []
        for index in indexes:
            result = evaluate(school, places[index])
            if result["confidence"] != "rejected":
                ranked.append((result["score"], index, result))
        ranked.sort(reverse=True)

        if not ranked:
            school["foursquare"] = {"match_status": "unmatched", "place": None}
            statuses["unmatched"] += 1
            continue

        best_score, best_index, best = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else None
        if second_score is not None and best_score - second_score < 0.035:
            status = "ambiguous"
        else:
            status = best["confidence"]
        place = places[best_index]
        place_data = {
            key: place.get(key)
            for key in (
                "fsq_place_id", "name", "latitude", "longitude", "address", "locality", "region",
                "postcode", "tel", "website", "email", "fsq_category_labels", "date_refreshed",
                "placemaker_url",
            )
        }
        school["foursquare"] = {"match_status": status, "match": best, "place": place_data}
        statuses[status] += 1
        if status in {"confident", "probable"}:
            students = (school.get("enrollment") or {}).get("total_students") or 0
            mapped_students[status] += students
            matches.append(
                {
                    "udise_code": school["udise_code"],
                    "school_name": school["metadata"].get("school_name"),
                    "students": students,
                    "status": status,
                    "foursquare": school["foursquare"],
                }
            )
        elif status == "ambiguous":
            ambiguities.append(
                {
                    "udise_code": school["udise_code"],
                    "school_name": school["metadata"].get("school_name"),
                    "best": school["foursquare"],
                    "runner_up_score": round(second_score, 4),
                }
            )

    total = len(document["schools"])
    accepted = statuses["confident"] + statuses["probable"]
    unique_places = len({m["foursquare"]["place"]["fsq_place_id"] for m in matches})
    generated_at = datetime.now(timezone.utc).isoformat()
    document["generated_at"] = generated_at
    document["foursquare_summary"] = {
        "schools": total,
        "raw_foursquare_places": raw_count,
        "school_candidate_places": len(places),
        "confident_matches": statuses["confident"],
        "probable_matches": statuses["probable"],
        "accepted_matches": accepted,
        "unique_foursquare_places_matched": unique_places,
        "accepted_coverage_percent": round(accepted * 100 / total, 2),
        "ambiguous": statuses["ambiguous"],
        "unmatched": statuses["unmatched"],
        "no_coordinates": statuses["no_coordinates"],
        "mapped_students": sum(mapped_students.values()),
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    REPORT.write_text(json.dumps(document["foursquare_summary"], ensure_ascii=False, indent=2) + "\n")
    AUDIT.write_text(
        json.dumps({"matches": matches, "ambiguous": ambiguities}, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(document["foursquare_summary"], indent=2))


if __name__ == "__main__":
    main()
