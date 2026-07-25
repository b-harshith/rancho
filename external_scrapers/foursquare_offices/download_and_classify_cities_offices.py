#!/usr/bin/env python3
import os
import re
import json
import yaml
from pathlib import Path
import polars as pl
from pyiceberg.catalog import load_catalog

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CITIES_YAML_PATH = PROJECT_ROOT / "config" / "cities.yaml"
WORKSPACE_DIR = Path(__file__).resolve().parent
OFFICES_CATEGORY_ID = "4bf58dd8d48988d124941735"

# --- Classification Rules from process_sez_office_listings.py ---
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


def main():
    # 1. Connect to Foursquare Catalog
    print("Connecting to Foursquare Catalog...")
    catalog = load_catalog(
        "default",
        **{
            "warehouse": "places",
            "uri": "https://catalog.h3-hub.foursquare.com/iceberg",
            "token": "eyJhbGciOiJIUzI1NiJ9.eyJhY3RvclR5cGUiOiJVU0VSIiwiYWN0b3JJZCI6InByb2QtZnNxLXVzZXItMTQxNjQ5MjcyNyIsInR5cGUiOiJQRVJTT05BTCIsInZlcnNpb24iOiIyIiwianRpIjoiZDM4Y2Q1ZjEtODc0Yy00OTk5LTkwNmMtNzcwZDE2MDE3ODBjIiwic3ViIjoicHJvZC1mc3EtdXNlci0xNDE2NDkyNzI3IiwiZXhwIjoxNzg0MzY0MDkyLCJpc3MiOiJkYXRhaHViLW1ldGFkYXRhLXNlcnZpY2UifQ.8o7VzExMxmkw_CBS5Z9bhfIdJ4KgX9ebDmhGXChFbb0",
            "header.content-type": "application/vnd.api+json",
            "rest-metrics-reporting-enabled": "false",
            "s3.region": "us-east-1",
            "s3.connect-timeout": "60",
            "s3.request-timeout": "60",
        },
    )

    print("Loading the OS Places table metadata...")
    table = catalog.load_table('datasets.places_os')

    # 2. Define the Schema fields
    target_schema = [
        "fsq_place_id", "name", "latitude", "longitude", "address", "locality", 
        "region", "postcode", "admin_region", "post_town", "po_box", "country", 
        "date_created", "date_refreshed", "date_closed", "tel", "website", 
        "email", "facebook_id", "instagram", "twitter", "fsq_category_ids", 
        "fsq_category_labels", "placemaker_url", "unresolved_flags", "geom", "bbox"
    ]

    # 3. Load Cities YAML
    print(f"Loading cities configuration from {CITIES_YAML_PATH}...")
    with open(CITIES_YAML_PATH, "r") as f:
        config = yaml.safe_load(f)

    cities = config.get("cities", [])
    
    for city in cities:
        city_id = city.get("canonical_city_id")
        city_name = city.get("display_name")
        
        # Skip Bengaluru as requested
        if city_id == "bengaluru":
            print(f"Skipping {city_name} (bengaluru)...")
            continue
            
        bounds = city.get("bounds", {})
        west = bounds.get("west")
        south = bounds.get("south")
        east = bounds.get("east")
        north = bounds.get("north")
        
        if None in (west, south, east, north):
            print(f"Skipping {city_name} due to missing bounds...")
            continue
            
        print(f"\n--- Processing {city_name} ({city_id}) ---")
        print(f"Bounds: West={west}, South={south}, East={east}, North={north}")
        
        # Spatial scan row filter
        row_filter_str = f"country == 'IN' and latitude >= {south} and latitude <= {north} and longitude >= {west} and longitude <= {east}"
        print(f"Executing spatial scan...")
        try:
            arrow_table = table.scan(
                row_filter=row_filter_str,
                selected_fields=target_schema
            ).to_arrow()
        except Exception as e:
            print(f"Failed to scan Foursquare catalog for {city_name}: {e}")
            continue

        pois = pl.from_arrow(arrow_table)
        print(f"Total POIs scanned: {len(pois)}")
        if len(pois) == 0:
            print("No POIs found.")
            continue

        # Filter by Offices category ID: OFFICES_CATEGORY_ID
        # Let's first format list columns to comma-separated strings to be consistent with original filter.py
        processed_pois = pois.with_columns([
            pl.col("fsq_category_ids").list.join(", ").fill_null(""),
            pl.col("fsq_category_labels").list.join(", ").fill_null(""),
            pl.col("unresolved_flags").list.join(", ").fill_null(""),
            pl.col("bbox").cast(pl.String),
            pl.col("geom").bin.encode("hex").fill_null("")
        ])

        filtered_offices = processed_pois.filter(
            pl.col("fsq_category_ids").str.contains(OFFICES_CATEGORY_ID)
        )
        print(f"Found {len(filtered_offices)} office listings.")

        if len(filtered_offices) == 0:
            print("No office listings found after filtering.")
            continue

        # Run classification
        print("Running corporate prominence classification...")
        classified_list = []
        for row in filtered_offices.to_dicts():
            name = row.get("name")
            category_labels = row.get("fsq_category_labels")
            website = row.get("website")
            
            classification = classify_company(name, category_labels, website)
            
            # Combine record with classification details
            classified_record = {**row, **classification}
            classified_list.append(classified_record)

        # Write to JSON
        output_file = WORKSPACE_DIR / f"{city_id}_office_listings.json"
        print(f"Saving {len(classified_list)} classified offices to {output_file}...")
        with open(output_file, "w") as f:
            json.dump(classified_list, f, indent=4)

        # Print quick statistics
        tiers = [item["company_prominence_tier"] for item in classified_list]
        from collections import Counter
        tier_counts = Counter(tiers)
        print(f"Classification stats for {city_name}:")
        for tier, count in sorted(tier_counts.items()):
            print(f"  {tier}: {count}")


if __name__ == "__main__":
    main()
