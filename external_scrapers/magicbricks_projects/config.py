# config.py

"""
Configuration file for the Magicbricks scraping and parsing pipeline.
Configured for comprehensive Bangalore extraction (residential/commercial, rent/sale).
"""

TARGET_CITIES = ["Bangalore"]
OUTPUT_SLUG = "bangalore"

PATHS = {
    "raw_dir": "data/raw",
    "processed_dir": "data/processed",
    "compiled_file": "data/processed/bangalore_listings.csv"
}

SCRAPER_SETTINGS = {
    "page_limit": 100,  # Magicbricks hard limit per distinct search
    "max_workers": 8,   # Max concurrent threads per category
    "min_sleep": 1.5,   # Minimum delay between requests to avoid bans
    "max_sleep": 3.5,   # Maximum delay between requests
}

CATEGORIES = {
    "residential_rent": {
        "url_template": "https://www.magicbricks.com/property-for-rent/residential-real-estate?bedroom=&proptype={property_types}&cityName={city}",
        "property_types": [
            "Multistorey-Apartment", "Builder-Floor-Apartment", "Villa",
            "Residential-House", "Penthouse", "Studio-Apartment", "Residential-Land"
        ],
        "price_buckets": [
            (0, 10000), (10001, 18000), (18001, 25000), (25001, 35000),
            (35001, 45000), (45001, 60000), (60001, 80000), (80001, 120000),
            (120001, 200000), (200001, 99999999)
        ]
    },
    "residential_sale": {
        "url_template": "https://www.magicbricks.com/property-for-sale/residential-real-estate?bedroom=&proptype={property_types}&cityName={city}",
        "property_types": [
            "Multistorey-Apartment", "Builder-Floor-Apartment", "Villa",
            "Residential-House", "Penthouse", "Studio-Apartment", "Residential-Land"
        ],
        "price_buckets": [
            (0, 3000000), (3000001, 5000000), (5000001, 7000000), (7000001, 9000000),
            (9000001, 12000000), (12000001, 15000000), (15000001, 20000000), (20000001, 30000000),
            (30000001, 50000000), (50000001, 100000000), (100000001, 9999999999)
        ]
    },
    "commercial_rent": {
        "url_template": "https://www.magicbricks.com/property-for-rent/commercial-real-estate?bedroom=&proptype={property_types}&cityName={city}",
        "property_types": [
            "Commercial-Office-Space", "Office-ITPark-SEZ", "Commercial-Shop",
            "Commercial-Showroom", "Commercial-Land", "Industrial-Land",
            "Co-working-Space", "Industrial-Building"
        ],
        "price_buckets": [
            (0, 20000), (20001, 40000), (40001, 75000), (75001, 150000),
            (150001, 300000), (300001, 99999999)
        ]
    },
    "commercial_sale": {
        "url_template": "https://www.magicbricks.com/property-for-sale/commercial-real-estate?bedroom=&proptype={property_types}&cityName={city}",
        "property_types": [
            "Commercial-Office-Space", "Office-ITPark-SEZ", "Commercial-Shop",
            "Commercial-Showroom", "Commercial-Land", "Industrial-Land",
            "Co-working-Space", "Industrial-Building"
        ],
        "price_buckets": [
            (0, 5000000), (5000001, 15000000), (15000001, 30000000), (30000001, 60000000),
            (60000001, 120000000), (120000001, 9999999999)
        ]
    }
}