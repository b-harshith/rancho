#!/usr/bin/env python3
import csv
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "schools" / "processed"
TOOL_DIR = ROOT / "schools" / "review_tool"
DATA_PATH = TOOL_DIR / "manual_review_data.json"
BBOX_PATH = PROCESSED / "manual_city_outskirts_bounding_boxes.geojson"
DECISIONS_PATH = PROCESSED / "school_coordinate_review_decisions.csv"

DECISION_FIELDS = [
    "udise_code",
    "school_name",
    "chosen_source",
    "chosen_latitude",
    "chosen_longitude",
    "saved_at",
    "udise_latitude",
    "udise_longitude",
    "google_latitude",
    "google_longitude",
    "udise_google_distance_m",
    "fee_band_calibrated",
    "coordinate_reason",
]


def read_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def read_decisions():
    if not DECISIONS_PATH.exists():
        return {}
    with DECISIONS_PATH.open(newline="", encoding="utf-8") as f:
        return {row["udise_code"]: row for row in csv.DictReader(f)}


def write_decisions(decisions):
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DECISIONS_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DECISION_FIELDS)
        writer.writeheader()
        for code in sorted(decisions):
            writer.writerow({field: decisions[code].get(field, "") for field in DECISION_FIELDS})
    os.replace(tmp, DECISIONS_PATH)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path).path
        if route in ("/", "/index.html"):
            self.send_file(TOOL_DIR / "index.html", "text/html; charset=utf-8")
        elif route == "/api/data":
            self.send_json({"schools": read_json(DATA_PATH), "decisions": read_decisions()})
        elif route == "/api/bboxes":
            self.send_json(read_json(BBOX_PATH))
        elif route == "/api/status":
            data = read_json(DATA_PATH)
            decisions = read_decisions()
            self.send_json({"total": len(data), "saved": len(decisions), "output": str(DECISIONS_PATH)})
        else:
            self.send_error(404)

    def do_POST(self):
        route = urlparse(self.path).path
        if route != "/api/save":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            code = str(payload["udise_code"]).strip()
            decisions = read_decisions()
            decisions[code] = {field: payload.get(field, "") for field in DECISION_FIELDS}
            write_decisions(decisions)
            self.send_json({"ok": True, "saved": len(decisions), "output": str(DECISIONS_PATH)})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)


def main():
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Review tool running at http://{host}:{port}/")
    print(f"Saving decisions to {DECISIONS_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
