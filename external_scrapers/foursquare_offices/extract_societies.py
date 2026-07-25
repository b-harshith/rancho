#!/usr/bin/env python3
import json
import csv
import re
from collections import Counter

# File paths
input_file = "foursquare_bangalore_places.json"
output_json = "bangalore_residential_listings.json"
output_csv = "bangalore_residential_listings.csv"

# Category IDs representing residential units/buildings/developments
RESIDENTIAL_CATEGORY_IDS = {
    "4e67e38e036454776db1fb3a",  # Community and Government > Residential Building
    "4d954b06a243a5684965b473",  # Community and Government > Residential Building > Apartment or Condo
    "4f2a210c4b9023bd5841ed28",  # Community and Government > Housing Development
}

# Strong residential words (lowercase)
STRONG_RESIDENTIAL_KEYWORDS = {
    "apartment", "apartments", "apts", "apt",
    "condo", "condos", "condominium", "condominiums",
    "villa", "villas",
    "enclave", "enclaves",
    "residency", "residencies",
    "township", "townships",
}

# Gated community / society combinations
RESIDENTIAL_PHRASES = [
    r"\bgated\s+community\b",
    r"\bhousing\s+society\b",
    r"\bcooperative\s+housing\s+society\b",
    r"\bco[- ]op\s+housing\b",
    r"\bapartment\s+society\b",
    r"\bresidential\s+society\b",
    r"\bresidential\s+layout\b",
]

# Developers in Bangalore (lowercase)
DEVELOPERS = {
    "prestige", "sobha", "brigade", "purva", "puravankara", "mantri", "adarsh", "salarpuria", "sattva", 
    "assetz", "godrej", "hiranandani", "rohan", "casagrand", "century", "nitesh", "sumadhura", 
    "total environment", "ds max", "ds-max", "dsmax", "shriram", "kolte patil", "kolte-patil", 
    "vaishnavi", "confident", "ramky", "vaswani", "divyasree", "gmr", "tata value", "tata housing"
}

# Exclusion terms in the name (lowercase)
NAME_EXCLUSION_KEYWORDS = {
    # Food and dining
    "restaurant", "cafe", "diner", "dhaba", "canteen", "eatery", "kitchen", "bakery", "bakes", "sweets", 
    "catering", "eateries", "tea shop", "coffee shop", "juice", "darshini", "mess", "caterers", "pizza", 
    "burger", "bites",
    # Retail and commerce
    "store", "shop", "mart", "supermarket", "groceries", "provisions", "bazaar", "showroom", "dealers", 
    "enterprise", "enterprises", "industries", "factory", "mills", "mill", "garage", "mechanic", "puncture", 
    "service station", "car wash", "automobiles", "boutique", "tailor", "salon", "saloon", "parlour", "spa",
    "hair", "beauty", "cosmetics", "pharmacy", "chemist", "hardware", "plywood", "electricals", "plumbing",
    "jewellery", "jewellers", "clothing", "textiles", "bookstore", "books", "opticals", "opticians", "stationery",
    # Offices and corporate
    "office", "corporate", "tech park", "business park", "software", "technologies", "it services", 
    "developer", "developers", "properties", "builders", "group", "constructions", "projects", "real estate",
    "agency", "consultancy", "firm", "limited", "ltd", "pvt", "coop credit", "credit society", "financial",
    "finance", "bank", "atm", "insurance", "broker", "cooperative bank", "muthoot", "manappuram", "gold loan",
    "systems", "system", "solutions", "solution", "control", "waterproofing", "management",
    # Services & interior design (often misclassified under Housing Development)
    "design", "designer", "designers", "interior", "interiors", "decor", "decors", "architect", "architects", 
    "architecture", "renovation", "renovations", "remodeling", "contractor", "contractors", "carpenter", 
    "plumber", "electrician", "painter", "pest control", "maintenance", "repair", "renovator",
    # Amenities and facilities
    "clubhouse", "club house", "swimming pool", "pool", "court", "badminton", "tennis", "squash", "track", 
    "jogging", "walking", "playground", "park", "security", "gate", "lobby", "lounge", "gym", "fitness", 
    "studio", "reception", "sales office", "experience center", "experience centre", "marketing office",
    "guest house", "pg", "paying guest", "hostel", "colive", "co-live", "snoozotel", "banquet hall",
    # Education and public
    "school", "college", "university", "academy", "vidyalaya", "preschool", "nursery", "kindergarten", 
    "tuition", "coaching", "classes", "institute", "hospital", "clinic", "dental", "dentist", "diagnostics", 
    "medical", "meds", "healthcare", "physiotherapy", "doctor", "nursing home", "temple", "church", "mosque", 
    "dargah", "gurudwara", "ashram", "math", "spiritual", "trust", "foundation",
    # Address terms that indicate commercial details
    "opposite", "near", "behind", "next to", "beside",
    # Weird noise
    "facebook", "hyderabad"
}

# Category labels to exclude if matched by keywords (lowercase)
EXCLUDE_CATEGORY_LABELS_SUBSTRINGS = {
    "retail", "dining and drinking", "restaurant", "cafe", "bar", "pub", "financial service", "bank", "atm",
    "hotel", "motel", "resort", "lodging", "school", "college", "education", "hospital", "clinic", "dentist",
    "doctor", "medical", "pharmacy", "gym", "fitness", "beauty", "salon", "spa", "hair", "office", "tech park",
    "business center", "government", "spiritual", "temple", "church", "mosque", "laundry", "dry cleaner",
    "post office", "police station", "fire station", "library", "museum", "art gallery"
}

# Neighborhood suffixes in single-word names (lowercase)
NEIGHBORHOOD_SUFFIXES = (
    "nagar", "palya", "sandra", "gere", "halli", "giri", "pura", "mangala", 
    "bagh", "pet", "pete", "kodi", "gate", "town", "layout", "village"
)

# Address/unit regex checks
UNIT_REGEXES = [
    r"^no\s*\.?\s*\d+",
    r"^flat\s+(no)?\.?\s*\d+",
    r"^plot\s+(no)?\.?\s*\d+",
    r"^door\s+(no)?\.?\s*\d+",
    r"^site\s+(no)?\.?\s*\d+",
    r"^\d+/\d+",
    r"^\d+,\s*",
    r"^[a-f]\s+block$",
    r"^block\s+[a-f]$",
    r"^block\s+\d+$",
    r"^\d+\s*th\s+(cross|main)$"
]

def clean_word(word):
    return re.sub(r'[^\w\s]', '', word.lower())

def is_residential_listing(data):
    name = data.get("name", "").strip()
    if not name:
        return False, "Empty Name", []
        
    name_lower = name.lower()
    
    # 1. Address / Unit check
    for regex in UNIT_REGEXES:
        if re.match(regex, name_lower):
            return False, f"Unit/Address Pattern Match: '{name}'", []
            
    # 2. Standalone neighborhood check (e.g. exactly "Uttrahalli" or "Channasandra")
    # If the name is a single word (no spaces) and ends with neighborhood suffixes
    if " " not in name_lower and name_lower.endswith(NEIGHBORHOOD_SUFFIXES):
        return False, f"Single-word Neighborhood Name: '{name}'", []
        
    # Parse categories
    cat_ids = set(x.strip() for x in data.get("fsq_category_ids", "").split(",") if x.strip())
    cat_labels = data.get("fsq_category_labels", "")
    cat_labels_lower = cat_labels.lower()
    
    # 3. Gather match candidates
    matched_by = []
    
    # Rule 1: Explicit Category ID
    if cat_ids & RESIDENTIAL_CATEGORY_IDS:
        matched_by.append("Explicit Category ID")
    
    # Clean words tokenization
    clean_name = re.sub(r'[^\w\s-]', ' ', name_lower)
    tokens = set(clean_name.split())
    
    # Rule 2: Strong Residential Keyword (as distinct words)
    matched_kws = tokens & STRONG_RESIDENTIAL_KEYWORDS
    if matched_kws:
        matched_by.append(f"Strong Keyword ({', '.join(matched_kws)})")
        
    # Rule 3: Residential Phrase (Regex)
    for phrase in RESIDENTIAL_PHRASES:
        if re.search(phrase, name_lower):
            matched_by.append("Residential Phrase")
            break
            
    # Rule 4: Layout name match (Ends with Layout, or Layout as a distinct word)
    if "layout" in tokens:
        matched_by.append("Layout")
        
    # Rule 5: Developer Name
    matched_devs = [dev for dev in DEVELOPERS if dev in name_lower]
    if matched_devs:
        matched_by.append(f"Developer ({', '.join(matched_devs)})")

    if not matched_by:
        return False, None, []

    # 4. Apply Exclusions (to ensure high precision)
    # Check for Name Exclusions
    for token in tokens:
        if token in NAME_EXCLUSION_KEYWORDS:
            return False, f"Name Exclusion Word: '{token}'", matched_by

    # Also check multi-word exclusion phrases in name
    multi_word_exclusions = [
        "pvt ltd", "pvt. ltd.", "co-op bank", "cooperative bank", "credit society", 
        "welfare association", "tech park", "business park", "experience center", 
        "experience centre", "sales office", "guest house", "paying guest", 
        "nursing home", "massage parlor", "massage parlour", "beauty parlor",
        "beauty parlour", "dry cleaner", "service station", "car wash", "dental clinic",
        "medical center", "medical centre", "business centre", "business center",
        "convention center", "convention centre", "convention hall", "home maintenance"
    ]
    for phrase in multi_word_exclusions:
        if phrase in name_lower:
            return False, f"Name Exclusion Phrase: '{phrase}'", matched_by

    # Standalone Center/Centre check (exclude unless accompanied by residential keyword)
    if ("center" in tokens or "centre" in tokens) and not (tokens & STRONG_RESIDENTIAL_KEYWORDS):
        return False, "Name contains Center/Centre without residential keyword", matched_by

    # Standalone Association check (exclude unless accompanied by residential keyword)
    if ("association" in tokens or "rwa" in tokens) and not (tokens & STRONG_RESIDENTIAL_KEYWORDS):
        return False, "Name contains Association without residential keyword", matched_by

    # Check for Category Exclusions (if not explicitly classified as residential by Foursquare)
    if "Explicit Category ID" not in matched_by:
        # If it matched by keywords/developer, check if the category is commercial/other
        for exclude_cat in EXCLUDE_CATEGORY_LABELS_SUBSTRINGS:
            if exclude_cat in cat_labels_lower:
                return False, f"Category Exclusion Label: '{exclude_cat}'", matched_by

    # If it is matched by developer name ONLY (no residential keyword/category),
    # it must have a very clean category (either empty, structure, or neighborhood)
    # and must not contain common commercial words.
    if len(matched_by) == 1 and matched_by[0].startswith("Developer"):
        is_safe_category = False
        if not cat_labels or any(c in cat_labels_lower for c in ["structure", "neighborhood", "residential"]):
            is_safe_category = True
        
        if not is_safe_category:
            return False, f"Developer Match with Unsafe Category: '{cat_labels}'", matched_by

    # Special check: if matched by "Layout" only, make sure it does not have commercial category
    if len(matched_by) == 1 and matched_by[0] == "Layout":
        if cat_labels_lower and not any(c in cat_labels_lower for c in ["neighborhood", "structure", "residential", "community"]):
            return False, f"Layout Match with Unsafe Category: '{cat_labels}'", matched_by

    return True, None, matched_by

def main():
    print(f"Reading and analyzing '{input_file}'...")
    
    extracted_listings = []
    excluded_samples = [] # Store some excluded items for validation
    
    # Counters for statistics
    total_processed = 0
    match_reasons = Counter()
    exclusion_reasons = Counter()
    
    with open(input_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            total_processed += 1
            data = json.loads(line)
            
            is_match, reason, matched_by = is_residential_listing(data)
            
            if is_match:
                # Add matched reason to metadata
                data["extraction_matched_by"] = ", ".join(matched_by)
                extracted_listings.append(data)
                for reason_name in matched_by:
                    match_reasons[reason_name] += 1
            else:
                if reason:
                    exclusion_reasons[reason] += 1
                    if len(excluded_samples) < 30:
                        excluded_samples.append((data.get("name"), data.get("fsq_category_labels"), reason))

    print("\n--- EXTRACTION STATISTICS ---")
    print(f"Total processed places: {total_processed}")
    print(f"Extracted residential places: {len(extracted_listings)}")
    print(f"Percentage extracted: {len(extracted_listings) / total_processed * 100:.2f}%")
    
    print("\nMatches breakdown by rule:")
    for rule, count in match_reasons.most_common():
        print(f"  - {rule}: {count}")
        
    print("\nTop 15 exclusion reasons:")
    for reason, count in exclusion_reasons.most_common(15):
        print(f"  - {reason}: {count}")
        
    # Write to JSON
    print(f"\nWriting to '{output_json}'...")
    with open(output_json, "w") as f:
        json.dump(extracted_listings, f, indent=4)
        
    # Write to CSV
    print(f"Writing to '{output_csv}'...")
    csv_columns = [
        "fsq_place_id", "name", "latitude", "longitude", "address", 
        "locality", "postcode", "fsq_category_ids", "fsq_category_labels", 
        "extraction_matched_by"
    ]
    try:
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
            writer.writeheader()
            for record in extracted_listings:
                writer.writerow(record)
    except Exception as e:
        print("Error writing CSV:", e)

    print("\n--- SAMPLE MATCHED LISTINGS (First 10) ---")
    for i, item in enumerate(extracted_listings[:10]):
        print(f"{i+1}. {item.get('name')} | Category: {item.get('fsq_category_labels')} | Matched by: {item.get('extraction_matched_by')}")
        
    print("\n--- SAMPLE EXCLUDED LISTINGS FOR VALIDATION (First 10) ---")
    for i, (name, cat, reason) in enumerate(excluded_samples[:10]):
        print(f"{i+1}. {name} | Category: {cat} | Excluded due to: {reason}")

if __name__ == "__main__":
    main()
