"""Abstract base class for all site scrapers."""

from abc import ABC, abstractmethod
import asyncio
import random
import logging
from typing import Any

from playwright.async_api import async_playwright, Page, Browser


class BaseScraper(ABC):
    """Abstract base class for all site scrapers.

    Subclasses must implement:
        - scrape_listing_page: Extract vehicle summaries from a listing page.
        - scrape_detail_page: Extract full details from a single vehicle page.
        - get_listing_urls: Return seed URLs to crawl.
        - site_name: Property returning a human-readable site identifier.
    """

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.stats = {"pages_crawled": 0, "records_fetched": 0, "errors": 0}

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def scrape_listing_page(self, page: Page, url: str) -> list[dict]:
        """Parse a listing/search-results page and return a list of raw
        vehicle dicts (or stubs with at least a detail URL)."""
        ...

    @abstractmethod
    async def scrape_detail_page(self, page: Page, url: str) -> dict:
        """Parse a single vehicle detail page and return a raw vehicle dict."""
        ...

    @abstractmethod
    def get_listing_urls(self) -> list[str]:
        """Return the list of listing page URLs to crawl."""
        ...

    @property
    @abstractmethod
    def site_name(self) -> str:
        """Human-readable name for this scraper target (e.g. 'truck_bank')."""
        ...

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    async def run(self, mode: str = "full") -> dict:
        """Main execution method.

        Args:
            mode: One of 'full' (listing + detail), 'listing' (listing only),
                  'detail' (detail pages from supplied URLs).

        Returns:
            Dict with 'data' (list[dict]) and 'stats'.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.config.get(
                    "user_agent",
                    (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                ),
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            try:
                results: list[dict] = []

                if mode in ("full", "listing"):
                    results = await self._crawl_listings(page)

                if mode == "full":
                    results = await self._crawl_details(page, results)

                self.stats["records_fetched"] = len(results)
                self.logger.info(
                    "Scraping complete for %s: %s", self.site_name, self.stats
                )
                return {"data": results, "stats": self.stats}
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # Internal crawling helpers
    # ------------------------------------------------------------------

    async def _crawl_listings(self, page: Page) -> list[dict]:
        """Iterate over all listing URLs and collect vehicle stubs."""
        results: list[dict] = []
        for url in self.get_listing_urls():
            await self._rate_limit()
            try:
                items = await self._retry(
                    lambda u=url: self.scrape_listing_page(page, u)
                )
                results.extend(items)
                self.stats["pages_crawled"] += 1
                self.logger.debug(
                    "Listing page %s yielded %d items", url, len(items)
                )
            except Exception as e:
                self.stats["errors"] += 1
                self.logger.error("Error scraping listing %s: %s", url, e)
        return results

    async def _crawl_details(
        self, page: Page, stubs: list[dict]
    ) -> list[dict]:
        """For each stub that has a 'detail_url', fetch the detail page."""
        enriched: list[dict] = []
        for stub in stubs:
            detail_url = stub.get("detail_url")
            if not detail_url:
                enriched.append(stub)
                continue
            await self._rate_limit()
            try:
                detail = await self._retry(
                    lambda u=detail_url: self.scrape_detail_page(page, u)
                )
                merged = {**stub, **detail}
                enriched.append(merged)
            except Exception as e:
                self.stats["errors"] += 1
                self.logger.error("Error scraping detail %s: %s", detail_url, e)
                enriched.append(stub)
        return enriched

    # ------------------------------------------------------------------
    # Rate limiting & retry
    # ------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        """Sleep for a random interval between configured min/max delays."""
        delay = random.uniform(
            self.config.get("delay_min", 3),
            self.config.get("delay_max", 7),
        )
        self.logger.debug("Rate-limit sleeping %.1fs", delay)
        await asyncio.sleep(delay)

    async def _retry(self, coro_factory, max_retries: int = 3) -> Any:
        """Retry an async callable up to *max_retries* times with
        exponential back-off.

        Args:
            coro_factory: A zero-argument callable that returns a coroutine.
            max_retries: Maximum number of attempts (default 3).

        Returns:
            The result of a successful invocation.

        Raises:
            The last exception if all retries are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                return await coro_factory()
            except Exception as e:
                last_exc = e
                wait = 2**attempt + random.uniform(0, 1)
                self.logger.warning(
                    "Attempt %d/%d failed (%s). Retrying in %.1fs...",
                    attempt,
                    max_retries,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]
