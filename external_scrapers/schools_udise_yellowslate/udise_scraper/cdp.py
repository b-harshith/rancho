from __future__ import annotations

import json
import logging
import queue
import sys
import socket
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import requests
import websocket


logger = logging.getLogger(__name__)


class CDPError(RuntimeError):
    pass


class CDPBrowser:
    def __init__(self, chrome_path: str, headless: bool = True):
        self.chrome_path = chrome_path
        self.headless = headless
        self.port = self._free_port()
        self.profile = tempfile.TemporaryDirectory(prefix="udise-chrome-")
        self.process: subprocess.Popen[bytes] | None = None
        self.ws: websocket.WebSocket | None = None
        self._next_id = 0
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._event_handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._receiver: threading.Thread | None = None

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self) -> None:
        args = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile.name}",
            "--remote-allow-origins=*",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,900",
            "about:blank",
        ]
        if self.headless:
            args.insert(1, "--headless=new")
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        version_url = f"http://127.0.0.1:{self.port}/json/version"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if requests.get(version_url, timeout=0.5).ok:
                    break
            except requests.RequestException:
                time.sleep(0.1)
        else:
            raise CDPError("Chrome did not expose its DevTools endpoint")

        target = requests.put(
            f"http://127.0.0.1:{self.port}/json/new?about:blank", timeout=3
        ).json()
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=5)
        self.ws.settimeout(None)
        self._receiver = threading.Thread(target=self._receive_loop, daemon=True)
        self._receiver.start()
        self.call("Page.enable")
        self.call("Network.enable", {"maxTotalBufferSize": 100_000_000, "maxResourceBufferSize": 20_000_000})
        self.call("Runtime.enable")

    def close(self) -> None:
        self._closed.set()
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.profile.cleanup()

    def on(self, method: str, callback: Callable[[dict[str, Any]], None]) -> None:
        self._event_handlers[method].append(callback)

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
        if not self.ws:
            raise CDPError("Browser is not started")
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
            self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        try:
            message = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            self._pending.pop(request_id, None)
            logger.error(
                "CDP timeout method=%s request_id=%s receiver_alive=%s closed=%s pending=%s",
                method, request_id,
                bool(self._receiver and self._receiver.is_alive()),
                self._closed.is_set(), len(self._pending),
            )
            raise CDPError(f"Timed out waiting for {method}") from exc
        if "error" in message:
            raise CDPError(f"{method}: {message['error']}")
        return message.get("result", {})

    def _receive_loop(self) -> None:
        assert self.ws is not None
        while not self._closed.is_set():
            try:
                raw_message = self.ws.recv()
                if not raw_message:
                    if self._closed.is_set():
                        return
                    raise CDPError("Chrome DevTools WebSocket closed unexpectedly")
                message = json.loads(raw_message)
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:
                if not self._closed.is_set():
                    logger.exception("CDP receiver stopped: %s", exc)
                if not self._closed.is_set():
                    self._closed.set()
                return
            if "id" in message:
                pending = self._pending.pop(int(message["id"]), None)
                if pending:
                    pending.put(message)
                continue
            method = message.get("method")
            if method:
                for callback in tuple(self._event_handlers.get(method, ())):
                    try:
                        callback(message.get("params") or {})
                    except Exception:
                        continue

    def navigate(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})

    def evaluate(self, expression: str, return_by_value: bool = True) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": return_by_value, "awaitPromise": True},
        )
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise CDPError(remote.get("description", "Evaluation failed"))
        return remote.get("value")

    def wait_until(self, expression: str, timeout: float = 20, interval: float = 0.2) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(expression)
            if value:
                return value
            time.sleep(interval)
        raise CDPError(f"Timed out waiting for page state: {expression[:80]}")

    def element_center(self, selector: str) -> tuple[float, float]:
        encoded = json.dumps(selector)
        rect = self.wait_until(
            f"(() => {{ const e=document.querySelector({encoded}); if(!e) return null; "
            "const r=e.getBoundingClientRect(); if(!r.width||!r.height) return null; "
            "return {x:r.left+r.width/2,y:r.top+r.height/2}; })()"
        )
        return float(rect["x"]), float(rect["y"])

    def click(self, selector: str) -> None:
        x, y = self.element_center(selector)
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})

    def key(self, key: str, modifiers: int = 0) -> None:
        text = key if len(key) == 1 and modifiers == 0 else ""
        params = {"type": "keyDown", "key": key, "text": text, "unmodifiedText": text, "modifiers": modifiers}
        self.call("Input.dispatchKeyEvent", params)
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "modifiers": modifiers})

    def replace_text(self, selector: str, value: str) -> None:
        self.click(selector)
        self.key("a", modifiers=4 if sys.platform == "darwin" else 2)
        self.key("Backspace")
        for character in value:
            self.key(character)

    def set_input_value(self, selector: str, value: str) -> None:
        selector_json = json.dumps(selector)
        value_json = json.dumps(value)
        changed = self.evaluate(
            f"(() => {{ const e=document.querySelector({selector_json}); if(!e) return false; "
            "const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; "
            f"setter.call(e,{value_json}); "
            "e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:null})); "
            "e.dispatchEvent(new Event('change',{bubbles:true})); return e.value; })()"
        )
        if changed != value:
            raise CDPError(f"Input value did not update for {selector}")
