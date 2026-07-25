"""
src/utils/browser.py
────────────────────
Managed Playwright browser pool with:
  • asyncio.Semaphore-throttled tab concurrency (default 4)
  • Memory-flush cycle — tears down & relaunches every N schools
  • Chromium args optimized for 8GB RAM
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright, Playwright

from config.settings import CHROMIUM_ARGS, MAX_BROWSER_CONCURRENCY, PAGE_TIMEOUT_MS

logger = logging.getLogger(__name__)


class BrowserPool:
    """
    Manages a single Chromium instance with a concurrency semaphore.

    Usage:
        pool = BrowserPool()
        await pool.start()
        async with pool.new_page() as page:
            await page.goto("https://example.com")
        await pool.stop()
    """

    def __init__(
        self,
        max_concurrency: int = MAX_BROWSER_CONCURRENCY,
        chromium_args: list[str] | None = None,
        page_timeout_ms: int = PAGE_TIMEOUT_MS,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._chromium_args = chromium_args or CHROMIUM_ARGS
        self._page_timeout_ms = page_timeout_ms
        self._semaphore = asyncio.Semaphore(max_concurrency)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._pages_served: int = 0

    # ── Lifecycle ────────────────────────────
    async def start(self) -> None:
        """Launch the Playwright Chromium instance with anti-bot evasion."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=self._chromium_args,
        )
        self._context = await self._browser.new_context(
            java_script_enabled=True,
            ignore_https_errors=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await self._context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self._context.set_default_timeout(self._page_timeout_ms)
        self._pages_served = 0
        logger.info(
            "BrowserPool started (concurrency=%d, timeout=%dms)",
            self._max_concurrency,
            self._page_timeout_ms,
        )

    async def stop(self) -> None:
        """Tear down browser and Playwright."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("BrowserPool stopped after serving %d pages.", self._pages_served)

    async def restart(self) -> None:
        """Full teardown + relaunch — the memory-flush cycle."""
        logger.info("BrowserPool memory flush — restarting Chromium...")
        await self.stop()
        await self.start()

    # ── Page checkout ────────────────────────
    @asynccontextmanager
    async def new_page(self) -> AsyncGenerator[Page, None]:
        """
        Yields a fresh Page, throttled by the semaphore.
        Automatically closes the page on exit.
        """
        async with self._semaphore:
            assert self._context is not None, "BrowserPool not started. Call .start() first."
            page = await self._context.new_page()
            self._pages_served += 1
            try:
                yield page
            finally:
                if not page.is_closed():
                    await page.close()

    # ── Helpers ──────────────────────────────
    @property
    def pages_served(self) -> int:
        return self._pages_served

    def should_flush(self, flush_interval: int) -> bool:
        """Check if we've hit the memory-flush threshold."""
        return self._pages_served > 0 and self._pages_served % flush_interval == 0
