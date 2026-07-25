"""Rich terminal progress logging."""

from __future__ import annotations

import sys
from datetime import datetime

IS_TTY = sys.stdout.isatty()


class ProgressLogger:
    """Simple progress logger with optional Rich formatting."""

    def __init__(self, title: str = "Pipeline"):
        self.title = title
        self._console = None
        if IS_TTY:
            try:
                from rich.console import Console
                self._console = Console()
            except ImportError:
                pass

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def info(self, msg: str):
        line = f"[{self._ts()}] [INFO]  {msg}"
        if self._console:
            self._console.print(f"[cyan]{line}[/cyan]")
        else:
            print(line, flush=True)

    def success(self, msg: str):
        line = f"[{self._ts()}] [OK]    {msg}"
        if self._console:
            self._console.print(f"[green]{line}[/green]")
        else:
            print(line, flush=True)

    def warn(self, msg: str):
        line = f"[{self._ts()}] [WARN]  {msg}"
        if self._console:
            self._console.print(f"[yellow]{line}[/yellow]")
        else:
            print(line, flush=True)

    def error(self, msg: str):
        line = f"[{self._ts()}] [ERROR] {msg}"
        if self._console:
            self._console.print(f"[red]{line}[/red]")
        else:
            print(line, flush=True)

    def stage(self, name: str, detail: str = ""):
        sep = " — " if detail else ""
        line = f"[{self._ts()}] ▶ STAGE: {name}{sep}{detail}"
        if self._console:
            self._console.print(f"\n[bold magenta]{line}[/bold magenta]")
        else:
            print(f"\n{line}", flush=True)

    def event(self, code: str, name: str, status: str, details: str = ""):
        line = f"[{self._ts()}] [{status:8s}] {code} | {name[:40]} | {details}"
        print(line, flush=True)

    def progress(self, current: int, total: int, label: str = ""):
        pct = (current / total * 100) if total else 0
        line = f"[{self._ts()}] [{current}/{total}] ({pct:.0f}%) {label}"
        if self._console:
            self._console.print(f"[dim]{line}[/dim]", end="\r")
        else:
            print(line, end="\r", flush=True)
