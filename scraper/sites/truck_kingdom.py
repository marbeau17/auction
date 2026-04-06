"""Scraper for truck-kingdom.com (トラック王国)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.async_api import Page

from scraper.base import BaseScraper
from scraper.utils import clean_text, normalize_price, normalize_mileage, normalize_year


class TruckKingdomScraper(BaseScraper):
    """Site-specific scraper for truck-kingdom.com.

    Truck Kingdom is a major Japanese commercial vehicle marketplace.
    Listings are organised by vehicle size category with paginated search
    results.
    """

    BASE_URL = "https://www.truck-kingdom.com"

    CATEGORIES = [
        "large-truck",
        "medium-truck",
        "small-truck",
        "trailer",
    ]

    # ------------------------------------------------------------------
    # Selector strategies
    # ------------------------------------------------------------------
    # Each group lists multiple CSS selectors to try, ordered from most
    # specific (likely from current site structure) to more generic
    # fallbacks.  The first selector that matches wins.

    _CARD_SELECTORS = [
        ".vehicle-card",
        ".p-searchResultItem",
        ".search-result-item",
        ".truck-item",
        "[class*='vehicle-list'] > li",
        "[class*='result'] [class*='item']",
        ".l-main .mod-list > li",
    ]

    _TITLE_SELECTORS = [
        ".vehicle-card__title",
        ".p-searchResultItem__title",
        ".truck-item__name",
        "h2 a", "h3 a",
        "[class*='title'] a",
        "[class*='name'] a",
        "a[class*='title']",
    ]

    _PRICE_SELECTORS = [
        ".vehicle-card__price",
        ".p-searchResultItem__price",
        ".truck-item__price",
        "[class*='price']",
        ".price",
    ]

    _YEAR_SELECTORS = [
        ".vehicle-card__year",
        ".p-searchResultItem__year",
        "[class*='year']",
        "[class*='nenshiki']",
        "td:has(th:text('年式')) + td",
    ]

    _MILEAGE_SELECTORS = [
        ".vehicle-card__mileage",
        ".p-searchResultItem__mileage",
        "[class*='mileage']",
        "[class*='km']",
        "[class*='soukou']",
    ]

    _IMAGE_SELECTORS = [
        ".vehicle-card__image img",
        ".p-searchResultItem__image img",
        ".truck-item__photo img",
        "[class*='image'] img",
        "[class*='photo'] img",
        "[class*='thumb'] img",
        "img[class*='vehicle']",
    ]

    _LINK_SELECTORS = [
        ".vehicle-card__title a",
        ".p-searchResultItem__title a",
        "h2 a", "h3 a",
        "a[class*='detail']",
        "a[href*='/detail/']",
        "a[href*='/truck/']",
    ]

    _MAKER_SELECTORS = [
        ".vehicle-card__maker",
        "[class*='maker']",
        "[class*='manufacturer']",
    ]

    _BODY_TYPE_SELECTORS = [
        ".vehicle-card__body",
        "[class*='body-type']",
        "[class*='bodytype']",
        "[class*='keitai']",
    ]

    _LOCATION_SELECTORS = [
        ".vehicle-card__location",
        "[class*='area']",
        "[class*='location']",
        "[class*='prefecture']",
    ]

    # ------------------------------------------------------------------
    # Detail page spec-table selectors
    # ------------------------------------------------------------------

    _SPEC_TABLE_SELECTORS = [
        "table.spec-table",
        "table.p-specTable",
        "table[class*='spec']",
        ".detail-spec table",
        ".vehicle-detail table",
        "#spec table",
        "table",
    ]

    # ------------------------------------------------------------------
    # Abstract interface implementation
    # ------------------------------------------------------------------

    @property
    def site_name(self) -> str:
        return "truck_kingdom"

    def get_listing_urls(self) -> list[str]:
        """Generate listing page URLs for all truck categories."""
        max_pages = self.config.get("max_pages", 20)
        urls: list[str] = []
        for cat in self.CATEGORIES:
            for page_num in range(1, max_pages + 1):
                urls.append(f"{self.BASE_URL}/list/{cat}/?page={page_num}")
        return urls

    # ------------------------------------------------------------------
    # Listing page scraping
    # ------------------------------------------------------------------

    async def scrape_listing_page(self, page: Page, url: str) -> list[dict]:
        """Scrape a single listing page and return raw vehicle dicts."""
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Locate all vehicle cards using resilient selector strategy
        items = await self._find_vehicle_cards(page)
        if not items:
            return []

        results: list[dict] = []
        for item in items:
            try:
                data = await self._parse_listing_item(page, item)
                if data and data.get("url"):
                    results.append(data)
            except Exception as exc:
                self.logger.warning("Error parsing listing item: %s", exc)
        return results

    async def _find_vehicle_cards(self, page: Page) -> list:
        """Try each card selector until one returns results."""
        for sel in self._CARD_SELECTORS:
            try:
                items = await page.query_selector_all(sel)
                if items:
                    return items
            except Exception:
                continue
        return []

    async def _parse_listing_item(self, page: Page, element) -> dict | None:
        """Parse a single vehicle card from listing page.

        Returns a dict with keys:
            title, url, price, year, mileage, image_url,
            maker, body_type, location, source_id
        """
        # Title
        title = await self._text_from(element, self._TITLE_SELECTORS)
        if not title:
            return None

        # Detail URL
        detail_url = await self._href_from(element, self._LINK_SELECTORS)
        if detail_url and not detail_url.startswith("http"):
            detail_url = urljoin(self.BASE_URL, detail_url)

        # Price
        price_text = await self._text_from(element, self._PRICE_SELECTORS)

        # Year
        year_text = await self._text_from(element, self._YEAR_SELECTORS)
        if not year_text:
            # Try to extract from title (e.g. "H28 いすゞ ギガ ...")
            year_text = self._extract_year_from_title(title)

        # Mileage
        mileage_text = await self._text_from(element, self._MILEAGE_SELECTORS)

        # Image
        image_url = await self._attr_from(element, self._IMAGE_SELECTORS, "src")
        if not image_url:
            image_url = await self._attr_from(element, self._IMAGE_SELECTORS, "data-src")
        if image_url and not image_url.startswith("http"):
            image_url = urljoin(self.BASE_URL, image_url)

        # Maker
        maker = await self._text_from(element, self._MAKER_SELECTORS)

        # Body type
        body_type = await self._text_from(element, self._BODY_TYPE_SELECTORS)

        # Location
        location = await self._text_from(element, self._LOCATION_SELECTORS)

        # Source ID from URL
        source_id = ""
        if detail_url:
            m = re.search(r"/(\d{4,10})(?:[/.]|$|\?)", detail_url)
            if m:
                source_id = m.group(1)
            else:
                source_id = detail_url.rstrip("/").rsplit("/", 1)[-1]

        return {
            "title": clean_text(title),
            "url": detail_url or "",
            "detail_url": detail_url or "",
            "price": clean_text(price_text),
            "year": clean_text(year_text),
            "mileage": clean_text(mileage_text),
            "image_url": image_url or "",
            "maker": clean_text(maker),
            "body_type": clean_text(body_type),
            "location": clean_text(location),
            "source_id": source_id,
        }

    # ------------------------------------------------------------------
    # Detail page scraping
    # ------------------------------------------------------------------

    async def scrape_detail_page(self, page: Page, url: str) -> dict:
        """Scrape vehicle detail page for full specs.

        Extracts a spec table (key/value pairs) and merges with any
        additional detail-page-specific fields.
        """
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        specs = await self._extract_spec_table(page)

        # Map spec-table keys to our field names
        field_map = {
            "メーカー": "maker",
            "車名": "model_name",
            "形状": "body_type",
            "年式": "year",
            "走行距離": "mileage",
            "型式": "model_code",
            "積載量": "tonnage_text",
            "排気量": "displacement",
            "ミッション": "transmission",
            "燃料": "fuel_type",
            "所在地": "location",
            "車検": "inspection",
            "上物メーカー": "body_maker",
        }

        result: dict = {}
        for spec_key, spec_val in specs.items():
            cleaned_key = clean_text(spec_key)
            for jp_key, field_name in field_map.items():
                if jp_key in cleaned_key:
                    result[field_name] = clean_text(spec_val)
                    break

        # Extract the main image if not already captured
        if "image_url" not in result:
            for sel in [
                ".detail-image img",
                ".vehicle-detail__image img",
                "[class*='main-image'] img",
                "[class*='detail'] img[class*='main']",
                ".p-detail__mainImage img",
                "#mainImage img",
            ]:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        src = await el.get_attribute("src")
                        if src:
                            if not src.startswith("http"):
                                src = urljoin(self.BASE_URL, src)
                            result["image_url"] = src
                            break
                except Exception:
                    continue

        return result

    async def _extract_spec_table(self, page: Page) -> dict[str, str]:
        """Extract key-value pairs from the vehicle spec table."""
        specs: dict[str, str] = {}

        for table_sel in self._SPEC_TABLE_SELECTORS:
            try:
                table = await page.query_selector(table_sel)
                if not table:
                    continue

                rows = await table.query_selector_all("tr")
                if not rows:
                    continue

                for row in rows:
                    th = await row.query_selector("th")
                    td = await row.query_selector("td")
                    if th and td:
                        key = (await th.text_content() or "").strip()
                        val = (await td.text_content() or "").strip()
                        if key:
                            specs[key] = val

                # Also try dl > dt/dd pattern
                if not specs:
                    dts = await table.query_selector_all("dt")
                    dds = await table.query_selector_all("dd")
                    for dt, dd in zip(dts, dds):
                        key = (await dt.text_content() or "").strip()
                        val = (await dd.text_content() or "").strip()
                        if key:
                            specs[key] = val

                if specs:
                    break
            except Exception:
                continue

        # If table approach failed, try dl-based spec blocks
        if not specs:
            for dl_sel in [
                "dl.spec-list",
                "dl[class*='spec']",
                ".detail-spec dl",
                "dl",
            ]:
                try:
                    dl = await page.query_selector(dl_sel)
                    if not dl:
                        continue
                    dts = await dl.query_selector_all("dt")
                    dds = await dl.query_selector_all("dd")
                    for dt, dd in zip(dts, dds):
                        key = (await dt.text_content() or "").strip()
                        val = (await dd.text_content() or "").strip()
                        if key:
                            specs[key] = val
                    if specs:
                        break
                except Exception:
                    continue

        return specs

    # ------------------------------------------------------------------
    # Element helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _text_from(element, selectors: list[str]) -> str:
        """Try multiple selectors, return first non-empty text."""
        for sel in selectors:
            try:
                el = await element.query_selector(sel)
                if el:
                    txt = (await el.text_content() or "").strip()
                    if txt:
                        return txt
            except Exception:
                continue
        return ""

    @staticmethod
    async def _attr_from(element, selectors: list[str], attr: str) -> str:
        """Try multiple selectors, return first non-empty attribute value."""
        for sel in selectors:
            try:
                el = await element.query_selector(sel)
                if el:
                    val = await el.get_attribute(attr)
                    if val:
                        return val.strip()
            except Exception:
                continue
        return ""

    @staticmethod
    async def _href_from(element, selectors: list[str]) -> str:
        """Extract the first non-empty href from selector candidates."""
        return await TruckKingdomScraper._attr_from(element, selectors, "href")

    @staticmethod
    def _extract_year_from_title(title: str) -> str:
        """Try to pull a year from the listing title text."""
        # "H28" / "R4" / "2020年"
        m = re.search(r"[HhRrSs]\d{1,2}|令和\d{1,2}|平成\d{1,2}|昭和\d{1,2}|(?:19|20)\d{2}", title)
        return m.group(0) if m else ""
