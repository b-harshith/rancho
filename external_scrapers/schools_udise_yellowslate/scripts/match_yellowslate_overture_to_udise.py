#!/usr/bin/env python3
"""Use local Overture data to geolocate YellowSlate schools and match to UDISE.

Pipeline:
1. Read local Overture GeoJSON export and cache education/school candidates.
2. Match each YellowSlate school to the best Overture place/land-use candidate.
3. Use the Overture coordinate first, then name/pincode/board/area evidence, to
   match YellowSlate fee data onto cleaned UDISE schools.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERTURE = Path("/Users/malleswararao/Desktop/CatchmentIQ/overture/bangalore_no_buildings.geojson")
UDISE_INPUT = ROOT / "data/output/schools_analysis_bangalore_cleaned.json"
YELLOWSLATE_INPUT = ROOT / "data/output/yellowslate/yellowslate_schools_with_locations.json"
OUT_DIR = ROOT / "data/output/yellowslate"
OVERTURE_CANDIDATES = OUT_DIR / "overture_bangalore_school_candidates.json"
YELLOWSLATE_OVERTURE = OUT_DIR / "yellowslate_with_overture_locations.json"
OUTPUT = ROOT / "data/output/schools_analysis_bangalore_cleaned_with_yellowslate_overture_fees.json"
REPORT = OUT_DIR / "yellowslate_udise_overture_match_report.json"
AUDIT = OUT_DIR / "yellowslate_udise_overture_match_audit.json"

GENERIC = {
    "school", "public", "english", "medium", "high", "higher", "primary", "secondary",
    "academy", "international", "education", "educational", "institution", "institutions",
    "vidyalaya", "vidya", "mandir", "the", "of", "and", "bangalore", "bengaluru",
    "kannada", "convent", "nursery", "lps", "hps", "hs", "eps", "college", "pu",
    "pre", "preschool", "kids", "kidzee", "little", "st", "sri", "shree", "new",
    "matric", "centre", "center", "learning", "residential", "global", "national",
    "state", "board",
}
REPLACEMENTS = {
    "sch": "school", "ps": "public school", "pub": "public", "hps": "higher primary school",
    "lps": "lower primary school", "hs": "high school", "intl": "international",
    "jnr": "junior", "mont": "montessori", "nps": "national public school",
    "dps": "delhi public school", "rvk": "rashtrotthana vidya kendra",
}
BRACKET_RANK = {"under_30k": 1, "30k_50k": 2, "50k_70k": 3, "70k_1l": 4, "1l_2l": 5, "above_2l": 6}


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    out = []
    for token in re.findall(r"[a-z0-9]+", text):
        out.extend(REPLACEMENTS.get(token, token).split())
    return " ".join(out)


def tokens(value: Any, *, keep_generic: bool = False) -> set[str]:
    words = normalize(value).split()
    return {w for w in words if len(w) > 1 and (keep_generic or w not in GENERIC)}


def sim(a: Any, b: Any) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    sort = SequenceMatcher(None, " ".join(sorted(na.split())), " ".join(sorted(nb.split()))).ratio()
    ta, tb = tokens(a), tokens(b)
    overlap = len(ta & tb) / max(1, len(ta | tb))
    contain = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(seq, sort, 0.72 * contain + 0.28 * overlap)


def jaccard(a: Any, b: Any, *, keep_generic: bool = False) -> float:
    ta, tb = tokens(a, keep_generic=keep_generic), tokens(b, keep_generic=keep_generic)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def pin(value: Any) -> str | None:
    m = re.search(r"\b([1-9]\d{5})\b", str(value or ""))
    return m.group(1) if m else None


def parse_jsonish(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def primary_name(names: Any) -> str | None:
    obj = parse_jsonish(names, {})
    if isinstance(obj, dict):
        return obj.get("primary")
    return None


def alternate_names(names: Any) -> list[str]:
    obj = parse_jsonish(names, {})
    out = []
    if isinstance(obj, dict):
        if obj.get("primary"):
            out.append(obj["primary"])
        for rule in obj.get("rules") or []:
            if isinstance(rule, dict) and rule.get("value"):
                out.append(rule["value"])
    return list(dict.fromkeys(out))


def address_text(addresses: Any) -> str:
    arr = parse_jsonish(addresses, [])
    if not isinstance(arr, list):
        return str(addresses or "")
    chunks = []
    for addr in arr:
        if isinstance(addr, dict):
            chunks.extend(str(addr.get(k) or "") for k in ("freeform", "locality", "postcode", "region", "country"))
    return " ".join(chunks)


def category_text(categories: Any, basic: Any) -> str:
    obj = parse_jsonish(categories, {})
    parts = [str(basic or "")]
    if isinstance(obj, dict):
        parts.append(str(obj.get("primary") or ""))
        parts.extend(str(x) for x in (obj.get("alternate") or []))
    else:
        parts.append(str(categories or ""))
    return " ".join(parts)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dist_score(km: float | None, source: str | None) -> float:
    if km is None:
        return 0.0
    if source == "foursquare":
        if km <= 0.15: return 1.0
        if km <= 0.5: return 0.9
        if km <= 1.0: return 0.72
        if km <= 2.0: return 0.45
        return 0.0
    if km <= 0.5: return 0.95
    if km <= 1.5: return 0.82
    if km <= 3.0: return 0.66
    if km <= 5.0: return 0.44
    if km <= 8.0: return 0.2
    return 0.0


def board_tokens(value: Any) -> set[str]:
    text = normalize(value)
    out = set()
    if "cbse" in text: out.add("CBSE")
    if "icse" in text or "cisce" in text or "isc" in text: out.add("CISCE")
    if "igcse" in text or "cambridge" in text or "caie" in text or re.search(r"\bib\b", text): out.add("International")
    if "state" in text or "kseeb" in text or "sslc" in text: out.add("State Board")
    return out


def school_boards(school: dict[str, Any]) -> set[str]:
    dims = school.get("analysis_dimensions") or {}
    boards = set(dims.get("boards_present") or [])
    boards |= board_tokens(dims.get("board_group"))
    boards |= board_tokens((school.get("board_classification") or {}).get("board_group"))
    aff = (school.get("metadata") or {}).get("board_affiliation") or {}
    boards |= board_tokens(" ".join(str(v or "") for v in aff.values()))
    return boards


def school_loc_text(school: dict[str, Any]) -> str:
    meta = school.get("metadata") or {}
    loc = meta.get("location") or {}
    return " ".join(str(x or "") for x in (
        meta.get("address"), meta.get("reported_pincode"), meta.get("searched_pincode"),
        loc.get("village_or_ward"), loc.get("cluster"), loc.get("block"), loc.get("district"), loc.get("state"),
    ))


def y_loc_text(y: dict[str, Any]) -> str:
    loc = y.get("school_location") or {}
    return " ".join(str(x or "") for x in (y.get("area"), loc.get("address"), loc.get("pincode")))


def extract_overture(path: Path, force: bool = False) -> list[dict[str, Any]]:
    if OVERTURE_CANDIDATES.exists() and not force:
        return json.loads(OVERTURE_CANDIDATES.read_text())
    con = duckdb.connect()
    con.execute("LOAD spatial")
    pattern = ".*(school|education|educational|college|kindergarten|preschool|montessori|academy|vidyalaya|vidya|university|tutorial|tuition).*"
    rows = con.execute(
        """
        SELECT id, layer_type, categories, names, addresses, websites, phones, basic_category,
               ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat
        FROM ST_Read(?)
        WHERE lower(coalesce(categories,'') || ' ' || coalesce(names,'') || ' ' || coalesce(basic_category,'')) SIMILAR TO ?
        """,
        [str(path), pattern],
    ).fetchall()
    cols = [d[0] for d in con.description]
    out = []
    for row in rows:
        raw = dict(zip(cols, row))
        names = alternate_names(raw["names"])
        addr = address_text(raw["addresses"])
        cats = category_text(raw["categories"], raw["basic_category"])
        out.append({
            "overture_id": raw["id"],
            "layer_type": raw["layer_type"],
            "name": primary_name(raw["names"]),
            "alternate_names": names,
            "categories_text": cats,
            "address_text": addr,
            "pincode": pin(addr),
            "websites": raw["websites"] or [],
            "phones": raw["phones"] or [],
            "latitude": raw["lat"],
            "longitude": raw["lon"],
        })
    OVERTURE_CANDIDATES.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return out


def prepare_overture(cands: list[dict[str, Any]]) -> dict[str, Any]:
    token_index: dict[str, set[int]] = defaultdict(set)
    pin_index: dict[str, set[int]] = defaultdict(set)
    for i, c in enumerate(cands):
        c["_tokens"] = tokens(" ".join(c.get("alternate_names") or [c.get("name") or ""]))
        c["_search_text"] = " ".join([c.get("name") or "", " ".join(c.get("alternate_names") or []), c.get("address_text") or "", c.get("categories_text") or ""])
        for t in c["_tokens"]:
            token_index[t].add(i)
        if c.get("pincode"):
            pin_index[c["pincode"]].add(i)
    return {"token_index": token_index, "pin_index": pin_index}


def resolve_overture(y_schools: list[dict[str, Any]], cands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prep = prepare_overture(cands)
    status = Counter()
    enriched = []
    audit = []
    for y_idx, y in enumerate(y_schools):
        ypin = (y.get("school_location") or {}).get("pincode")
        cand_ids = set()
        if ypin:
            cand_ids |= prep["pin_index"].get(ypin, set())
        hits = [(t, prep["token_index"].get(t, set())) for t in tokens(y.get("school_name"))]
        hits = [(t, h) for t, h in hits if h]
        hits.sort(key=lambda x: len(x[1]))
        for _, h in hits[:6]:
            if len(h) <= 1200:
                cand_ids |= h
        ranked = []
        for ci in cand_ids:
            c = cands[ci]
            nscore = max(sim(y.get("school_name"), nm) for nm in (c.get("alternate_names") or [c.get("name") or ""]))
            pmatch = bool(ypin and ypin == c.get("pincode"))
            ascore = max(sim(y.get("area"), c.get("address_text")) if y.get("area") else 0.0, jaccard(y_loc_text(y), c["_search_text"], keep_generic=True))
            shared = tokens(y.get("school_name")) & c["_tokens"]
            cat_school = bool(re.search(r"school|preschool|kindergarten|montessori|education", c.get("categories_text") or "", re.I))
            score = 0.72 * nscore + 0.11 * int(pmatch) + 0.10 * ascore + 0.04 * int(cat_school) + 0.03 * min(1, len(shared) / 2)
            acceptable = (
                (nscore >= 0.93)
                or (nscore >= 0.84 and pmatch and shared)
                or (nscore >= 0.80 and pmatch and ascore >= 0.12 and shared)
                or (nscore >= 0.86 and ascore >= 0.30 and len(shared) >= 2)
            )
            if acceptable:
                ranked.append((score, ci, nscore, pmatch, ascore, sorted(shared)))
        ranked.sort(reverse=True)
        item = copy.deepcopy(y)
        if ranked:
            best = ranked[0]
            runner = ranked[1] if len(ranked) > 1 else None
            strong_branch_evidence = (best[2] >= 0.93 and best[3]) or (best[2] >= 0.97 and best[4] >= 0.35)
            ambiguous = bool(runner and best[0] - runner[0] < 0.035 and not strong_branch_evidence)
            if not ambiguous:
                c = cands[best[1]]
                item["overture_location"] = {
                    "status": "matched",
                    "overture_id": c["overture_id"],
                    "name": c["name"],
                    "alternate_names": c["alternate_names"],
                    "categories_text": c["categories_text"],
                    "address_text": c["address_text"],
                    "pincode": c["pincode"],
                    "latitude": c["latitude"],
                    "longitude": c["longitude"],
                    "phones": c.get("phones") or [],
                    "websites": c.get("websites") or [],
                    "match": {
                        "confidence": round(best[0], 4),
                        "name_similarity": round(best[2], 4),
                        "pincode_match": best[3],
                        "area_similarity": round(best[4], 4),
                        "shared_distinctive_tokens": best[5],
                        "runner_up_delta": round(best[0] - runner[0], 4) if runner else None,
                    },
                }
                status["matched"] += 1
            else:
                item["overture_location"] = {"status": "ambiguous", "best_candidate": cands[best[1]]["name"]}
                status[item["overture_location"]["status"]] += 1
        else:
            item["overture_location"] = {"status": "unmatched"}
            status["unmatched"] += 1
        audit.append({"yellowslate_name": y.get("school_name"), "yellowslate_url": y.get("school_url"), "overture_location": item["overture_location"]})
        enriched.append(item)
    YELLOWSLATE_OVERTURE.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n")
    return enriched, {"overture_resolution_counts": dict(status), "audit": audit}


def prepare_udise(schools: list[dict[str, Any]]) -> dict[str, Any]:
    token_index: dict[str, set[int]] = defaultdict(set)
    pin_index: dict[str, set[int]] = defaultdict(set)
    recs = []
    for i, s in enumerate(schools):
        meta = s.get("metadata") or {}
        loc = meta.get("location") or {}
        rec = {
            "name": meta.get("school_name"),
            "tokens": tokens(meta.get("school_name")),
            "loc_text": school_loc_text(s),
            "boards": school_boards(s),
            "lat": loc.get("latitude"),
            "lon": loc.get("longitude"),
            "coord_source": loc.get("coordinate_source"),
            "pins": {pin(meta.get("reported_pincode")), pin(meta.get("searched_pincode"))} - {None},
        }
        recs.append(rec)
        for t in rec["tokens"]:
            token_index[t].add(i)
        for p in rec["pins"]:
            pin_index[p].add(i)
    return {"recs": recs, "token_index": token_index, "pin_index": pin_index}


def evaluate_udise(y: dict[str, Any], s: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    oloc = y.get("overture_location") or {}
    ylat, ylon = oloc.get("latitude"), oloc.get("longitude")
    km = None
    if ylat is not None and ylon is not None and rec["lat"] is not None and rec["lon"] is not None:
        km = haversine(float(ylat), float(ylon), float(rec["lat"]), float(rec["lon"]))
    dscore = dist_score(km, rec["coord_source"])
    ypin = oloc.get("pincode") or (y.get("school_location") or {}).get("pincode")
    pmatch = bool(ypin and ypin in rec["pins"])
    pconflict = bool(ypin and rec["pins"] and not pmatch)
    nscore = sim(y.get("school_name"), rec["name"])
    ascore = max(sim(y.get("area"), rec["loc_text"]) if y.get("area") else 0.0, jaccard(y_loc_text(y), rec["loc_text"], keep_generic=True))
    yboards = board_tokens(y.get("board_text"))
    bmatch = bool(yboards and rec["boards"] and yboards & rec["boards"])
    bconflict = bool(yboards and rec["boards"] and not (yboards & rec["boards"]))
    shared = tokens(y.get("school_name")) & rec["tokens"]
    geo_ok = oloc.get("status") == "matched"
    score = 0.44 * dscore + 0.34 * nscore + 0.10 * int(pmatch) + 0.06 * ascore + 0.04 * int(bmatch) + 0.02 * min(1, len(shared) / 2)
    acceptable = False
    method = None
    if geo_ok:
        if km is not None and km <= 0.35 and nscore >= 0.70 and shared:
            acceptable, method = True, "overture_geo_near+name"
        elif km is not None and km <= 1.5 and nscore >= 0.82 and shared:
            acceptable, method = True, "overture_geo_close+name"
        elif km is not None and km <= 4.0 and pmatch and nscore >= 0.74 and shared:
            acceptable, method = True, "overture_geo+pincode+name"
        elif km is not None and km <= 4.0 and nscore >= 0.84 and ascore >= 0.25 and len(shared) >= 2:
            acceptable, method = True, "overture_geo+name+area"
    else:
        if nscore >= 0.95:
            acceptable, method = True, "fallback:name_strong"
        elif nscore >= 0.90 and ascore >= 0.30 and len(shared) >= 2:
            acceptable, method = True, "fallback:name+area"
    if bconflict and not pmatch and nscore < 0.93:
        acceptable = False
    if pconflict and not pmatch and len(shared) < 2:
        acceptable = False
    return {
        "score": score, "acceptable": acceptable, "method": method, "distance_km": km,
        "distance_score": dscore, "udise_coordinate_source": rec["coord_source"],
        "name_similarity": nscore, "area_similarity": ascore, "pincode_match": pmatch,
        "pincode_conflict": pconflict, "board_match": bmatch, "board_conflict": bconflict,
        "shared_distinctive_tokens": sorted(shared), "has_overture_location": geo_ok,
    }


def compact(edge: dict[str, Any] | None) -> dict[str, Any] | None:
    if not edge: return None
    return {
        "school_index": edge["school_index"], "score": round(edge["score"], 4), "method": edge["method"],
        "distance_km": round(edge["distance_km"], 4) if edge.get("distance_km") is not None else None,
        "distance_score": round(edge["distance_score"], 4),
        "udise_coordinate_source": edge["udise_coordinate_source"],
        "name_similarity": round(edge["name_similarity"], 4), "area_similarity": round(edge["area_similarity"], 4),
        "pincode_match": edge["pincode_match"], "pincode_conflict": edge["pincode_conflict"],
        "board_match": edge["board_match"], "board_conflict": edge["board_conflict"],
        "shared_distinctive_tokens": edge["shared_distinctive_tokens"],
        "runner_up_delta": round(edge["runner_up_delta"], 4) if edge.get("runner_up_delta") is not None else None,
    }


def match_to_udise(doc: dict[str, Any], y_schools: list[dict[str, Any]], overture_report: dict[str, Any]) -> dict[str, Any]:
    schools = copy.deepcopy(doc["schools"])
    prep = prepare_udise(schools)
    edges = []
    diagnostics = []
    for yi, y in enumerate(y_schools):
        cand = set()
        oloc = y.get("overture_location") or {}
        ylat, ylon = oloc.get("latitude"), oloc.get("longitude")
        ypin = oloc.get("pincode") or (y.get("school_location") or {}).get("pincode")
        if ypin: cand |= prep["pin_index"].get(ypin, set())
        if ylat is not None and ylon is not None:
            for si, rec in enumerate(prep["recs"]):
                # Only use pure geo-near expansion for high-quality UDISE
                # coordinates. Most cleaned UDISE coordinates are pincode
                # centroids, which are useful as supporting evidence but too
                # broad for candidate generation.
                if rec["coord_source"] != "foursquare":
                    continue
                if rec["lat"] is not None and rec["lon"] is not None and haversine(float(ylat), float(ylon), float(rec["lat"]), float(rec["lon"])) <= 3:
                    cand.add(si)
        hits = [(t, prep["token_index"].get(t, set())) for t in tokens(y.get("school_name"))]
        hits = [(t, h) for t, h in hits if h]
        hits.sort(key=lambda x: len(x[1]))
        for _, h in hits[:5]:
            if len(h) <= 1000: cand |= h
        ranked = []
        for si in cand:
            m = evaluate_udise(y, schools[si], prep["recs"][si])
            if m["acceptable"]:
                ranked.append({"yellowslate_index": yi, "school_index": si, **m})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        if ranked:
            best, runner = ranked[0], ranked[1] if len(ranked) > 1 else None
            best["runner_up_delta"] = best["score"] - runner["score"] if runner else None
            edges.append(best)
            diagnostics.append({"best": compact(best), "runner_up": compact(runner) if runner else None})
        else:
            diagnostics.append({"best": None})

    by_y: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in edges: by_y[e["yellowslate_index"]].append(e)
    eligible, ambiguous = [], {}
    for yi, es in by_y.items():
        es.sort(key=lambda x: x["score"], reverse=True)
        best, runner = es[0], es[1] if len(es) > 1 else None
        gap = 0.035 if best["has_overture_location"] else 0.045
        if runner and best["score"] - runner["score"] < gap:
            ambiguous[yi] = "close competing UDISE candidates"
        else:
            eligible.append(best)
    eligible.sort(key=lambda x: x["score"], reverse=True)
    selected, used_y, used_s = [], set(), set()
    for e in eligible:
        if e["yellowslate_index"] in used_y: continue
        if e["school_index"] in used_s:
            ambiguous[e["yellowslate_index"]] = "UDISE target already claimed by stronger YellowSlate match"
            continue
        selected.append(e); used_y.add(e["yellowslate_index"]); used_s.add(e["school_index"])

    matched_by_y = {e["yellowslate_index"]: e for e in selected}
    matches, unmatched = [], []
    students = 0
    for e in selected:
        y, s = y_schools[e["yellowslate_index"]], schools[e["school_index"]]
        fee = y.get("fee") or {}
        key = fee.get("assigned_bracket_key")
        s["yellowslate_fee"] = {
            "source": "YellowSlate+Overture", "school_name": y.get("school_name"), "school_url": y.get("school_url"),
            "board": y.get("board_text"), "area": y.get("area"), "location": y.get("school_location"),
            "overture_location": y.get("overture_location"), "fee_text": fee.get("fee_text"),
            "min_fee": fee.get("min_fee"), "max_fee": fee.get("max_fee"),
            "fee_category_key": key, "fee_category_label": fee.get("assigned_bracket_label"),
            "pricing_band_key": key, "pricing_band_name": fee.get("assigned_bracket_label"),
            "pricing_band_rank": BRACKET_RANK.get(key), "match": {k: v for k, v in compact(e).items() if k != "school_index"},
        }
        students += int((s.get("enrollment") or {}).get("total_students") or 0)
        matches.append({
            "udise_code": s.get("udise_code"), "udise_name": (s.get("metadata") or {}).get("school_name"),
            "udise_location": (s.get("metadata") or {}).get("location"), "yellowslate_name": y.get("school_name"),
            "yellowslate_url": y.get("school_url"), "overture_location": y.get("overture_location"), **compact(e),
        })
    counts = Counter()
    for yi, y in enumerate(y_schools):
        if yi in matched_by_y:
            counts["matched"] += 1; continue
        status = "ambiguous" if yi in ambiguous else "unmatched"
        counts[status] += 1
        best = diagnostics[yi].get("best")
        if best and best.get("school_index") is not None:
            s = schools[best["school_index"]]
            best = {**best, "udise_code": s.get("udise_code"), "udise_name": (s.get("metadata") or {}).get("school_name")}
        unmatched.append({"status": status, "reason": ambiguous.get(yi, "no candidate passed thresholds"), "yellowslate": y, "best_candidate": best})
    methods = Counter(e["method"] for e in selected)
    fee_counts = Counter(s.get("yellowslate_fee", {}).get("pricing_band_key") for s in schools if s.get("yellowslate_fee"))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "udise_schools": len(schools),
        "yellowslate_unique_schools": len(y_schools), **{k: v for k, v in overture_report.items() if k != "audit"},
        "matched_schools": counts["matched"],
        "matched_from_overture_location": sum(y_schools[e["yellowslate_index"]].get("overture_location", {}).get("status") == "matched" for e in selected),
        "match_coverage_of_udise_percent": round(counts["matched"] * 100 / len(schools), 2),
        "match_coverage_of_yellowslate_percent": round(counts["matched"] * 100 / len(y_schools), 2),
        "matched_students": students, "total_students": doc["summary"]["students"],
        "matched_student_coverage_percent": round(students * 100 / doc["summary"]["students"], 2),
        "unmatched_yellowslate_schools": counts["unmatched"], "ambiguous_yellowslate_schools": counts["ambiguous"],
        "match_methods": dict(methods.most_common()),
        "pricing_band_counts": {k: fee_counts.get(k, 0) for k in sorted(BRACKET_RANK, key=BRACKET_RANK.get)},
    }
    out = copy.deepcopy(doc); out["schools"] = schools; out["generated_at"] = report["generated_at"]; out["yellowslate_overture_fee_coverage"] = report
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    AUDIT.write_text(json.dumps({"report": report, "matches": matches, "unmatched_or_ambiguous": unmatched, "overture_resolution_audit": overture_report.get("audit", [])}, ensure_ascii=False, indent=2) + "\n")
    return report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--overture", type=Path, default=DEFAULT_OVERTURE)
    p.add_argument("--force-extract", action="store_true")
    p.add_argument("--force-resolve-overture", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cands = extract_overture(args.overture, force=args.force_extract)
    print(f"Overture candidates: {len(cands)}")
    if YELLOWSLATE_OVERTURE.exists() and not args.force_resolve_overture:
        y_enriched = json.loads(YELLOWSLATE_OVERTURE.read_text())
        counts = Counter((item.get("overture_location") or {}).get("status") or "missing" for item in y_enriched)
        overture_report = {"overture_resolution_counts": dict(counts), "audit": []}
        print("Using cached YellowSlate→Overture resolution")
    else:
        y = json.loads(YELLOWSLATE_INPUT.read_text())
        y_enriched, overture_report = resolve_overture(y, cands)
    doc = json.loads(UDISE_INPUT.read_text())
    report = match_to_udise(doc, y_enriched, overture_report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
