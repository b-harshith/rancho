#!/usr/bin/env python3
import json
import csv
import os
import re
from datetime import datetime
from pathlib import Path

class MagicbricksParser:
    """
    Utility class to parse and transform Magicbricks raw JSONL listings into CSV.
    """
    
    CSV_COLUMNS = [
        "listing_id", "source_portal", "listing_url", "scraped_at",
        "latitude", "longitude", "locality", "sublocality", "address", "landmark_details", "pincode",
        "bhk_type", "property_type", "furnishing", "floor_number", "total_floors", "facing", "sqft", "area_type", "age_years",
        "apartment_bio",
        "monthly_rent", "deposit_amount", "maintenance_monthly", "price_per_sqft",
        "bathrooms", "parking", "has_lift", "has_gym", "has_security", "luxury_amenities",
        "is_verified", "is_premium", "owner_type", "confidence_score", "possession_status", 
        "listed_date", "last_updated", "is_available"
    ]

    def __init__(self, logger, config_obj):
        self.logger = logger
        self.config = config_obj
        self.raw_dir = Path(self.config.PATHS["raw_dir"])
        self.processed_dir = Path(self.config.PATHS["processed_dir"])
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _clean_text(text):
        if not text:
            return ""
        # Remove HTML tags and extra whitespace
        text = re.sub(r'<[^>]+>', '', str(text))
        return " ".join(text.split())

    @staticmethod
    def _extract_pincode(text):
        if not text:
            return ""
        match = re.search(r'\b\d{6}\b', str(text))
        return match.group(0) if match else ""

    def _extract_listing_data(self, item):
        """Maps a single listing item to the target CSV schema."""
        
        # Coordinates
        lat, lon = "", ""
        geo = item.get("ltcoordGeo", "")
        if geo and "," in geo:
            parts = geo.split(",")
            if len(parts) >= 2:
                lat, lon = parts[0].strip(), parts[1].strip()

        # Amenities logic
        nonlux = item.get("nonluxAmenMap", {})
        lux = item.get("luxAmenMap", {})
        all_amenities_text = " ".join(list(nonlux.values()) + list(lux.values()))
        
        has_lift = "Yes" if "Lift" in all_amenities_text else "No"
        has_gym = "Yes" if "Gym" in all_amenities_text else "No"
        has_security = "Yes" if "Security" in all_amenities_text else "No"

        # Bio and Address
        bio = self._clean_text(item.get("dtldesc") or item.get("schemaDtldesc") or item.get("auto_desc"))
        address = item.get("catAdd1") or item.get("defaultAdddressGoogle")
        pincode = self._extract_pincode(item.get("psmAdd") or item.get("dtldesc") or address)

        # Deposit Extraction
        deposit = item.get("bookingAmtExact") or ""
        if not deposit:
            dep_match = re.search(r'deposit[:\s]*(\d+[\d,]*)', bio, re.IGNORECASE)
            if dep_match:
                deposit = dep_match.group(1).replace(",", "")

        # Flags
        is_verified = "True" if (item.get("comFlag") == "Y" or item.get("ctVerifd") == "Y") else "False"
        is_premium = "True" if (item.get("prm") == "y" or str(item.get("isprimeListingType")).lower() == "true") else "False"

        return {
            "listing_id": item.get("encId") or item.get("id"),
            "source_portal": "Magicbricks",
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "listing_url": f"https://www.magicbricks.com/property-details/{item.get('url')}",
            "latitude": lat,
            "longitude": lon,
            "locality": item.get("locName"),
            "sublocality": item.get("locSeoName") or item.get("caCompNameD"),
            "address": address,
            "landmark_details": ", ".join(item.get("landmarkDetails", [])) if isinstance(item.get("landmarkDetails"), list) else "",
            "pincode": pincode,
            "bhk_type": item.get("bedroom"),
            "property_type": item.get("propTypeD"),
            "furnishing": item.get("furnishedD"),
            "floor_number": item.get("floorNo"),
            "total_floors": item.get("floors"),
            "facing": item.get("facingD"),
            "sqft": item.get("coveredArea") or item.get("ca"),
            "area_type": item.get("covAreaUnitDesc"),
            "age_years": item.get("acD") or item.get("operatingSinceYear") or "",
            "apartment_bio": bio,
            "monthly_rent": item.get("price"),
            "deposit_amount": deposit,
            "maintenance_monthly": item.get("maintenanceCharges") or "",
            "price_per_sqft": item.get("sqFtPrice"),
            "bathrooms": item.get("bathD"),
            "parking": item.get("parkingD"),
            "has_lift": has_lift,
            "has_gym": has_gym,
            "has_security": has_security,
            "luxury_amenities": ", ".join(lux.values()) if lux else "",
            "is_verified": is_verified,
            "is_premium": is_premium,
            "owner_type": item.get("userType"),
            "confidence_score": item.get("cScore"),
            "possession_status": item.get("possStatusD"),
            "listed_date": item.get("postDateT"),
            "last_updated": item.get("modifiedDate") or item.get("lastAccessDate"),
            "is_available": "True"
        }

    def process_city(self, city_name):
        """Processes a single city's JSONL file."""
        safe_city = getattr(self.config, "OUTPUT_SLUG", city_name.lower().replace(" ", "_").replace("/", "_"))
        input_file = self.raw_dir / f"{safe_city}.jsonl"
        output_file = self.processed_dir / f"{safe_city}.csv"

        if not input_file.exists():
            if self.logger: self.logger.log(f"[Parser] Skipped: No raw data for {city_name}.")
            return

        print_enabled = bool(self.logger)
        if print_enabled: self.logger.log(f"[Parser] Parsing {city_name} data...")
        count = 0
        
        with open(output_file, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=self.CSV_COLUMNS)
            writer.writeheader()

            with open(input_file, "r", encoding="utf-8") as f:
                for line_idx, line in enumerate(f):
                    try:
                        data = json.loads(line)
                        results = data.get("searchResult", [])
                        
                        for item in results:
                            row = self._extract_listing_data(item)
                            writer.writerow(row)
                            count += 1
                            
                    except Exception as e:
                        if print_enabled: self.logger.log(f"[Parser] Error on line {line_idx + 1} for '{city_name}': {e}")

        if print_enabled: self.logger.log(f"[Parser] Saved {count:,} clean records to {output_file.name}")

    def process_all_cities(self):
        """Processes all .jsonl files in the raw directory."""
        jsonl_files = list(self.raw_dir.glob("*.jsonl"))
        if not jsonl_files:
            print("No JSONL files found in raw directory.")
            return

        for file in jsonl_files:
            self.process_city(file.stem)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Magicbricks Parser CLI")
    parser.add_argument("--city", help="Specify a city to process (filename without .jsonl)")
    parser.add_argument("--all", action="store_true", help="Process all cities in data/raw")
    
    args = parser.parse_args()
    
    app_parser = MagicbricksParser()
    
    if args.all:
        app_parser.process_all_cities()
    elif args.city:
        app_parser.process_city(args.city)
    else:
        # Default behavior: if no args, check for bangalore and hyderabad
        for city in ["bangalore", "hyderabad"]:
            app_parser.process_city(city)
