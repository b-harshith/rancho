#!/usr/bin/env python3
"""Prepare SEZ-proximate office listings for the web platform.

This does not touch the TAM / affluence scoring model. It only spatially joins
the supplied office listings into existing SEZ boundaries/proximity buffers and
H3 cells.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import h3
from shapely.geometry import Point, shape
from shapely.prepared import prep
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[2]
OFFICES_PATH = ROOT / "bangalore_office_listings.json"
SEZ_PATH = ROOT / "web_platform" / "public" / "data" / "sez_zones.geojson"
HEXES_PATH = ROOT / "web_platform" / "public" / "data" / "hexes.geojson"
OUT_PATH = ROOT / "web_platform" / "public" / "data" / "sez_offices.json"
SUMMARY_PATH = ROOT / "DATA" / "audits" / "sez_office_listings_summary.json"
PROXIMITY_BUFFER_KM = 2.0
PROJECTION_ORIGIN_LAT = 12.9716
PROJECTION_ORIGIN_LON = 77.5946


KNOWN_GLOBAL_ANCHORS = {
    "google", "microsoft", "amazon", "aws", "apple", "meta", "facebook", "oracle",
    "sap", "ibm", "intel", "qualcomm", "nvidia", "amd", "broadcom", "cisco",
    "adobe", "salesforce", "vmware", "dell", "hewlett packard", "hp", "hpe",
    "samsung", "sony", "ericsson", "nokia", "siemens", "bosch", "ge",
    "general electric", "honeywell", "philips", "abb", "schneider", "unilever",
    "walmart", "target", "lowe", "tesco", "maersk", "shell", "boeing",
    "airbus", "mercedes", "toyota", "honda", "goldman sachs", "jp morgan",
    "jpmorgan", "morgan stanley", "hsbc", "citi", "citibank", "deutsche bank",
    "barclays", "standard chartered", "visa", "mastercard", "paypal",
    "thomson reuters", "reuters", "ernst young", "ey", "deloitte", "kpmg",
    "pwc", "accenture", "capgemini", "cognizant", "genpact", "diageo",
    "coca cola", "indegene", "uber", "atlassian", "stripe", "zoom", "netflix",
    "linkedin", "github", "intuit", "servicenow", "workday", "snowflake",
    "twilio", "splunk", "netapp", "synopsys", "cadence", "arm", "nxp",
    "infineon", "micron", "applied materials", "asml", "kla", "lam research",
    "juniper", "f5", "palo alto", "fortinet", "crowdstrike", "okta", "cloudflare",
    "akamai", "citrix", "tibco", "informatica", "teradata", "alteryx", "mathworks",
    "fidelity", "wellsfargo", "wells fargo", "ubs", "credit suisse", "bny mellon",
    "state street", "northern trust", "american express", "amex", "capital one",
    "discover", "allianz", "axa", "metlife", "prudential", "societe generale",
    "bnp paribas", "rbs", "natwest", "lloyds", "nomura", "daiwa", "mufg", "smbc",
    "mizuho", "macquarie", "anz", "westpac", "nab", "mckinsey", "boston consulting",
    "bcg", "bain", "mercer", "willis towers", "wtw", "aon", "marsh", "gartner",
    "idc", "forrester", "avaya", "polycom", "alcatel", "lenovo", "asus", "acer",
    "blackrock", "vanguard", "schwab", "charles schwab", "franklin templeton",
    "citadel", "point72", "two sigma", "millennium", "worldpay", "fiserv", "fis",
    "equifax", "experian", "transunion", "moody", "moodys", "sp global", "bloomberg",
    "interactive brokers", "synchrony", "pnc", "bmo", "td bank", "scotiabank",
    "databricks", "confluent", "hashicorp", "elastic", "mongodb", "neo4j", "redis",
    "cloudera", "autodesk", "ptc", "ansys", "unity", "epic games", "ea",
    "electronic arts", "spotify", "logitech", "razer", "texas instruments",
    "analog devices", "skyworks", "qorvo", "stmicroelectronics", "stmicro",
    "renesas", "on semi", "microchip", "marvell", "realtek", "mediatek", "unisoc",
    "tsmc", "globalfoundries", "seagate", "western digital", "sandisk", "kingston",
    "netgear", "tp-link", "d-link", "arista", "extreme networks", "ciena",
    "infinera", "keysight", "rohde schwarz", "tektronix", "fluke", "national instruments",
    "johnson and johnson", "j and j", "j&j", "pfizer", "roche", "novartis", "abbvie",
    "merck", "bristol myers squibb", "bms", "astrazeneca", "gsk", "glaxosmithkline",
    "sanofi", "eli lilly", "amgen", "gilead", "bayer", "abbott", "medtronic",
    "stryker", "boston scientific", "philips healthcare", "siemens healthineers",
    "ge healthcare", "illumina", "thermo fisher", "danaher", "agilent", "waters",
    "optum", "unitedhealth", "unitedhealthcare", "cvs", "cvs health", "aetna",
    "cigna", "humana", "elevance", "anthem", "centene", "iqvia", "syneos",
    "emerson", "rockwell", "john deere", "caterpillar", "cummins", "eaton",
    "parker hannifin", "danfoss", "yokogawa", "hitachi", "toshiba", "mitsubishi",
    "komatsu", "kubota", "yanmar", "nissan", "mazda", "subaru", "suzuki", "yamaha",
    "bmw", "volkswagen", "audi", "porsche", "volvo", "scania", "renault", "peugeot",
    "citroen", "fiat", "ferrari", "jaguar", "land rover", "jlr", "rolls royce",
    "ford", "gm", "general motors", "tesla", "rivian", "lucid", "polestar",
    "byd", "nio", "lockheed martin", "northrop grumman", "general dynamics",
    "raytheon", "rtx", "pratt whitney", "collins aerospace", "safran", "bae systems",
    "thales", "l3harris", "dhl", "fedex", "ups", "ikea", "decathlon", "zara",
    "h and m", "h&m", "gap", "puma", "reebok", "under armour", "asics", "skechers",
    "lululemon", "uniqlo", "costco", "carrefour", "starbucks", "mcdonalds",
    "subway", "burger king", "kfc", "pizza hut", "dominos", "pepsico", "nestle",
    "procter and gamble", "p and g", "p&g", "colgate palmolive", "colgate",
    "palmolive", "reckitt", "loreal", "l'oreal", "estee lauder", "shiseido",
    "mondelez", "kraft heinz", "danone", "general mills", "kellogg", "mars",
    "hershey", "ferrero"
}

KNOWN_INDIAN_ENTERPRISES = {
    "tcs", "tata consultancy", "infosys", "wipro", "hcl", "tech mahindra",
    "ltimindtree", "lti mindtree", "larsen toubro", "l&t", "mindtree",
    "flipkart", "bigbasket", "byju", "swiggy", "ola", "zoho", "zerodha",
    "razorpay", "phonepe", "paytm", "freshworks", "biocon", "mphasis",
    "persistent", "nagarro", "birlasoft", "reliance", "jio", "tata", "birla",
    "adani", "mahindra", "godrej", "itc", "bajaj", "vedanta", "hal", "bel",
    "bhel", "ntpc", "ongc", "gail", "iocl", "bpcl", "hpcl", "coal india",
    "sbi", "state bank", "hdfc", "icici", "axis bank", "kotak", "indusind",
    "yes bank", "idfc", "bandhan", "rbl", "cred", "meesho", "groww", "upstox",
    "lenskart", "nykaa", "zomato", "blinkit", "zepto", "policybazaar",
    "paisabazaar", "shiksha", "naukri", "info edge", "justdial", "indiamart",
    "tradeindia", "classplus", "unacademy", "physics wallah", "upgrad",
    "simplilearn", "eruditus", "great learning", "masai school", "coforge",
    "cyient", "zensar", "sonata", "intellect design", "nucleus software",
    "saksoft", "quick heal", "tata elxsi", "kpit", "happiest minds",
    "route mobile", "tanla", "affle",
    "tata communications", "tata comm", "sify", "ctrls", "webwerks", "netmagic",
    "yotta", "bridgei2i", "mu sigma", "fractal analytics", "fractal", "latentview",
    "tiger analytics", "sigmoid", "absolutdata", "incedo", "ust global", "ust",
    "quinnox", "hexaware", "syntel", "virtusa", "itc infotech", "mastek",
    "3i infotech", "rsystems", "r systems", "datamatics", "teamlease", "quess",
    "quess corp", "pine labs", "bharatpe", "mswipe", "ezetap", "slice", "onecard",
    "jupiter money", "fi money", "niyo", "kreditbee", "druva", "browserstack",
    "chargebee", "postman", "hasura", "hevo", "acceldata", "mindtickle",
    "darwinbox", "leadsquared", "whatfix", "zenoti", "icertis", "sirionlabs",
    "locus", "fareye", "delhivery", "shiprocket", "shadowfax", "porter",
    "blackbuck", "rivigo", "elasticrun", "udaan", "jumbotail", "ninjacart",
    "waycool", "dehaat", "oyo", "ola electric", "rapido", "zoomcar", "mygate",
    "nobroker", "housing", "magicbricks", "99acres", "proptiger", "square yards",
    "anarock", "vedantu", "doubtnut", "toppr", "cuemath", "teachmint", "turing",
    "scaler", "interviewbit", "myntra", "ajio", "tata cliq", "firstcry",
    "hopscotch", "clovia", "zivame", "souled store", "boat", "noise", "fire-boltt",
    "boult", "mivi", "zebronics", "portronics", "iball", "intex", "micromax",
    "lava", "reliance retail", "jiomart", "dunzo", "instamart", "milkbasket",
    "country delight", "licious", "freshToHome", "mamaearth", "sugar cosmetics",
    "mcaffeine", "wow skin", "plum goodness", "minimalist", "foxtale",
    "forest essentials", "kama ayurveda", "himalaya wellness", "himalaya",
    "dabur", "baidyanath", "patanjali", "emami", "marico", "godrej consumer",
    "gcpl", "tata consumer", "tcpl", "britannia", "dlf", "prestige", "sobha",
    "brigade", "puravankara", "kolte patil", "tata housing", "lodha", "macrotech",
    "oberoi realty", "shapoorji", "l&t technology services", "ltts", "l&t infotech"
}

TECH_GCC_SIGNALS = {
    "technology", "technologies", "software", "systems", "solutions", "digital",
    "analytics", "semiconductor", "research", "development", "r&d", "labs",
    "global", "innovation", "engineering", "consulting", "consultancy",
    "operations", "services", "cloud", "data", "networks", "electronics",
    "gcc", "gdc", "global delivery", "global development", "shared services",
    "coe", "center of excellence", "offshore", "delivery center", "it hubs",
    "it park", "cyber city", "tech park", "innovation lab", "cybersecurity",
    "devops", "site reliability", "sre", "infrastructure", "artificial intelligence",
    "ai", "machine learning", "ml", "deep learning", "computer vision", "nlp",
    "robotics", "automation", "iot", "blockchain", "fintech", "insurtech",
    "healthtech", "edtech", "retailtech", "martech", "adtech", "proptech",
    "cyber security", "information security", "infosec", "network security",
    "cloud computing", "data analytics", "business intelligence", "data science",
    "predictive analytics", "big data", "data engineering", "data warehouse",
    "data lake", "database", "dba", "dbms", "software engineering", "programming",
    "coding", "web development", "frontend", "backend", "fullstack", "mobile development",
    "app development", "uiux", "ui ux", "user experience", "user interface",
    "product design", "product management", "project management", "quality assurance",
    "qa", "software testing", "test automation", "penetration testing", "vulnerability assessment"
}

LOW_PROMINENCE_SIGNALS = {
    "pan center", "indane", "pest control", "warehouse", "service station",
    "site", "office space", "co-working", "coworking", "business center",
    "serviced office", "integrated citizen service", "agency",
}


def normalize_text(value: object) -> str:
    text = str(value or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def company_key(name: str) -> str:
    text = normalize_text(name)
    text = re.sub(
        r"\b(pvt|private|limited|ltd|llp|opc|inc|corporation|corp|company|co|"
        r"india|bangalore|bengaluru|office|corporate|headquarters|hq|branch)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip() or normalize_text(name)


def contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {text} "


def classify_company(name: str, category_labels: str = "", website: str | None = None) -> dict:
    text = normalize_text(name)
    category_text = normalize_text(category_labels)
    combined_text = normalize_text(f"{name} {category_labels}")
    score = 25
    reasons = []
    company_type = "Local / unclassified office"

    matched_global = sorted(anchor for anchor in KNOWN_GLOBAL_ANCHORS if contains_phrase(text, anchor))
    matched_indian = sorted(anchor for anchor in KNOWN_INDIAN_ENTERPRISES if contains_phrase(text, anchor))
    tech_signals = sorted(signal for signal in TECH_GCC_SIGNALS if contains_phrase(text, signal))
    low_signals = sorted(signal for signal in LOW_PROMINENCE_SIGNALS if contains_phrase(combined_text, signal))

    if matched_global:
      score += 70
      company_type = "Known MNC / GCC anchor"
      reasons.append(f"Known global anchor: {', '.join(matched_global[:2])}")
    elif matched_indian:
      score += 55
      company_type = "Large Indian enterprise / tech anchor"
      reasons.append(f"Known enterprise anchor: {', '.join(matched_indian[:2])}")

    if any(token in text for token in ("private limited", "pvt ltd", "limited", "ltd", "inc", "corp", "corporation")):
        score += 10
        reasons.append("Formal corporate suffix")
    if any(token in text for token in ("headquarters", "head office", "corporate office", "hq")):
        score += 10
        reasons.append("HQ/corporate-office signal")
    if tech_signals:
        score += min(18, 4 * len(tech_signals))
        if company_type == "Local / unclassified office":
            company_type = "Tech / professional services office"
        reasons.append(f"Tech/GCC name signals: {', '.join(tech_signals[:3])}")
    if website:
        score += 5
        reasons.append("Website present")
    if low_signals:
        score -= min(25, 7 * len(low_signals))
        reasons.append(f"Lower enterprise signal: {', '.join(low_signals[:2])}")
    if text in {"office", "corporate office"} or len(text) < 4:
        score -= 30
        reasons.append("Generic office name")

    score = max(0, min(100, score))
    if score >= 85:
        tier = "Tier 1 - MNC/GCC anchor"
    elif score >= 65:
        tier = "Tier 2 - Enterprise/tech anchor"
    elif score >= 45:
        tier = "Tier 3 - Professional office"
    else:
        tier = "Tier 4 - Local/generic office"

    return {
        "company_prominence_score": score,
        "company_prominence_tier": tier,
        "company_type_proxy": company_type,
        "ranking_reasons": reasons or ["Name-only proxy; no strong public-company signal in local record"],
    }


def load_geo_features(path: Path):
    data = json.loads(path.read_text())
    return data, data.get("features", [])


def lonlat_to_local_meters(lon: float, lat: float) -> tuple[float, float]:
    meters_per_degree_lat = 110_574
    meters_per_degree_lon = 111_320 * 0.9749
    return (
        (lon - PROJECTION_ORIGIN_LON) * meters_per_degree_lon,
        (lat - PROJECTION_ORIGIN_LAT) * meters_per_degree_lat,
    )


def project_geometry(geom):
    return transform(lambda lon, lat, z=None: lonlat_to_local_meters(lon, lat), geom)


def main() -> None:
    offices = json.loads(OFFICES_PATH.read_text())
    sez_data, sez_features = load_geo_features(SEZ_PATH)
    _, hex_features = load_geo_features(HEXES_PATH)

    sez_shapes = []
    for idx, feature in enumerate(sez_features):
        geom = shape(feature["geometry"])
        projected_geom = project_geometry(geom)
        sez_shapes.append((idx, feature, prep(geom), projected_geom))

    hex_shapes = []
    for feature in hex_features:
        geom = shape(feature["geometry"])
        hex_shapes.append((feature, prep(geom)))

    output = []
    seen_place_ids = set()

    for raw in offices:
        place_id = raw.get("fsq_place_id")
        if place_id in seen_place_ids:
            continue
        seen_place_ids.add(place_id)

        lat = raw.get("latitude")
        lon = raw.get("longitude")
        name = raw.get("name")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not name:
            continue

        point = Point(lon, lat)
        projected_point = Point(*lonlat_to_local_meters(lon, lat))
        matched_sez = None
        match_type = None
        distance_to_sez_km = 0.0
        nearest = None

        for _, feature, prepared, projected_geom in sez_shapes:
            if prepared.contains(point) or prepared.intersects(point):
                matched_sez = feature
                match_type = "inside_boundary"
                distance_to_sez_km = 0.0
                break

            distance_m = projected_point.distance(projected_geom)
            if nearest is None or distance_m < nearest[0]:
                nearest = (distance_m, feature)

        if not matched_sez:
            if nearest and nearest[0] <= PROXIMITY_BUFFER_KM * 1000:
                distance_to_sez_km = round(nearest[0] / 1000, 3)
                matched_sez = nearest[1]
                match_type = "near_boundary"
            else:
                continue

        matched_hex = None
        for feature, prepared in hex_shapes:
            if prepared.contains(point) or prepared.intersects(point):
                matched_hex = feature
                break

        hex_props = (matched_hex or {}).get("properties", {})
        sez_props = matched_sez.get("properties", {})
        ranking = classify_company(raw.get("name"), raw.get("fsq_category_labels"), raw.get("website"))

        output.append({
            "id": raw.get("fsq_place_id"),
            "name": raw.get("name"),
            "lat": lat,
            "lon": lon,
            "address": raw.get("address") or "",
            "locality": raw.get("locality") or "",
            "postcode": raw.get("postcode") or "",
            "website": raw.get("website") or "",
            "tel": raw.get("tel") or "",
            "email": raw.get("email") or "",
            "fsq_category_labels": raw.get("fsq_category_labels") or "",
            "placemaker_url": raw.get("placemaker_url") or "",
            "date_created": raw.get("date_created") or "",
            "date_refreshed": raw.get("date_refreshed") or "",
            "company_key": company_key(raw.get("name")),
            "sez_name": sez_props.get("name") or "N/A",
            "sez_match_type": match_type,
            "distance_to_sez_km": distance_to_sez_km,
            "proximity_buffer_km": PROXIMITY_BUFFER_KM,
            "sez_office_spaces": sez_props.get("office_spaces") or 0,
            "hex_id": hex_props.get("hex_id") or h3.latlng_to_cell(lat, lon, 7),
            "hex_name": hex_props.get("name") or "",
            "hex_rank": hex_props.get("rank"),
            "zone": hex_props.get("zone") or "",
            **ranking,
        })

    company_counts = Counter(item["company_key"] for item in output)
    for item in output:
        item["same_company_records_in_sez"] = company_counts[item["company_key"]]
        item["office_rank_score"] = min(100, item["company_prominence_score"] + min(8, company_counts[item["company_key"]] - 1))

    output.sort(key=lambda item: (-item["office_rank_score"], item["sez_name"], item["name"]))
    for idx, item in enumerate(output, 1):
        item["overall_office_rank"] = idx

    sez_summary = defaultdict(lambda: {"office_count": 0, "inside_count": 0, "near_boundary_count": 0, "top_companies": [], "tier_counts": Counter()})
    zone_summary = defaultdict(lambda: {"office_count": 0, "inside_count": 0, "near_boundary_count": 0, "top_companies": [], "tier_counts": Counter()})
    hex_summary = defaultdict(lambda: {"office_count": 0, "inside_count": 0, "near_boundary_count": 0, "top_companies": [], "tier_counts": Counter()})

    for item in output:
        for key, summary in (
            (item["sez_name"], sez_summary),
            (item["zone"] or "Unassigned", zone_summary),
            (item["hex_id"], hex_summary),
        ):
            summary[key]["office_count"] += 1
            if item["sez_match_type"] == "inside_boundary":
                summary[key]["inside_count"] += 1
            elif item["sez_match_type"] == "near_boundary":
                summary[key]["near_boundary_count"] += 1
            summary[key]["tier_counts"][item["company_prominence_tier"]] += 1
            top_keys = {company["company_key"] for company in summary[key]["top_companies"]}
            if item["company_key"] not in top_keys and len(summary[key]["top_companies"]) < 8:
                summary[key]["top_companies"].append({
                    "name": item["name"],
                    "company_key": item["company_key"],
                    "score": item["office_rank_score"],
                    "tier": item["company_prominence_tier"],
                })

    summary_payload = {
        "source_file": str(OFFICES_PATH.relative_to(ROOT)),
        "input_office_records": len(offices),
        "sez_matched_office_records": len(output),
        "inside_boundary_records": sum(1 for item in output if item["sez_match_type"] == "inside_boundary"),
        "near_boundary_records": sum(1 for item in output if item["sez_match_type"] == "near_boundary"),
        "outside_proximity_excluded_records": len(offices) - len(output),
        "proximity_buffer_km": PROXIMITY_BUFFER_KM,
        "sez_count": len(sez_summary),
        "zone_count": len(zone_summary),
        "hex_count": len(hex_summary),
        "proximity_note": f"Includes offices inside SEZ boundaries plus offices up to {PROXIMITY_BUFFER_KM:g} km from the nearest SEZ boundary/geometry.",
        "ranking_note": "Company prominence is an offline name-signal proxy, not a refreshed public-company lookup.",
        "sez_summary": {
            key: {
                "office_count": value["office_count"],
                "inside_count": value["inside_count"],
                "near_boundary_count": value["near_boundary_count"],
                "tier_counts": dict(value["tier_counts"]),
                "top_companies": value["top_companies"],
            }
            for key, value in sorted(sez_summary.items())
        },
        "zone_summary": {
            key: {
                "office_count": value["office_count"],
                "inside_count": value["inside_count"],
                "near_boundary_count": value["near_boundary_count"],
                "tier_counts": dict(value["tier_counts"]),
                "top_companies": value["top_companies"],
            }
            for key, value in sorted(zone_summary.items())
        },
    }

    OUT_PATH.write_text(json.dumps(output, indent=2))
    SUMMARY_PATH.write_text(json.dumps(summary_payload, indent=2))
    print(f"Input offices: {len(offices)}")
    print(f"SEZ-matched offices: {len(output)}")
    print(f"Inside boundary: {summary_payload['inside_boundary_records']}")
    print(f"Near boundary <= {PROXIMITY_BUFFER_KM:g} km: {summary_payload['near_boundary_records']}")
    print(f"Outside excluded: {summary_payload['outside_proximity_excluded_records']}")
    print(f"Wrote {OUT_PATH}")
    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
