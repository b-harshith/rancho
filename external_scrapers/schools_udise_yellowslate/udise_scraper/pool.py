from __future__ import annotations

import logging
import threading
import time

from .database import Database
from .worker import Collector


logger = logging.getLogger(__name__)


class CollectorPool:
    """Stage five sessions, then stage the next five when at most two remain."""

    def __init__(
        self, database: Database, chrome_path: str, headless: bool = True,
        max_browsers: int = 10,
    ):
        self.db = database
        self.chrome_path = chrome_path
        self.headless = headless
        self.max_browsers = max(1, min(max_browsers, 10))
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.children: dict[int, Collector] = {}
        self._lock = threading.RLock()
        self.job_id: int | None = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, job_id: int) -> None:
        if self.running:
            raise RuntimeError("A collection job is already running")
        self.job_id = job_id
        self.stop_event.clear()
        self.children = {}
        self.thread = threading.Thread(target=self._coordinate, args=(job_id,), daemon=True)
        self.thread.start()

    def submit_captcha(self, challenge_id: int, code: str) -> None:
        with self._lock:
            for child in self.children.values():
                if child.challenge_id == challenge_id:
                    child.submit_captcha(code)
                    return
        raise RuntimeError("The CAPTCHA session is no longer active")

    def stop(self) -> None:
        self.stop_event.set()
        with self._lock:
            for child in self.children.values():
                child.stop()

    def _coordinate(self, job_id: int) -> None:
        self.db.update_job(job_id, status="starting", error=None)
        self.db.log_event(
            job_id, "info", "pool.starting",
            f"Starting browser pool with capacity {self.max_browsers}",
        )
        try:
            while not self.stop_event.is_set():
                with self._lock:
                    finished = [task_id for task_id, child in self.children.items() if not child.running]
                    for task_id in finished:
                        self.children.pop(task_id, None)
                    active = len(self.children)
                counts = self.db.pin_status_counts(job_id)
                remaining = counts.get("pending", 0) + counts.get("retry", 0)
                terminal = counts.get("completed", 0) + counts.get("failed", 0)
                total = sum(counts.values())
                if terminal == total and active == 0:
                    final_status = "completed" if not counts.get("failed", 0) else "completed_with_errors"
                    self.db.update_job(job_id, status=final_status, current_pincode=None, current_school_id=None)
                    self.db.log_event(job_id, "info", "pool.completed", "All PIN browser sessions finished", counts)
                    return
                # Keep all browser slots occupied while PIN tasks remain.
                available_slots = self.max_browsers - active
                if remaining and available_slots > 0:
                    batch = self.db.pending_pins(job_id, min(available_slots, remaining))
                    if batch:
                        self.db.log_event(
                            job_id, "info", "pool.wave_staged",
                            f"Staging {len(batch)} new PIN browser sessions",
                            {"pincodes": [task["pincode"] for task in batch], "active_before": active},
                        )
                    for task in batch:
                        child = Collector(self.db, self.chrome_path, self.headless)
                        with self._lock:
                            self.children[int(task["id"])] = child
                        child.start_task(job_id, int(task["id"]))
                self._refresh_job_counts(job_id)
                time.sleep(0.5)
            self.db.update_job(job_id, status="stopped")
        except Exception as exc:
            logger.exception("Collector pool failed")
            self.db.update_job(job_id, status="failed", error=str(exc))
            self.db.log_event(job_id, "error", "pool.failed", str(exc))
            self.stop()

    def _refresh_job_counts(self, job_id: int) -> None:
        counts = self.db.pin_status_counts(job_id)
        total_schools, completed_schools = self.db.school_counts(job_id)
        self.db.update_job(
            job_id,
            status="waiting_captcha" if counts.get("running", 0) or counts.get("claimed", 0) else "running",
            completed_pincodes=counts.get("completed", 0),
            total_schools=total_schools,
            completed_schools=completed_schools,
        )
