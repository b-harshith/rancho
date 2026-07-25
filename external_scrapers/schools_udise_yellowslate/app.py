from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from udise_scraper.database import Database
from udise_scraper.pool import CollectorPool


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("UDISE_DB", ROOT / "data/runtime/udise_data.sqlite3"))
PINCODES_PATH = Path(os.environ.get("UDISE_PINCODES", ROOT / "data/input/pincodes.json"))
CHROME_PATH = os.environ.get(
    "UDISE_CHROME",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
HEADLESS = os.environ.get("UDISE_HEADLESS", "1") != "0"
BROWSER_CONCURRENCY = max(1, min(int(os.environ.get("UDISE_BROWSER_CONCURRENCY", "20")), 30))

log_handler = RotatingFileHandler(
    ROOT / "logs/udise_scraper.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(log_handler)

app = Flask(__name__)
database = Database(DB_PATH)
collector = CollectorPool(database, CHROME_PATH, HEADLESS, BROWSER_CONCURRENCY)


@app.after_request
def disable_dashboard_cache(response: Response) -> Response:
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


def load_pincodes() -> list[str]:
    values = json.loads(PINCODES_PATH.read_text(encoding="utf-8"))
    pincodes: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = str(value).strip()
        if re.fullmatch(r"\d{6}", code) and code not in seen:
            seen.add(code)
            pincodes.append(code)
    if not pincodes:
        raise ValueError("No valid six-digit PIN codes were found")
    return pincodes


@app.get("/")
def index() -> str:
    return render_template(
        "index.html", headless=HEADLESS, browser_concurrency=BROWSER_CONCURRENCY
    )


@app.get("/api/status")
def api_status() -> Response:
    return jsonify(database.status())


@app.post("/api/start")
def api_start() -> tuple[Response, int] | Response:
    if collector.running:
        return jsonify({"error": "A job is already running"}), 409
    try:
        pincodes = load_pincodes()
        body = request.get_json(silent=True) or {}
        limit = body.get("limit")
        if limit is not None:
            limit = max(1, min(int(limit), len(pincodes)))
            pincodes = pincodes[:limit]
        job_id = database.create_job(pincodes)
        collector.start(job_id)
        return jsonify({"job_id": job_id, "pincodes": len(pincodes)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/captcha")
def api_captcha() -> tuple[Response, int] | Response:
    body = request.get_json(silent=True) or {}
    try:
        challenge_id = body.get("challenge_id")
        if challenge_id is None:
            raise ValueError("Dashboard is outdated. Reload the page before submitting CAPTCHA.")
        collector.submit_captcha(int(challenge_id), str(body.get("code") or ""))
        return jsonify({"accepted": True})
    except (TypeError, ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/stop")
def api_stop() -> Response:
    collector.stop()
    return jsonify({"stopping": True})


@app.post("/api/retry/<int:job_id>")
def api_retry(job_id: int) -> tuple[Response, int] | Response:
    if collector.running:
        return jsonify({"error": "A job is already running"}), 409
    retry = database.prepare_retry(job_id)
    if retry["retry_pincodes"] == 0:
        return jsonify({"error": "There are no failed PINs or schools to retry"}), 400
    database.log_event(job_id, "info", "retry.prepared", "Prepared targeted retry", retry)
    collector.start(job_id)
    return jsonify({"job_id": job_id, **retry})


@app.get("/api/captcha/<int:challenge_id>")
def api_captcha_image(challenge_id: int) -> tuple[Response, int] | Response:
    image = database.challenge_image(challenge_id)
    if not image:
        return jsonify({"error": "CAPTCHA not found"}), 404
    return jsonify({"image": image})


@app.get("/api/export/<int:job_id>")
def api_export(job_id: int) -> Response:
    payload = json.dumps(database.export_job(job_id), ensure_ascii=False, indent=2)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="udise-job-{job_id}.json"'},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5050")), debug=False)
