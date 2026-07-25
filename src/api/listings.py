import json
import sqlite3
import os
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler

try:
    from portal_auth import is_authorized
except ImportError:  # pragma: no cover - package import in tests/tooling
    from src.portal_auth import is_authorized

# Support for Postgres
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# Setup Paths
SERVER_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SERVER_DIR / "listings.db"

POSTGRES_URL = os.environ.get("POSTGRES_URL")

LEGACY_SCHOOL_FIELDS = {
    "catchment_kids",
    "kids_tam",
    "school_age_children",
    "wealthy_school_children",
    "countable_school_age_children",
    "countable_wealthy_school_children",
    "target_grade_2_9_kids",
    "target_student_tam",
    "student_implied_families",
    "reachable_grade_2_9_kids",
    "reachable_student_implied_families",
    "reachable_student_pool",
}

LISTING_COLUMNS = (
    "id, title, property_type, price, sqft, floor, amenities, latitude, longitude, "
    "listing_url, score, metro_name, metro_distance, road_type, visibility_score, "
    "catchment_tam, raw_data, created_at"
)


def strip_legacy_school_fields(value):
    """Remove retired synthetic school fields from persisted listing payloads."""
    if isinstance(value, dict):
        return {
            key: strip_legacy_school_fields(item)
            for key, item in value.items()
            if key not in LEGACY_SCHOOL_FIELDS
        }
    if isinstance(value, list):
        return [strip_legacy_school_fields(item) for item in value]
    return value

def get_db_connection():
    if POSTGRES_URL and HAS_PSYCOPG2:
        conn = psycopg2.connect(POSTGRES_URL)
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS commercial_listings (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    property_type TEXT,
                    price REAL,
                    sqft REAL,
                    floor TEXT,
                    amenities TEXT,
                    latitude REAL,
                    longitude REAL,
                    listing_url TEXT,
                    score REAL,
                    metro_name TEXT,
                    metro_distance REAL,
                    road_type TEXT,
                    visibility_score REAL,
                    catchment_tam REAL,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        conn.commit()
        return ('postgres', conn)
    else:
        try:
            conn = sqlite3.connect(DB_PATH)
        except sqlite3.OperationalError:
            # Fallback to /tmp for Vercel if root is read-only
            conn = sqlite3.connect("/tmp/listings.db")
        
        conn.row_factory = sqlite3.Row
        # Initialize schema
        conn.execute('''
            CREATE TABLE IF NOT EXISTS commercial_listings (
                id TEXT PRIMARY KEY,
                title TEXT,
                property_type TEXT,
                price REAL,
                sqft REAL,
                floor TEXT,
                amenities TEXT,
                latitude REAL,
                longitude REAL,
                listing_url TEXT,
                score REAL,
                metro_name TEXT,
                metro_distance REAL,
                road_type TEXT,
                visibility_score REAL,
                catchment_tam REAL,
                raw_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        return ('sqlite', conn)

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Allow", "GET, POST, DELETE, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_DELETE(self):
        if not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": {"code": "authentication_required"}},
                401,
            )
            return
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            listing_id = params.get("id", [None])[0]
            
            if not listing_id:
                self.send_json_response({"status": "error", "message": "Missing id parameter"}, 400)
                return
                
            db_type, conn = get_db_connection()
            if db_type == 'postgres':
                with conn.cursor() as cur:
                    if listing_id == 'all':
                        cur.execute("DELETE FROM commercial_listings")
                    else:
                        cur.execute("DELETE FROM commercial_listings WHERE id = %s", (listing_id,))
            else:
                if listing_id == 'all':
                    conn.execute("DELETE FROM commercial_listings")
                else:
                    conn.execute("DELETE FROM commercial_listings WHERE id = ?", (listing_id,))
            conn.commit()
            conn.close()
            
            self.send_json_response({"status": "success", "message": "Listing(s) deleted"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def do_GET(self):
        if not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": {"code": "authentication_required"}},
                401,
            )
            return
        try:
            db_type, conn = get_db_connection()
            if db_type == 'postgres':
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        f"SELECT {LISTING_COLUMNS} FROM commercial_listings "
                        "ORDER BY score DESC, created_at DESC"
                    )
                    rows = cur.fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {LISTING_COLUMNS} FROM commercial_listings "
                    "ORDER BY score DESC, created_at DESC"
                ).fetchall()
            conn.close()
            
            listings = []
            for row in rows:
                listing = dict(row)
                if listing.get("created_at"):
                    listing["created_at"] = str(listing["created_at"])
                if listing.get("raw_data"):
                    listing["raw_data"] = strip_legacy_school_fields(json.loads(listing["raw_data"]))
                listings.append(listing)
                
            self.send_json_response({"status": "success", "data": listings})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def do_POST(self):
        if not is_authorized(self.headers):
            self.send_json_response(
                {"status": "error", "error": {"code": "authentication_required"}},
                401,
            )
            return
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data)
            
            listing_id = data.get("listing_id")
            if not listing_id:
                self.send_json_response({"status": "error", "message": "Missing listing_id"}, 400)
                return
                
            title = data.get("title", "Custom Listing")
            property_type = data.get("property_type", "Office Space")
            price = float(data.get("price", 0))
            sqft = float(data.get("sqft", 0))
            floor = data.get("floor", "Mid")
            amenities = ",".join(data.get("amenities", []))
            lat = float(data.get("latitude", 0))
            lon = float(data.get("longitude", 0))
            url = data.get("listing_url", "")
            
            score = float(data.get("commercial_score", 0))
            metro = data.get("metro", {})
            metro_name = metro.get("nearest_station", "NA")
            metro_dist = float(metro.get("distance_km", 0))
            
            visibility = data.get("visibility", {})
            road_type = visibility.get("road_type", "Unknown")
            visibility_score = float(visibility.get("score", 0))
            
            catchment = data.get("catchment", {})
            metrics = catchment.get("metrics", {})
            residential = catchment.get("residential_market", {}).get("inside_isochrone", {})
            tam = float(residential.get("family_tam", metrics.get("countable_family_tam", 0)) or 0)
            
            raw_data = json.dumps(strip_legacy_school_fields(data))
            
            db_type, conn = get_db_connection()
            
            if db_type == 'postgres':
                with conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO commercial_listings 
                        (id, title, property_type, price, sqft, floor, amenities, latitude, longitude, listing_url, score, metro_name, metro_distance, road_type, visibility_score, catchment_tam, raw_data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET 
                        title = EXCLUDED.title,
                        property_type = EXCLUDED.property_type,
                        price = EXCLUDED.price,
                        sqft = EXCLUDED.sqft,
                        floor = EXCLUDED.floor,
                        amenities = EXCLUDED.amenities,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        listing_url = EXCLUDED.listing_url,
                        score = EXCLUDED.score,
                        metro_name = EXCLUDED.metro_name,
                        metro_distance = EXCLUDED.metro_distance,
                        road_type = EXCLUDED.road_type,
                        visibility_score = EXCLUDED.visibility_score,
                        catchment_tam = EXCLUDED.catchment_tam,
                        raw_data = EXCLUDED.raw_data
                    ''', (listing_id, title, property_type, price, sqft, floor, amenities, lat, lon, url, score, metro_name, metro_dist, road_type, visibility_score, tam, raw_data))
            else:
                conn.execute('''
                    INSERT OR REPLACE INTO commercial_listings 
                    (id, title, property_type, price, sqft, floor, amenities, latitude, longitude, listing_url, score, metro_name, metro_distance, road_type, visibility_score, catchment_tam, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (listing_id, title, property_type, price, sqft, floor, amenities, lat, lon, url, score, metro_name, metro_dist, road_type, visibility_score, tam, raw_data))
                
            conn.commit()
            conn.close()
            
            self.send_json_response({"status": "success", "message": "Listing saved"})
        except Exception as e:
            self.send_json_response({"status": "error", "message": str(e)}, 500)

    def send_json_response(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
