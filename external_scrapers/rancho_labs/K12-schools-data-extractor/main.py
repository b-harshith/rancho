"""
main.py — CLI Entry Point
──────────────────────────
Exposes all pipeline commands via Typer with rich terminal UI.

Commands:
    run          Full ETL pipeline for a city
    debug-url    Single-school debug (crawl + LLM + print JSON)
    clean        Reset database and cached data
    status       Show pipeline progress summary
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from config.settings import (
    BROWSER_FLUSH_INTERVAL,
    CACHE_DIR,
    EXTRACTED_TEXT_DIR,
    LOG_LEVEL,
    LOGS_DIR,
    OUTPUT_DIR,
    RAW_PDF_DIR,
    SEED_CACHE_FILE,
    SQLITE_DB_PATH,
)

# ──────────────────────────────────────────────
# Typer app
# ──────────────────────────────────────────────
app = typer.Typer(
    name="k12-extractor",
    help="K12 Schools Data Extractor — scrape, crawl, extract, and structure school data.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()


# ──────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────
def _setup_logging(level: str = LOG_LEVEL) -> None:
    """Configure rich logging for the CLI."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # File handler
    file_handler = logging.FileHandler(LOGS_DIR / "pipeline.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s")
    )

    # Rich console handler
    console_handler = RichHandler(
        console=console,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[file_handler, console_handler],
        force=True,
    )


# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────


@app.command()
def run(
    city: str = typer.Option(..., "--city", "-c", help="Target city (e.g., 'bangalore')"),
    limit: int = typer.Option(3000, "--limit", "-l", help="Maximum schools to scrape"),
    force_seed: bool = typer.Option(False, "--force-seed", help="Force re-scrape of seed lists, ignoring cache"),
    include_failed: bool = typer.Option(False, "--include-failed", help="Include failed schools in export"),
) -> None:
    """
    [bold green]Run the full ETL pipeline[/bold green] for a city.

    Initializes the DB, runs the Seed Generator, and executes all pipeline stages:
    Seed → Crawl → Extract → LLM → Validate → Export
    """
    _setup_logging()
    asyncio.run(_run_pipeline(city, limit, force_seed, include_failed))


async def _run_pipeline(city: str, limit: int, force_seed: bool, include_failed: bool) -> None:
    """Async pipeline orchestrator."""
    from src.exporter import export_master_database
    from src.enricher_udise import enrich_all_pending_schools
    from src.scraper_uniapply import scrape_uniapply_listings
    from src.state import StateManager
    from src.utils.browser import BrowserPool
    from src.validator import validate_all_pending

    logger = logging.getLogger("pipeline")

    console.rule("[bold blue]K12 Schools Data Extractor[/bold blue]")
    console.print(f"City: [cyan]{city}[/cyan] | Limit: [cyan]{limit}[/cyan] | Force seed: [cyan]{force_seed}[/cyan]")

    async with StateManager() as state_mgr:
        pool = BrowserPool()
        await pool.start()

        try:
            # ── Stage 1: UniApply Listing Scrape & Fee Harvesting ──
            console.rule("[bold]Stage 1: Seed Generation & Fee Scrape (UniApply)[/bold]")
            if SEED_CACHE_FILE.exists() and not force_seed:
                use_cache = typer.confirm(
                    "Cached seed list found. Use cache?", default=True
                )
                if not use_cache:
                    force_seed = True

            if SEED_CACHE_FILE.exists() and not force_seed:
                import pandas as pd
                seed_df = pd.read_csv(str(SEED_CACHE_FILE))
            else:
                import pandas as pd
                schools = await scrape_uniapply_listings(city, pool, state_mgr, max_schools=limit)
                seed_df = pd.DataFrame(schools)
                if not seed_df.empty:
                    seed_df.to_csv(str(SEED_CACHE_FILE), index=False)

            console.print(f"  Seeds loaded: [green]{len(seed_df)}[/green] schools")

            if seed_df.empty:
                console.print("[yellow]No schools found. Exiting.[/yellow]")
                return

            # ── Stage 2: UDISE+ Metrics Enrichment ──
            console.rule("[bold]Stage 2: UDISE+ Metrics Enrichment[/bold]")
            enriched_count = await enrich_all_pending_schools(pool, state_mgr, max_concurrency=5)
            console.print(f"  UDISE+ Enriched: [green]{enriched_count}[/green] schools")

            # ── Stage 3: Text Extraction (Bypassed) ──
            console.rule("[bold dim]Stage 3: Text Extraction (Bypassed)[/bold dim]")

            # ── Stage 4: LLM Processing (Bypassed) ──
            console.rule("[bold dim]Stage 4: LLM Processing (Bypassed)[/bold dim]")

            # ── Stage 5: Validation ──
            console.rule("[bold]Stage 5: Validation[/bold]")
            val_count = await validate_all_pending(state_mgr)
            console.print(f"  Validated: [green]{val_count}[/green] schools")

            # ── Stage 6: Export ──
            console.rule("[bold]Stage 6: Export[/bold]")
            xlsx_path, json_path = await export_master_database(state_mgr, include_failed=include_failed)
            console.print(f"  Excel: [cyan]{xlsx_path}[/cyan]")
            console.print(f"  JSON:  [cyan]{json_path}[/cyan]")

            # ── Summary ──
            console.rule("[bold green]Pipeline Complete[/bold green]")
            await _print_status_table(state_mgr)

        finally:
            await pool.stop()


@app.command("debug-url")
def debug_url(
    url: str = typer.Argument(..., help="School website URL to debug"),
) -> None:
    """
    [bold yellow]Debug mode[/bold yellow] for a single school URL.

    Runs the crawler and prints the LLM-structured JSON to terminal.
    """
    _setup_logging("DEBUG")
    asyncio.run(_debug_url(url))


async def _debug_url(url: str) -> None:
    """Debug a single URL through the pipeline."""
    import json as json_mod

    from src.crawler_locator import crawl_school
    from src.llm_engine import process_school_text
    from src.parser_text import extract_text_for_school
    from src.state import StateManager
    from src.utils.browser import BrowserPool

    logger = logging.getLogger("debug")

    school_id = "DEBUG_SCHOOL"
    console.rule("[bold yellow]Debug Mode[/bold yellow]")
    console.print(f"URL: [cyan]{url}[/cyan]")

    async with StateManager() as state_mgr:
        pool = BrowserPool()
        await pool.start()

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                # ── Crawl ──
                console.print("\n[bold]Crawling...[/bold]")
                result = await crawl_school(school_id, url, pool, session, state_mgr)
                console.print(f"  Compliance doc: {result.compliance_doc_path or '[dim]None[/dim]'}")
                console.print(f"  Fees doc:       {result.fees_doc_path or '[dim]None[/dim]'}")

                # ── Extract text ──
                console.print("\n[bold]Extracting text...[/bold]")
                text = await extract_text_for_school(
                    school_id, result.compliance_doc_path, result.fees_doc_path, state_mgr
                )
                if text:
                    console.print(f"  Extracted [green]{len(text)}[/green] chars")
                    console.print(f"  Preview: {text[:500]}...")
                else:
                    console.print("  [yellow]No text extracted.[/yellow]")
                    return

                # ── LLM ──
                console.print("\n[bold]Running LLM...[/bold]")
                llm_result = await process_school_text(school_id, text, state_mgr)
                if llm_result:
                    console.print("\n[bold green]Structured Output:[/bold green]")
                    console.print_json(llm_result.model_dump_json(indent=2))
                else:
                    console.print("  [yellow]LLM returned no result.[/yellow]")

        finally:
            await pool.stop()


@app.command()
def clean(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    [bold red]Clean[/bold red] — delete the SQLite database and all cached/raw data.
    """
    _setup_logging()

    if not confirm:
        confirm = typer.confirm("This will delete all data. Continue?", default=False)
        if not confirm:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Abort()

    # Delete DB
    if SQLITE_DB_PATH.exists():
        SQLITE_DB_PATH.unlink()
        console.print(f"  Deleted DB: [red]{SQLITE_DB_PATH}[/red]")

    # Delete data directories
    for d in [CACHE_DIR, RAW_PDF_DIR, EXTRACTED_TEXT_DIR, OUTPUT_DIR]:
        if d.exists():
            shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            console.print(f"  Cleared: [red]{d}[/red]")

    console.print("[green]Clean complete.[/green]")


@app.command()
def status() -> None:
    """Show current pipeline progress summary."""
    _setup_logging()
    asyncio.run(_show_status())


async def _show_status() -> None:
    from src.state import StateManager

    if not SQLITE_DB_PATH.exists():
        console.print("[yellow]No database found. Run the pipeline first.[/yellow]")
        return

    async with StateManager() as state_mgr:
        await _print_status_table(state_mgr)


async def _print_status_table(state_mgr) -> None:
    """Render a rich table showing pipeline status counts."""
    counts = await state_mgr.count_by_status()
    total = await state_mgr.total_count()

    table = Table(title="Pipeline Status", show_header=True, header_style="bold cyan")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Pct", justify="right")

    for status, count in sorted(counts.items()):
        pct = f"{100 * count / max(total, 1):.1f}%"
        # Color-code by status type
        if status in ("VALIDATED", "EXPORTED"):
            style = "green"
        elif status in ("DEAD_LINK", "BOT_BLOCKED", "ENCRYPTED_PDF", "TIMEOUT", "LLM_ERROR", "UNKNOWN_ERROR"):
            style = "red"
        elif status == "DOCS_NOT_FOUND":
            style = "yellow"
        else:
            style = "white"
        table.add_row(f"[{style}]{status}[/{style}]", str(count), pct)

    table.add_row("[bold]TOTAL[/bold]", f"[bold]{total}[/bold]", "100%")
    console.print(table)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app()
