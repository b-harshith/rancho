#!/usr/bin/env python3
"""Intelligently deduplicate non-UDISE school JSON while preserving genuine branches."""

import csv
import json
import math
import re
from collections import defaultdict
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_JSON = ROOT / "output/unmatched_non_udise_premium_schools_7_cities.json"
OUTPUT_JSON = ROOT / "output/unmatched_non_udise_premium_schools_7_cities_deduped.json"
AUDIT_JSON = ROOT / "output/unmatched_non_udise_duplicate_audit.json"
REVIEW_CSV = ROOT / "output/unmatched_non_udise_duplicate_review.csv"


GENERIC_WORDS = {
    "school", "schools", "international", "global", "public", "academy", "the",
    "senior", "secondary", "high", "higher", "primary", "junior", "college",
    "english", "medium", "world", "campus", "branch", "wing", "new", "old",
    "for", "and", "of", "in", "at",
}


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def norm(text):
    text = clean(text).lower().replace("&amp;", " and ").replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def name_tokens(text):
    return [t for t in norm(text).split() if t and t not in GENERIC_WORDS]


def token_jaccard(a, b):
    ta, tb = set(name_tokens(a)), set(name_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def token_containment(a, b):
    ta, tb = set(name_tokens(a)), set(name_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def name_similarity(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    sort_a = " ".join(sorted(na.split()))
    sort_b = " ".join(sorted(nb.split()))
    token_sort = SequenceMatcher(None, sort_a, sort_b).ratio()
    jac = token_jaccard(a, b)
    contain = token_containment(a, b)
    return max(seq, token_sort, jac, contain * 0.96)


def haversine_m(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371000.0
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def url_values(school):
    urls = school.get("urls") or {}
    return {clean(v).lower() for v in urls.values() if clean(v)}


def same_url(a, b):
    return bool(url_values(a) & url_values(b))


def has_same_place(a, b):
    pa = clean(a.get("google_place_id"))
    pb = clean(b.get("google_place_id"))
    return bool(pa and pb and pa == pb)


def same_addressish(a, b):
    aa, ab = norm(a.get("address")), norm(b.get("address"))
    if aa and ab and len(aa) >= 20 and len(ab) >= 20 and SequenceMatcher(None, aa, ab).ratio() >= 0.94:
        return True
    return False


def duplicate_reason(a, b):
    if clean(a.get("city")) != clean(b.get("city")):
        return None

    distance = haversine_m(a.get("latitude"), a.get("longitude"), b.get("latitude"), b.get("longitude"))
    sim = name_similarity(a.get("name"), b.get("name"))
    jac = token_jaccard(a.get("name"), b.get("name"))
    contain = token_containment(a.get("name"), b.get("name"))
    same_pin = clean(a.get("pincode")) and clean(a.get("pincode")) == clean(b.get("pincode"))

    # Preserve genuine branches: same brand/name across the city should not merge
    # unless coordinates/address say this is probably the same campus. Some source
    # rows reuse a chain-level URL/place result, so far-apart place-id/url matches
    # are deliberately not merged.
    if distance is not None and distance > 1200:
        return None

    if has_same_place(a, b) and (distance is None or distance <= 100 or same_addressish(a, b)) and (sim >= 0.84 or contain >= 0.90):
        return "same_google_place_id"
    if same_url(a, b) and (distance is None or distance <= 120 or same_addressish(a, b)) and (sim >= 0.88 or contain >= 0.90):
        return "same_source_url"

    if same_addressish(a, b) and sim >= 0.96 and jac >= 0.80:
        return "same_or_near_address_and_similar_name"
    if distance is not None and distance <= 25 and (sim >= 0.82 or jac >= 0.45 or contain >= 0.90):
        return "same_coordinate_cluster_and_related_name"
    if distance is not None and distance <= 100 and sim >= 0.94 and (jac >= 0.55 or contain >= 0.90):
        return "very_close_and_high_name_similarity"
    if distance is not None and distance <= 120 and same_pin and sim >= 0.96 and (jac >= 0.55 or contain >= 0.90):
        return "same_pincode_close_and_high_name_similarity"
    if distance is not None and distance <= 80 and contain >= 0.97 and jac >= 0.70:
        return "close_coordinate_and_name_containment"
    return None


class DSU:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def completeness_score(s):
    score = 0
    for key in [
        "google_place_id", "address", "pincode", "boards", "fee_reference",
        "fee_text", "area", "zone", "category", "coordinate_source",
    ]:
        if clean(s.get(key)):
            score += 1
    urls = s.get("urls") or {}
    score += sum(1 for v in urls.values() if clean(v))
    if s.get("top_150_premium_chain_above_1L"):
        score += 3
    if s.get("fee_above_1L"):
        score += 2
    if s.get("original_student_count"):
        score += 1
    return score


def choose_representative(members):
    return max(
        members,
        key=lambda s: (
            completeness_score(s),
            s.get("fee_reference") or 0,
            bool(clean(s.get("google_place_id"))),
            clean(s.get("name")),
        ),
    )


def merge_records(members, group_id):
    rep = deepcopy(choose_representative(members))
    duplicate_ids = [m.get("id") for m in members if m.get("id") != rep.get("id")]
    source_names = sorted({clean(m.get("name")) for m in members if clean(m.get("name"))})
    source_datasets = sorted({clean(m.get("source_dataset")) for m in members if clean(m.get("source_dataset"))})
    source_urls = defaultdict(list)
    for m in members:
        for k, v in (m.get("urls") or {}).items():
            if clean(v) and clean(v) not in source_urls[k]:
                source_urls[k].append(clean(v))

    rep["duplicate_status"] = "representative" if len(members) > 1 else "unique"
    rep["duplicate_group_id"] = group_id if len(members) > 1 else None
    rep["duplicate_listing_count"] = len(members)
    rep["duplicate_source_ids"] = duplicate_ids
    rep["duplicate_source_names"] = source_names
    rep["source_datasets_merged"] = source_datasets
    rep["all_source_urls"] = dict(source_urls)
    return rep


def candidate_pairs(schools):
    by_city = defaultdict(list)
    by_place = defaultdict(list)
    by_url = defaultdict(list)
    by_pin = defaultdict(list)

    for i, school in enumerate(schools):
        city = clean(school.get("city"))
        by_city[city].append(i)
        place = clean(school.get("google_place_id"))
        if place:
            by_place[place].append(i)
        for url in url_values(school):
            by_url[url].append(i)
        pin = clean(school.get("pincode"))
        if pin:
            by_pin[(city, pin)].append(i)

    pairs = set()
    for bucket in list(by_place.values()) + list(by_url.values()) + list(by_pin.values()):
        if len(bucket) < 2:
            continue
        for pos, i in enumerate(bucket):
            for j in bucket[pos + 1:]:
                pairs.add((min(i, j), max(i, j)))

    # Nearby coordinate buckets, roughly 0.005 degrees ~ 550m lat.
    grid = defaultdict(list)
    for i, s in enumerate(schools):
        if s.get("latitude") is None or s.get("longitude") is None:
            continue
        key = (clean(s.get("city")), round(float(s["latitude"]) / 0.005), round(float(s["longitude"]) / 0.005))
        grid[key].append(i)

    neighbor_offsets = [-1, 0, 1]
    for (city, gx, gy), bucket in list(grid.items()):
        candidates = []
        for dx in neighbor_offsets:
            for dy in neighbor_offsets:
                candidates.extend(grid.get((city, gx + dx, gy + dy), []))
        candidates = sorted(set(candidates))
        for pos, i in enumerate(candidates):
            for j in candidates[pos + 1:]:
                pairs.add((min(i, j), max(i, j)))

    return sorted(pairs)


def main():
    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    schools = data["schools"]
    dsu = DSU(len(schools))
    pair_audit = []

    for i, j in candidate_pairs(schools):
        reason = duplicate_reason(schools[i], schools[j])
        if not reason:
            continue
        dsu.union(i, j)
        pair_audit.append({
            "left_id": schools[i].get("id"),
            "right_id": schools[j].get("id"),
            "left_name": schools[i].get("name"),
            "right_name": schools[j].get("name"),
            "city": schools[i].get("city"),
            "distance_m": haversine_m(schools[i].get("latitude"), schools[i].get("longitude"), schools[j].get("latitude"), schools[j].get("longitude")),
            "name_similarity": name_similarity(schools[i].get("name"), schools[j].get("name")),
            "reason": reason,
        })

    groups = defaultdict(list)
    for idx, school in enumerate(schools):
        groups[dsu.find(idx)].append(school)

    deduped = []
    duplicate_groups = []
    group_num = 1
    for members in groups.values():
        group_id = None
        if len(members) > 1:
            group_id = f"dup_{group_num:04d}"
            group_num += 1
            rep = choose_representative(members)
            duplicate_groups.append({
                "duplicate_group_id": group_id,
                "representative_id": rep.get("id"),
                "representative_name": rep.get("name"),
                "city": rep.get("city"),
                "member_count": len(members),
                "members": [
                    {
                        "id": m.get("id"),
                        "name": m.get("name"),
                        "area": m.get("area"),
                        "pincode": m.get("pincode"),
                        "latitude": m.get("latitude"),
                        "longitude": m.get("longitude"),
                        "google_place_id": m.get("google_place_id"),
                        "fee_reference": m.get("fee_reference"),
                        "source_dataset": m.get("source_dataset"),
                    }
                    for m in members
                ],
            })
        deduped.append(merge_records(members, group_id or ""))

    deduped.sort(key=lambda s: (
        s.get("city") or "",
        not s.get("top_150_premium_chain_above_1L"),
        -(s.get("fee_reference") or 0),
        s.get("name") or "",
    ))

    out = deepcopy(data)
    out["metadata"]["deduplication"] = {
        "input_count": len(schools),
        "output_count": len(deduped),
        "removed_duplicate_listings": len(schools) - len(deduped),
        "duplicate_groups": len(duplicate_groups),
        "method": (
            "Merged exact same Google Place ID/source URL and near-campus fuzzy duplicates. "
            "Same-brand schools farther than 1.2km are preserved as branches unless place ID/URL matches."
        ),
    }
    out["metadata"]["counts"]["schools_before_deduplication"] = len(schools)
    out["metadata"]["counts"]["schools"] = len(deduped)
    out["metadata"]["counts"]["top_150_premium_chain_above_1L"] = int(
        sum(1 for s in deduped if s.get("top_150_premium_chain_above_1L"))
    )
    out["metadata"]["counts"]["fee_above_1L"] = int(sum(1 for s in deduped if s.get("fee_above_1L")))
    city_counts = defaultdict(int)
    for school in deduped:
        city_counts[school.get("city")] += 1
    out["metadata"]["counts"]["by_city"] = dict(sorted(city_counts.items()))
    out["schools"] = deduped

    OUTPUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    AUDIT_JSON.write_text(json.dumps({
        "summary": out["metadata"]["deduplication"],
        "duplicate_groups": duplicate_groups,
        "duplicate_pairs": pair_audit,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    with REVIEW_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "duplicate_group_id", "representative_name", "city", "member_count",
            "member_name", "area", "pincode", "latitude", "longitude",
            "google_place_id", "fee_reference", "source_dataset",
        ])
        writer.writeheader()
        for group in duplicate_groups:
            for member in group["members"]:
                writer.writerow({
                    "duplicate_group_id": group["duplicate_group_id"],
                    "representative_name": group["representative_name"],
                    "city": group["city"],
                    "member_count": group["member_count"],
                    "member_name": member["name"],
                    "area": member["area"],
                    "pincode": member["pincode"],
                    "latitude": member["latitude"],
                    "longitude": member["longitude"],
                    "google_place_id": member["google_place_id"],
                    "fee_reference": member["fee_reference"],
                    "source_dataset": member["source_dataset"],
                })

    print(OUTPUT_JSON)
    print(json.dumps(out["metadata"]["deduplication"], indent=2))
    print("review_csv", REVIEW_CSV)
    print("audit_json", AUDIT_JSON)


if __name__ == "__main__":
    main()
