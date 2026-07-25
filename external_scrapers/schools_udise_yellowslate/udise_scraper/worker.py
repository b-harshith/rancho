from __future__ import annotations

import base64
import json
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .cdp import CDPBrowser, CDPError
from .database import Database, utc_now


logger = logging.getLogger(__name__)
REPORT_BATCH_SEMAPHORE = threading.BoundedSemaphore(
    max(1, int(os.environ.get("UDISE_REPORT_BATCH_CONCURRENCY", "6")))
)


BASE_URL = "https://kys.udiseplus.gov.in/"
SEARCH_URL = BASE_URL + "#/advancesearch"
API_MARKER = "/web-app/api/"
SEARCH_MARKER = API_MARKER + "search-schools?"
CAPTCHA_SELECTOR = 'input[placeholder="Enter Captcha"]'
PIN_SELECTOR = 'input[maxlength="6"]:not([placeholder])'


@dataclass
class Context:
    job_id: int
    pincode: str | None = None
    school_id: str | None = None
    year_id: str | None = None
    phase: str = "bootstrap"


class Collector:
    def __init__(self, database: Database, chrome_path: str, headless: bool = True):
        self.db = database
        self.chrome_path = chrome_path
        self.headless = headless
        self.browser: CDPBrowser | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.captcha_answers: queue.Queue[str] = queue.Queue(maxsize=1)
        self.challenge_id: int | None = None
        self.context = Context(job_id=0)
        self._requests: dict[str, dict[str, Any]] = {}
        self._responses: dict[str, dict[str, Any]] = {}
        self._capture_queue: queue.Queue[str] = queue.Queue()
        self._ledger_queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._captured: list[dict[str, Any]] = []
        self._captured_condition = threading.Condition()
        self._capture_thread: threading.Thread | None = None
        self._ledger_thread: threading.Thread | None = None
        self._ocr_reader = None

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, job_id: int) -> None:
        if self.running:
            raise RuntimeError("A collection job is already running")
        self.stop_event.clear()
        self.context = Context(job_id=job_id)
        self.thread = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        self.thread.start()

    def start_task(self, job_id: int, pin_task_id: int) -> None:
        if self.running:
            raise RuntimeError("This browser worker is already running")
        self.stop_event.clear()
        self.context = Context(job_id=job_id)
        self.thread = threading.Thread(
            target=self._run_task, args=(job_id, pin_task_id), daemon=True
        )
        self.thread.start()

    def submit_captcha(self, code: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9]{6}", code):
            raise ValueError("CAPTCHA must contain exactly six letters or digits")
        if not self.challenge_id:
            raise RuntimeError("There is no CAPTCHA waiting for input")
        while not self.captcha_answers.empty():
            try:
                self.captcha_answers.get_nowait()
            except queue.Empty:
                break
        self.db.answer_challenge(self.challenge_id, len(code))
        self.captcha_answers.put_nowait(code)

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self, job_id: int) -> None:
        self.db.update_job(job_id, status="starting", error=None)
        self._log("info", "job.starting", "Starting Chrome and collection worker")
        try:
            self.browser = CDPBrowser(self.chrome_path, self.headless)
            self.browser.start()
            self.browser.on("Network.requestWillBeSent", self._on_request)
            self.browser.on("Network.responseReceived", self._on_response)
            self.browser.on("Network.loadingFinished", self._on_finished)
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            self._ledger_thread = threading.Thread(target=self._ledger_loop, daemon=True)
            self._ledger_thread.start()
            self.db.update_job(job_id, status="running")
            self._log("info", "browser.ready", "Chrome CDP connection is ready")
            while not self.stop_event.is_set():
                task = self.db.next_pin(job_id)
                if not task:
                    self._log("info", "job.completed", "All PIN tasks completed")
                    self.db.update_job(job_id, status="completed", current_pincode=None, current_school_id=None)
                    return
                self._process_pin(task)
            self.db.update_job(job_id, status="stopped")
        except Exception as exc:
            self._log("error", "job.failed", str(exc), exception_type=type(exc).__name__)
            self.db.fail_active_pins(job_id, str(exc))
            self.db.update_job(job_id, status="failed", error=str(exc))
        finally:
            self.stop_event.set()
            if self.browser:
                self.browser.close()
                self.browser = None

    def _run_task(self, job_id: int, pin_task_id: int) -> None:
        task = self.db.get_pin(pin_task_id)
        if not task:
            return
        self.context = Context(job_id=job_id, pincode=task["pincode"])
        try:
            self.browser = CDPBrowser(self.chrome_path, self.headless)
            self.browser.start()
            self.browser.on("Network.requestWillBeSent", self._on_request)
            self.browser.on("Network.responseReceived", self._on_response)
            self.browser.on("Network.loadingFinished", self._on_finished)
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            self._ledger_thread = threading.Thread(target=self._ledger_loop, daemon=True)
            self._ledger_thread.start()
            self._log("info", "browser.ready", "Dedicated PIN browser session is ready")
            self._process_pin(task)
        except Exception as exc:
            self._log("error", "pin.failed", str(exc), exception_type=type(exc).__name__)
            self.db.update_pin(pin_task_id, status="failed", error=str(exc))
        finally:
            self.stop_event.set()
            if self.browser:
                self.browser.close()
                self.browser = None

    def _process_pin(self, task: dict[str, Any]) -> None:
        job_id = self.context.job_id
        pin = task["pincode"]
        task_id = int(task["id"])
        self.context = Context(job_id, pincode=pin, phase="search")
        self.db.update_pin(task_id, status="running", started_at=utc_now(), error=None)
        self.db.update_job(job_id, current_pincode=pin, current_school_id=None, status="running")
        self._log("info", "pin.started", f"Starting PIN {pin}", pin_task_id=task_id)

        search_payload = None
        for attempt in range(1, 6):
            if self.stop_event.is_set():
                return
            self.db.update_pin(task_id, captcha_attempts=attempt)
            self._stage_search(pin)
            image = self._captcha_image()
            self.challenge_id = self.db.create_challenge(job_id, task_id, image)
            try:
                captcha = self._solve_captcha(image)
                self.db.answer_challenge(self.challenge_id, len(captcha))
                self._log(
                    "info", "captcha.ocr_solved", f"OCR solved CAPTCHA for PIN {pin}: {captcha}",
                    challenge_id=self.challenge_id, attempt=attempt,
                )
            except Exception as e:
                self._log(
                    "error", "captcha.ocr_failed", f"OCR failed to solve CAPTCHA: {str(e)}",
                    challenge_id=self.challenge_id, attempt=attempt,
                )
                captcha = ""
            search_payload = self._submit_search(pin, captcha)
            if self._successful_search(search_payload):
                self._log("info", "search.success", f"Search API succeeded for PIN {pin}")
                break
            self._log(
                "warning", "search.rejected", f"Search rejected for PIN {pin}; requesting a new CAPTCHA",
                attempt=attempt, response_status=search_payload.get("status"),
                error=search_payload.get("error"),
            )
        else:
            self.db.update_pin(task_id, status="failed", error="CAPTCHA/search failed after five attempts")
            return

        schools = self._extract_schools(search_payload)
        self._log("info", "schools.extracted", f"Extracted {len(schools)} schools for PIN {pin}")
        for school in schools:
            self.db.save_school(job_id, pin, school)
        self.db.update_pin(task_id, school_count=len(schools))
        self.db.update_job(job_id, total_schools=self._job_school_count(job_id))

        pending_schools = [
            row for row in self.db.schools_for_pin(job_id, pin)
            if row["status"] in {"pending", "failed", "running"}
        ]
        for offset in range(0, len(pending_schools), 5):
            if self.stop_event.is_set():
                return
            self._process_school_batch(pending_schools[offset:offset + 5])

        self.db.update_pin(task_id, status="completed", completed_at=utc_now())
        status = self.db.status(job_id)
        completed = sum(1 for item in status["pins"] if item["status"] == "completed")
        self.db.update_job(job_id, completed_pincodes=completed, current_school_id=None)

    def _wait_for_captcha(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return None
            try:
                return self.captcha_answers.get(timeout=min(1.0, deadline - time.monotonic()))
            except queue.Empty:
                continue
        raise RuntimeError("CAPTCHA input timed out")

    def _solve_captcha(self, image_data_url: str) -> str:
        import easyocr
        if self._ocr_reader is None:
            self._ocr_reader = easyocr.Reader(['en'])
        if image_data_url.startswith("data:image/png;base64,"):
            header, base64_data = image_data_url.split(",", 1)
            img_bytes = base64.b64decode(base64_data)
            result = self._ocr_reader.readtext(img_bytes)
            text = "".join([res[1] for res in result]).replace(" ", "")
            text = re.sub(r'[^A-Za-z0-9]', '', text)
            return text
        raise ValueError("Invalid CAPTCHA image format")

    def _stage_search(self, pincode: str) -> None:
        assert self.browser
        self.context.phase = "search"
        self._log("debug", "search.navigate", f"Opening search page for PIN {pincode}")
        self.browser.navigate(SEARCH_URL)
        self.browser.wait_until("document.readyState === 'complete'", timeout=30)
        self.browser.wait_until("document.querySelector('#pinCode') !== null", timeout=30)
        self.browser.click("#pinCode")
        self.browser.wait_until(f"document.querySelector({json.dumps(PIN_SELECTOR)}) !== null")
        self.browser.set_input_value(PIN_SELECTOR, pincode)
        self._log("debug", "search.pin_bound", "PIN value bound to the UDISE+ form", pincode=pincode)
        self.browser.wait_until(
            "(() => { const i=document.querySelector('img[src^=\"data:image/png;base64,\"]'); return i && i.src.length>100; })()",
            timeout=20,
        )

    def _captcha_image(self) -> str:
        assert self.browser
        value = self.browser.evaluate(
            "(() => { const imgs=[...document.images].filter(i=>i.src.startsWith('data:image/png;base64,')); "
            "return imgs.length ? imgs[imgs.length-1].src : null; })()"
        )
        if not value:
            raise RuntimeError("CAPTCHA image was not found")
        return str(value)

    def _submit_search(self, pincode: str, captcha: str) -> dict[str, Any]:
        assert self.browser
        before = len(self._captured)
        query = urlencode({"searchType": 4, "searchParam": pincode, "captcha": captcha})
        search_url = f"{BASE_URL}web-app/api/search-schools?{query}"
        self._log(
            "info", "search.requesting", "Issuing search-schools in the active browser session",
            pincode=pincode, captcha_length=len(captcha),
            url=f"{BASE_URL}web-app/api/search-schools?searchType=4&searchParam={pincode}&captcha=[REDACTED]",
        )
        result = self.browser.evaluate(
            f"fetch({json.dumps(search_url)},{{headers:{{'Accept':'application/json'}}}})"
            ".then(async r=>({statusCode:r.status,text:await r.text()}))"
        )
        self._log(
            "debug", "search.fetch_completed", "Browser fetch completed",
            status_code=result.get("statusCode"), body_bytes=len(result.get("text") or ""),
        )
        try:
            record = self._wait_for_response(
                lambda item: SEARCH_MARKER in item["url"] and f"searchParam={pincode}" in item["url"],
                before,
                timeout=15,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                "Browser received search-schools, but the response-capture queue did not persist it"
            ) from exc
        try:
            payload = json.loads(record["body_text"])
            self._log(
                "info", "search.response", "Captured search-schools response",
                url=record["url"], status_code=record.get("status_code"),
                body_bytes=len(record.get("body_text") or ""),
            )
            return payload
        except json.JSONDecodeError:
            return {"status": False, "error": {"message": "Search response was not JSON"}}

    @staticmethod
    def _successful_search(payload: dict[str, Any]) -> bool:
        return payload.get("status") is True

    @staticmethod
    def _extract_schools(payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data") or {}
        content = data.get("content") if isinstance(data, dict) else []
        if isinstance(content, dict):
            content = content.get("content") or []
        return [item for item in (content or []) if isinstance(item, dict)]

    def _process_school(self, school: dict[str, Any]) -> None:
        assert self.browser
        school_id = school["school_id"]
        source_year_id = school["year_id"] or "11"
        year_id = "11" if source_year_id in {"12", "13"} else source_year_id
        row_id = int(school["id"])
        self.context = Context(self.context.job_id, school["pincode"], school_id, year_id, "know_more")
        self.db.update_job(self.context.job_id, current_school_id=school_id)
        self.db.update_school(row_id, status="running", error=None)
        self._log(
            "info", "know_more.started", f"Opening Know More for school {school_id}",
            school_id=school_id, year_id=year_id,
        )
        start_count = len(self._captured)
        try:
            try:
                self.browser.navigate(f"{BASE_URL}#/schooldetail/{school_id}/{year_id}")
                self.browser.wait_until("document.readyState === 'complete'", timeout=15)
                self._wait_for_report_settle(start_count, timeout=6, minimum=1)
                self._log(
                    "debug", "know_more.captured", f"Know More APIs captured for {school_id}",
                    school_id=school_id,
                )
            except Exception as know_more_error:
                self._log(
                    "warning", "know_more.skipped",
                    f"Know More produced no usable API response for {school_id}; continuing with direct APIs",
                    school_id=school_id, error=str(know_more_error),
                )
            self.context.phase = "report_card"
            report_start = len(self._captured)
            self._fetch_report_card_apis(school_id, year_id)
            self._wait_for_report_settle(report_start, timeout=25, minimum=8)
            self.db.update_school(row_id, status="completed")
            captured_count = len(self._captured) - start_count
            self._log(
                "info", "report_card.completed", f"Report-card capture completed for {school_id}",
                school_id=school_id, captured_responses=captured_count,
            )
        except Exception as exc:
            self.db.update_school(row_id, status="failed", error=str(exc))
            self._log(
                "error", "report_card.failed", f"Report-card capture failed for {school_id}: {exc}",
                school_id=school_id,
            )
        status = self.db.status(self.context.job_id)
        _, completed = self.db.school_counts(self.context.job_id)
        self.db.update_job(self.context.job_id, completed_schools=completed)
        time.sleep(0.75)

    def _process_school_batch(self, schools: list[dict[str, Any]]) -> None:
        assert self.browser
        if not schools:
            return
        job_id = self.context.job_id
        pin = schools[0]["pincode"]
        ids = [row["school_id"] for row in schools]
        self.context = Context(job_id, pin, phase="report_card")
        self.db.update_job(job_id, current_school_id=",".join(ids))
        for row in schools:
            self.db.update_school(int(row["id"]), status="running", error=None)
        self._log(
            "info", "school_batch.started", f"Processing {len(schools)} schools concurrently",
            school_ids=ids,
        )
        specs: list[dict[str, str]] = []
        for row in schools:
            school_id = row["school_id"]
            source_year_id = row["year_id"] or "11"
            year_id = "11" if source_year_id in {"12", "13"} else source_year_id
            identifier = "udiseSchCode" if len(school_id) >= 11 else "schoolId"
            api_root = f"{BASE_URL}web-app/api/"
            urls = [
                f"{api_root}school/by-year?{identifier}={school_id}&year={year_id}&action=2",
                f"{api_root}school/report-card?{identifier}={school_id}&yearId={year_id}",
                f"{api_root}school/facility?{identifier}={school_id}&yearId={year_id}",
                f"{api_root}school/profile?{identifier}={school_id}&yearId={year_id}",
                f"{api_root}school-statistics/enrolment-teacher?{identifier}={school_id}&yearId={year_id}",
                *[
                    f"{api_root}getSocialData?flag={flag}&schoolId={school_id}&yearId={year_id}"
                    for flag in range(1, 6)
                ],
            ]
            specs.extend({"schoolId": school_id, "url": url} for url in urls)
        start_count = len(self._captured)
        try:
            with REPORT_BATCH_SEMAPHORE:
                results = self._fetch_specs(specs)
                self._wait_for_report_settle(start_count, timeout=30, minimum=max(1, len(specs) - 2))
            by_school: dict[str, list[dict[str, Any]]] = {school_id: [] for school_id in ids}
            for result in results:
                by_school[result["schoolId"]].append(result)
            fallback_ids = [
                school_id for school_id, items in by_school.items()
                if any("school/report-card?" in item["url"] and item.get("apiStatus") is False for item in items)
            ]
            if fallback_ids:
                fallback_specs: list[dict[str, str]] = []
                for row in schools:
                    if row["school_id"] not in fallback_ids:
                        continue
                    fallback_specs.extend(self._school_api_specs(row["school_id"], "12"))
                fallback_start = len(self._captured)
                self._log(
                    "warning", "school_batch.year_fallback",
                    f"Retrying {len(fallback_ids)} schools with internal report year 12",
                    school_ids=fallback_ids,
                )
                with REPORT_BATCH_SEMAPHORE:
                    fallback_results = self._fetch_specs(fallback_specs)
                    self._wait_for_report_settle(
                        fallback_start, timeout=30, minimum=max(1, len(fallback_specs) - 2)
                    )
                for school_id in fallback_ids:
                    by_school[school_id] = [
                        item for item in fallback_results if item["schoolId"] == school_id
                    ]
            for row in schools:
                transport_failures = [
                    item for item in by_school[row["school_id"]] if item.get("status") != 200
                ]
                missing_sections = [
                    item for item in by_school[row["school_id"]]
                    if item.get("status") == 200 and item.get("apiStatus") is False
                ]
                if transport_failures:
                    self.db.update_school(
                        int(row["id"]), status="failed",
                        error=f"{len(transport_failures)} report API transport request(s) failed",
                    )
                elif missing_sections:
                    self.db.update_school(
                        int(row["id"]), status="partial",
                        error=f"{len(missing_sections)} report section(s) unavailable",
                    )
                else:
                    self.db.update_school(int(row["id"]), status="completed")
            self._log(
                "info", "school_batch.completed", f"Completed batch of {len(schools)} schools",
                school_ids=ids, request_count=len(specs),
            )
        except Exception as exc:
            for row in schools:
                self.db.update_school(int(row["id"]), status="failed", error=str(exc))
            self._log(
                "error", "school_batch.failed", f"School batch failed: {exc}", school_ids=ids,
            )
        _, completed = self.db.school_counts(job_id)
        self.db.update_job(job_id, completed_schools=completed)
        time.sleep(0.25)

    def _school_api_specs(self, school_id: str, year_id: str) -> list[dict[str, str]]:
        identifier = "udiseSchCode" if len(school_id) >= 11 else "schoolId"
        api_root = f"{BASE_URL}web-app/api/"
        urls = [
            f"{api_root}school/by-year?{identifier}={school_id}&year={year_id}&action=2",
            f"{api_root}school/report-card?{identifier}={school_id}&yearId={year_id}",
            f"{api_root}school/facility?{identifier}={school_id}&yearId={year_id}",
            f"{api_root}school/profile?{identifier}={school_id}&yearId={year_id}",
            f"{api_root}school-statistics/enrolment-teacher?{identifier}={school_id}&yearId={year_id}",
            *[
                f"{api_root}getSocialData?flag={flag}&schoolId={school_id}&yearId={year_id}"
                for flag in range(1, 6)
            ],
        ]
        return [{"schoolId": school_id, "url": url} for url in urls]

    def _fetch_specs(self, specs: list[dict[str, str]]) -> list[dict[str, Any]]:
        assert self.browser
        return self.browser.evaluate(
            f"Promise.all({json.dumps(specs)}.map(async item => {{"
            "try { const r=await fetch(item.url,{headers:{'Accept':'application/json'}}); "
            "const text=await r.text(); let data=null; try{data=JSON.parse(text)}catch{} "
            "return {...item,status:r.status,bytes:text.length,apiStatus:data?.status??null,"
            "message:data?.message||data?.error?.errorDetails?.details||null}; } "
            "catch(e){ return {...item,status:0,error:String(e)}; }}))"
        )

    def _fetch_report_card_apis(self, school_id: str, year_id: str) -> None:
        assert self.browser
        identifier = "udiseSchCode" if len(school_id) >= 11 else "schoolId"
        api_root = f"{BASE_URL}web-app/api/"
        urls = [
            f"{api_root}school/by-year?{identifier}={school_id}&year={year_id}&action=2",
            f"{api_root}school/report-card?{identifier}={school_id}&yearId={year_id}",
            f"{api_root}school/facility?{identifier}={school_id}&yearId={year_id}",
            f"{api_root}school/profile?{identifier}={school_id}&yearId={year_id}",
            f"{api_root}school-statistics/enrolment-teacher?{identifier}={school_id}&yearId={year_id}",
            *[
                f"{api_root}getSocialData?flag={flag}&schoolId={school_id}&yearId={year_id}"
                for flag in range(1, 6)
            ],
        ]
        self._log(
            "info", "report_card.requesting",
            f"Requesting {len(urls)} report-card API payloads for {school_id}",
            school_id=school_id, year_id=year_id,
        )
        results = self.browser.evaluate(
            f"Promise.all({json.dumps(urls)}.map(async url => {{"
            "try { const r=await fetch(url,{headers:{'Accept':'application/json'}}); "
            "const text=await r.text(); return {url,status:r.status,bytes:text.length}; } "
            "catch(e){ return {url,status:0,error:String(e)}; }}))"
        )
        self._log(
            "debug", "report_card.fetch_completed", "Report-card API fan-out completed",
            results=results,
        )

    def _wait_for_report_settle(self, start_count: int, timeout: float, minimum: int = 5) -> None:
        deadline = time.monotonic() + timeout
        last_count = start_count
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            with self._captured_condition:
                current = len(self._captured)
                if current != last_count:
                    last_count = current
                    last_change = time.monotonic()
                relevant = [
                    item for item in self._captured[start_count:]
                    if item["phase"] == self.context.phase and API_MARKER in item["url"]
                ]
                if len(relevant) >= minimum and time.monotonic() - last_change >= 1.5:
                    return
                self._captured_condition.wait(timeout=0.25)
        if len(self._captured) == start_count:
            raise RuntimeError("No report-card API responses were captured")

    def _on_request(self, event: dict[str, Any]) -> None:
        request = event.get("request") or {}
        context = Context(**self.context.__dict__)
        self._requests[event["requestId"]] = {
            "method": request.get("method"),
            "url": request.get("url"),
            "headers": request.get("headers") or {},
        }
        url = request.get("url") or ""
        if context.job_id and url.startswith(("http://", "https://")):
            self._ledger_queue.put(("request", {
                "job_id": context.job_id,
                "pincode": context.pincode,
                "school_id": context.school_id,
                "year_id": context.year_id,
                "phase": context.phase,
                "request_id": event["requestId"],
                "method": request.get("method"),
                "url": url,
                "resource_type": event.get("type"),
                "headers": request.get("headers") or {},
                "post_data": request.get("postData"),
            }))

    def _on_response(self, event: dict[str, Any]) -> None:
        response = event.get("response") or {}
        url = response.get("url") or ""
        mime = (response.get("mimeType") or "").lower()
        self._ledger_queue.put(("response", {
            "job_id": self.context.job_id,
            "request_id": event["requestId"],
            "status": response.get("status"),
            "mime_type": mime,
        }))
        if API_MARKER not in url:
            return
        if "json" not in mime and not url.endswith("getCaptcha"):
            return
        query = parse_qs(urlparse(url).query)
        response_school_id = (query.get("schoolId") or query.get("udiseSchCode") or [None])[0]
        response_year_id = (query.get("yearId") or query.get("year") or [None])[0]
        self._responses[event["requestId"]] = {
            "url": url,
            "status_code": response.get("status"),
            "mime_type": mime,
            "headers": response.get("headers") or {},
            "context": Context(
                self.context.job_id,
                self.context.pincode,
                response_school_id or self.context.school_id,
                response_year_id or self.context.year_id,
                self.context.phase,
            ),
        }

    def _on_finished(self, event: dict[str, Any]) -> None:
        request_id = event["requestId"]
        if request_id in self._responses:
            self._capture_queue.put(request_id)

    def _capture_loop(self) -> None:
        while not self.stop_event.is_set() or not self._capture_queue.empty():
            try:
                request_id = self._capture_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            response = self._responses.pop(request_id, None)
            request = self._requests.pop(request_id, {})
            if not response or not self.browser:
                continue
            try:
                body = self.browser.call("Network.getResponseBody", {"requestId": request_id}, timeout=10)
                text = body.get("body") or ""
                if body.get("base64Encoded"):
                    text = base64.b64decode(text).decode("utf-8", errors="replace")
            except CDPError:
                continue
            context: Context = response.pop("context")
            record = {
                "job_id": context.job_id,
                "pincode": context.pincode,
                "school_id": context.school_id,
                "year_id": context.year_id,
                "phase": context.phase,
                "request_id": request_id,
                "method": request.get("method"),
                "request_headers": request.get("headers") or {},
                "response_headers": response.pop("headers"),
                "body_text": text,
                **response,
            }
            self.db.save_response(record)
            with self._captured_condition:
                self._captured.append(record)
                self._captured_condition.notify_all()

    def _ledger_loop(self) -> None:
        while not self.stop_event.is_set() or not self._ledger_queue.empty():
            try:
                action, record = self._ledger_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if action == "request":
                self.db.save_request(record)
            else:
                self.db.update_request_response(
                    record["job_id"], record["request_id"],
                    record.get("status"), record.get("mime_type"),
                )

    def _wait_for_response(self, predicate: Any, start: int, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self._captured_condition:
            while time.monotonic() < deadline:
                for item in self._captured[start:]:
                    if predicate(item):
                        return item
                self._captured_condition.wait(timeout=min(0.5, deadline - time.monotonic()))
        raise RuntimeError("Timed out waiting for the search API response")

    def _job_school_count(self, job_id: int) -> int:
        total, _ = self.db.school_counts(job_id)
        return total

    def _log(self, level: str, event: str, message: str, **details: Any) -> None:
        job_id = self.context.job_id
        getattr(logger, "warning" if level == "warning" else level)(
            "%s: %s details=%s", event, message, details
        )
        if job_id:
            self.db.log_event(job_id, level, event, message, details)
