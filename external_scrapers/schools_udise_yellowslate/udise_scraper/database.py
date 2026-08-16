from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


import zlib


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compress_text(text: str | None) -> bytes | None:
    if not text:
        return None
    return zlib.compress(text.encode("utf-8"), level=6)


def decompress_text(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, bytes):
        try:
            return zlib.decompress(val).decode("utf-8", errors="replace")
        except Exception:
            return str(val)
    return str(val)


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.create_function("decompress", 1, decompress_text)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    total_pincodes INTEGER NOT NULL DEFAULT 0,
                    completed_pincodes INTEGER NOT NULL DEFAULT 0,
                    total_schools INTEGER NOT NULL DEFAULT 0,
                    completed_schools INTEGER NOT NULL DEFAULT 0,
                    current_pincode TEXT,
                    current_school_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pin_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    pincode TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    captcha_attempts INTEGER NOT NULL DEFAULT 0,
                    school_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    UNIQUE(job_id, pincode)
                );

                CREATE TABLE IF NOT EXISTS captcha_challenges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    pin_task_id INTEGER NOT NULL REFERENCES pin_tasks(id) ON DELETE CASCADE,
                    image_data_url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'waiting',
                    submitted_length INTEGER,
                    created_at TEXT NOT NULL,
                    answered_at TEXT
                );

                CREATE TABLE IF NOT EXISTS schools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    pincode TEXT NOT NULL,
                    school_id TEXT NOT NULL,
                    udise_code TEXT,
                    year_id TEXT,
                    school_name TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    summary_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, school_id, year_id)
                );

                CREATE TABLE IF NOT EXISTS network_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    pincode TEXT,
                    school_id TEXT,
                    year_id TEXT,
                    phase TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    method TEXT,
                    url TEXT NOT NULL,
                    status_code INTEGER,
                    mime_type TEXT,
                    request_headers_json TEXT,
                    response_headers_json TEXT,
                    body_json TEXT,
                    body_text TEXT,
                    body_sha256 TEXT,
                    captured_at TEXT NOT NULL,
                    UNIQUE(job_id, request_id)
                );

                CREATE TABLE IF NOT EXISTS network_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    pincode TEXT,
                    school_id TEXT,
                    year_id TEXT,
                    phase TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    method TEXT,
                    url TEXT NOT NULL,
                    resource_type TEXT,
                    request_headers_json TEXT,
                    post_data TEXT,
                    response_status INTEGER,
                    response_mime_type TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, request_id)
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    event TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_pin_tasks_job_status
                    ON pin_tasks(job_id, status, position);
                CREATE INDEX IF NOT EXISTS idx_schools_job_pin
                    ON schools(job_id, pincode, status);
                CREATE INDEX IF NOT EXISTS idx_responses_job_context
                    ON network_responses(job_id, pincode, school_id, phase);
                CREATE INDEX IF NOT EXISTS idx_requests_job_context
                    ON network_requests(job_id, pincode, school_id, phase);
                CREATE INDEX IF NOT EXISTS idx_events_job_id
                    ON job_events(job_id, id);
                """
            )

    def create_job(self, pincodes: list[str]) -> int:
        now = utc_now()
        with self._lock, self.connect() as db:
            cursor = db.execute(
                "INSERT INTO jobs(status,total_pincodes,created_at,updated_at) VALUES(?,?,?,?)",
                ("queued", len(pincodes), now, now),
            )
            job_id = int(cursor.lastrowid)
            db.executemany(
                "INSERT INTO pin_tasks(job_id,pincode,position) VALUES(?,?,?)",
                [(job_id, code, index) for index, code in enumerate(pincodes)],
            )
            return job_id

    def recover_interrupted_job(self, job_id: int) -> dict[str, int]:
        """Return work abandoned by a terminated runner to the pending queue."""
        with self._lock, self.connect() as db:
            pin_cursor = db.execute(
                "UPDATE pin_tasks SET status='retry',error=NULL,completed_at=NULL "
                "WHERE job_id=? AND status IN ('claimed','running')",
                (job_id,),
            )
            school_cursor = db.execute(
                "UPDATE schools SET status='pending',error=NULL,updated_at=? "
                "WHERE job_id=? AND status='running'",
                (utc_now(), job_id),
            )
            challenge_cursor = db.execute(
                "UPDATE captcha_challenges SET status='superseded' "
                "WHERE job_id=? AND status='waiting'",
                (job_id,),
            )
            db.execute(
                "UPDATE jobs SET status='queued',error=NULL,current_pincode=NULL,"
                "current_school_id=NULL,updated_at=? WHERE id=?",
                (utc_now(), job_id),
            )
            return {
                "pincodes": int(pin_cursor.rowcount),
                "schools": int(school_cursor.rowcount),
                "challenges": int(challenge_cursor.rowcount),
            }

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in fields)
        with self._lock, self.connect() as db:
            db.execute(
                f"UPDATE jobs SET {assignments} WHERE id=?",
                (*fields.values(), job_id),
            )

    def log_event(
        self, job_id: int, level: str, event: str, message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "INSERT INTO job_events(job_id,level,event,message,details_json,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    job_id, level, event, message,
                    json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
                    utc_now(),
                ),
            )

    def update_pin(self, pin_task_id: int, **fields: Any) -> None:
        if not fields:
            return
        assignments = ",".join(f"{key}=?" for key in fields)
        with self._lock, self.connect() as db:
            db.execute(
                f"UPDATE pin_tasks SET {assignments} WHERE id=?",
                (*fields.values(), pin_task_id),
            )

    def fail_active_pins(self, job_id: int, error: str) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE pin_tasks SET status='failed',error=? "
                "WHERE job_id=? AND status='running'",
                (error, job_id),
            )

    def next_pin(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM pin_tasks WHERE job_id=? AND status IN ('pending','retry') "
                "ORDER BY position LIMIT 1",
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_pin(self, pin_task_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM pin_tasks WHERE id=?", (pin_task_id,)).fetchone()
            return dict(row) if row else None

    def pending_pins(self, job_id: int, limit: int) -> list[dict[str, Any]]:
        with self._lock, self.connect() as db:
            rows = db.execute(
                "SELECT * FROM pin_tasks WHERE job_id=? AND status IN ('pending','retry') "
                "ORDER BY position LIMIT ?",
                (job_id, limit),
            ).fetchall()
            if rows:
                db.executemany(
                    "UPDATE pin_tasks SET status='claimed' WHERE id=?",
                    [(row["id"],) for row in rows],
                )
            return [dict(row) for row in rows]

    def pin_status_counts(self, job_id: int) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT status,COUNT(*) AS count FROM pin_tasks WHERE job_id=? GROUP BY status",
                (job_id,),
            ).fetchall()
            return {row["status"]: int(row["count"]) for row in rows}

    def create_challenge(self, job_id: int, pin_task_id: int, image_data_url: str = "") -> int:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE captcha_challenges SET status='superseded' "
                "WHERE job_id=? AND pin_task_id=? AND status='waiting'",
                (job_id, pin_task_id),
            )
            cursor = db.execute(
                "INSERT INTO captcha_challenges(job_id,pin_task_id,image_data_url,created_at) "
                "VALUES(?,?,?,?)",
                (job_id, pin_task_id, "", utc_now()),
            )
            return int(cursor.lastrowid)

    def answer_challenge(self, challenge_id: int, length: int) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE captcha_challenges SET status='submitted',submitted_length=?,answered_at=? "
                "WHERE id=?",
                (length, utc_now(), challenge_id),
            )

    def save_school(self, job_id: int, pincode: str, school: dict[str, Any]) -> None:
        school_id = str(school.get("schoolId") or school.get("school_id") or "")
        if not school_id:
            return
        year_id = str(school.get("yearId") or "")
        now = utc_now()
        with self._lock, self.connect() as db:
            db.execute(
                """
                INSERT INTO schools(
                    job_id,pincode,school_id,udise_code,year_id,school_name,
                    summary_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id,school_id,year_id) DO UPDATE SET
                    pincode=excluded.pincode,
                    udise_code=excluded.udise_code,
                    school_name=excluded.school_name,
                    summary_json=excluded.summary_json,
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    pincode,
                    school_id,
                    school.get("udiseschCode") or school.get("udiseCode"),
                    year_id,
                    school.get("schoolName"),
                    json.dumps(school, ensure_ascii=False, separators=(",", ":")),
                    now,
                    now,
                ),
            )

    def schools_for_pin(self, job_id: int, pincode: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM schools WHERE job_id=? AND pincode=? ORDER BY id",
                (job_id, pincode),
            ).fetchall()
            return [dict(row) for row in rows]

    def school_counts(self, job_id: int) -> tuple[int, int]:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status IN ('completed','partial') THEN 1 ELSE 0 END) AS completed "
                "FROM schools WHERE job_id=?",
                (job_id,),
            ).fetchone()
            return int(row["total"] or 0), int(row["completed"] or 0)

    def prepare_retry(self, job_id: int) -> dict[str, int]:
        with self._lock, self.connect() as db:
            failed_pin_rows = db.execute(
                "SELECT id FROM pin_tasks WHERE job_id=? AND status='failed'",
                (job_id,),
            ).fetchall()
            failed_school_pins = db.execute(
                "SELECT DISTINCT pincode FROM schools WHERE job_id=? AND status='failed'",
                (job_id,),
            ).fetchall()
            pin_codes = [row["pincode"] for row in failed_school_pins]
            if pin_codes:
                placeholders = ",".join("?" for _ in pin_codes)
                db.execute(
                    f"UPDATE pin_tasks SET status='retry',error=NULL WHERE job_id=? "
                    f"AND pincode IN ({placeholders})",
                    (job_id, *pin_codes),
                )
            db.execute(
                "UPDATE pin_tasks SET status='retry',error=NULL WHERE job_id=? AND status='failed'",
                (job_id,),
            )
            failed_schools = db.execute(
                "SELECT COUNT(*) FROM schools WHERE job_id=? AND status='failed'",
                (job_id,),
            ).fetchone()[0]
            db.execute(
                "UPDATE schools SET status='pending',error=NULL WHERE job_id=? AND status='failed'",
                (job_id,),
            )
            retry_pins = db.execute(
                "SELECT COUNT(*) FROM pin_tasks WHERE job_id=? AND status='retry'",
                (job_id,),
            ).fetchone()[0]
            db.execute(
                "UPDATE jobs SET status='queued',error=NULL,updated_at=? WHERE id=?",
                (utc_now(), job_id),
            )
            return {
                "retry_pincodes": int(retry_pins),
                "retry_schools": int(failed_schools),
                "failed_pin_searches": len(failed_pin_rows),
            }

    def update_school(self, row_id: int, **fields: Any) -> None:
        fields["updated_at"] = utc_now()
        assignments = ",".join(f"{key}=?" for key in fields)
        with self._lock, self.connect() as db:
            db.execute(
                f"UPDATE schools SET {assignments} WHERE id=?",
                (*fields.values(), row_id),
            )

    def save_response(self, record: dict[str, Any]) -> None:
        body_text = record.get("body_text") or ""
        body_json = None
        try:
            parsed = json.loads(body_text)
            body_json = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, json.JSONDecodeError):
            pass
        digest = hashlib.sha256(body_text.encode("utf-8", errors="replace")).hexdigest()
        
        # Compress payloads with zlib to shrink database size by ~85%
        compressed_json = compress_text(body_json) if body_json else None
        compressed_text = compress_text(body_text) if not body_json else None
        
        values = (
            record["job_id"], record.get("pincode"), record.get("school_id"),
            record.get("year_id"), record["phase"], record["request_id"],
            record.get("method"), record["url"], record.get("status_code"),
            record.get("mime_type"), json.dumps(record.get("request_headers") or {}),
            json.dumps(record.get("response_headers") or {}), compressed_json,
            compressed_text, digest, utc_now(),
        )
        with self._lock, self.connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO network_responses(
                    job_id,pincode,school_id,year_id,phase,request_id,method,url,
                    status_code,mime_type,request_headers_json,response_headers_json,
                    body_json,body_text,body_sha256,captured_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )

    def save_request(self, record: dict[str, Any]) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO network_requests(
                    job_id,pincode,school_id,year_id,phase,request_id,method,url,
                    resource_type,request_headers_json,post_data,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record["job_id"], record.get("pincode"), record.get("school_id"),
                    record.get("year_id"), record["phase"], record["request_id"],
                    record.get("method"), record["url"], record.get("resource_type"),
                    json.dumps(record.get("headers") or {}), record.get("post_data"), utc_now(),
                ),
            )

    def update_request_response(
        self, job_id: int, request_id: str, status: int | None, mime_type: str | None
    ) -> None:
        with self._lock, self.connect() as db:
            db.execute(
                "UPDATE network_requests SET response_status=?,response_mime_type=? "
                "WHERE job_id=? AND request_id=?",
                (status, mime_type, job_id, request_id),
            )

    def status(self, job_id: int | None = None) -> dict[str, Any]:
        with self.connect() as db:
            if job_id is None:
                job = db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
            else:
                job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                return {"job": None, "pins": [], "challenge": None, "responses": 0}
            job_id = int(job["id"])
            pins = db.execute(
                "SELECT id,pincode,status,captcha_attempts,school_count,error FROM pin_tasks "
                "WHERE job_id=? ORDER BY position",
                (job_id,),
            ).fetchall()
            challenges = db.execute(
                "SELECT id,pin_task_id,status,created_at FROM captcha_challenges "
                "WHERE job_id=? AND status='waiting' ORDER BY id",
                (job_id,),
            ).fetchall()
            responses = db.execute(
                "SELECT COUNT(*) FROM network_responses WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            events = db.execute(
                "SELECT level,event,message,details_json,created_at FROM job_events "
                "WHERE job_id=? ORDER BY id DESC LIMIT 100",
                (job_id,),
            ).fetchall()
            return {
                "job": dict(job),
                "pins": [dict(row) for row in pins],
                "challenge": dict(challenges[0]) if challenges else None,
                "challenges": [dict(row) for row in challenges],
                "responses": responses,
                "events": [
                    {**dict(row), "details": json.loads(row["details_json"] or "{}")}
                    for row in events
                ],
            }

    def challenge_image(self, challenge_id: int) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT image_data_url FROM captcha_challenges WHERE id=?", (challenge_id,)
            ).fetchone()
            return row[0] if row else None

    def export_job(self, job_id: int) -> dict[str, Any]:
        with self.connect() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            pins = db.execute("SELECT * FROM pin_tasks WHERE job_id=? ORDER BY position", (job_id,)).fetchall()
            schools = db.execute("SELECT * FROM schools WHERE job_id=? ORDER BY pincode,id", (job_id,)).fetchall()
            requests = db.execute("SELECT * FROM network_requests WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
            responses = db.execute("SELECT * FROM network_responses WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
            events = db.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        def decode(row: sqlite3.Row, json_fields: tuple[str, ...]) -> dict[str, Any]:
            item = dict(row)
            for field in json_fields:
                if item.get(field):
                    val = decompress_text(item[field])
                    if val:
                        try:
                            item[field] = json.loads(val)
                        except (TypeError, json.JSONDecodeError):
                            item[field] = val
            return item
        return {
            "job": dict(job) if job else None,
            "pins": [dict(row) for row in pins],
            "schools": [decode(row, ("summary_json",)) for row in schools],
            "network_requests": [decode(row, ("request_headers_json",)) for row in requests],
            "network_responses": [decode(row, ("request_headers_json", "response_headers_json", "body_json")) for row in responses],
            "events": [decode(row, ("details_json",)) for row in events],
        }
