"""Scraper job scheduler and orchestrator.

Coordinates running site scrapers, parsing results, and upserting records
into the database via Supabase.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from supabase import Client

from scraper.parsers.vehicle_parser import VehicleParser
from scraper.sites import SCRAPERS

logger = logging.getLogger(__name__)


class ScraperScheduler:
    """Orchestrates scraper execution, parsing, and database upserts.

    Usage::

        from app.db.supabase_client import get_supabase_client
        scheduler = ScraperScheduler(
            supabase_client=get_supabase_client(service_role=True),
            config={"max_pages": 5},
        )
        stats = await scheduler.run_site("truck_kingdom", mode="full")
    """

    def __init__(self, supabase_client: Client, config: dict[str, Any]):
        self.client = supabase_client
        self.config = config
        self.parser = VehicleParser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_site(self, site_name: str, mode: str = "full") -> dict[str, Any]:
        """Run the scraper for a specific site.

        Steps:
            1. Create a ``scraping_logs`` entry (status=running).
            2. Instantiate and run the site scraper.
            3. Parse and clean the raw results.
            4. Upsert valid records to the ``vehicles`` table.
            5. Update the log entry with final stats.

        Args:
            site_name: Key in :data:`scraper.sites.SCRAPERS`.
            mode: ``"full"`` (listing + detail) or ``"listing"`` (listing only).

        Returns:
            Dict of run stats.
        """
        if site_name not in SCRAPERS:
            raise ValueError(
                f"Unknown site '{site_name}'. "
                f"Available: {', '.join(SCRAPERS.keys())}"
            )

        # 1. Create log entry
        log_id = await self._create_log(site_name)

        stats: dict[str, Any] = {
            "site": site_name,
            "mode": mode,
            "new_records": 0,
            "updated_records": 0,
            "skipped_records": 0,
            "error_count": 0,
            "total_scraped": 0,
            "total_parsed": 0,
        }

        try:
            # 2. Run scraper
            scraper_cls = SCRAPERS[site_name]
            scraper = scraper_cls(config=self.config)
            run_result = await scraper.run(mode=mode)
            raw_items = run_result.get("data", [])
            scraper_stats = run_result.get("stats", {})

            stats["total_scraped"] = len(raw_items)
            stats["pages_crawled"] = scraper_stats.get("pages_crawled", 0)

            # 3. Parse and normalize
            parsed_items = self.parser.parse_batch(raw_items, source_site=site_name)
            stats["total_parsed"] = len(parsed_items)

            # 4. Upsert to database
            for record in parsed_items:
                try:
                    result = await self._upsert_vehicle(record)
                    if result == "new":
                        stats["new_records"] += 1
                    elif result == "updated":
                        stats["updated_records"] += 1
                    else:
                        stats["skipped_records"] += 1
                except Exception as exc:
                    stats["error_count"] += 1
                    logger.warning(
                        "upsert_failed: source_id=%s, error=%s",
                        record.get("source_id", "?"),
                        str(exc),
                    )

            # 5. Mark log as completed
            await self._update_log(log_id, "completed", stats)
            logger.info("scraper_run_complete: site=%s, stats=%s", site_name, stats)

        except Exception as exc:
            stats["error_count"] += 1
            await self._update_log(
                log_id,
                "failed",
                stats,
                error_details={"error": str(exc)},
            )
            logger.error("scraper_run_failed: site=%s, error=%s", site_name, str(exc))
            raise

        return stats

    async def run_all(self, mode: str = "full") -> dict[str, Any]:
        """Run all configured scrapers sequentially.

        Returns:
            Dict mapping site_name -> run stats.
        """
        all_stats: dict[str, Any] = {}
        for site_name in SCRAPERS:
            try:
                all_stats[site_name] = await self.run_site(site_name, mode=mode)
            except Exception as exc:
                logger.error(
                    "run_all: site %s failed: %s", site_name, str(exc)
                )
                all_stats[site_name] = {"error": str(exc)}
        return all_stats

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    async def _create_log(self, site_name: str) -> str:
        """Insert a new scraping_logs row and return its id."""
        result = (
            self.client.table("scraping_logs")
            .insert(
                {
                    "source_site": site_name,
                    "status": "running",
                    "triggered_by": self.config.get("triggered_by", "manual"),
                }
            )
            .execute()
        )
        return result.data[0]["id"]

    async def _update_log(
        self,
        log_id: str,
        status: str,
        stats: dict[str, Any],
        error_details: dict | None = None,
    ) -> None:
        """Update an existing scraping_logs row with final stats."""
        update_data: dict[str, Any] = {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "processed_pages": stats.get("pages_crawled", 0),
            "new_records": stats.get("new_records", 0),
            "updated_records": stats.get("updated_records", 0),
            "skipped_records": stats.get("skipped_records", 0),
            "error_count": stats.get("error_count", 0),
        }
        if error_details:
            update_data["error_details"] = error_details

        self.client.table("scraping_logs").update(update_data).eq(
            "id", log_id
        ).execute()

    async def _upsert_vehicle(self, record: dict[str, Any]) -> str:
        """Upsert a vehicle record, returning 'new', 'updated', or 'skipped'.

        Uses the unique constraint (source_site, source_id) for conflict
        resolution.
        """
        source_site = record.get("source_site", "")
        source_id = record.get("source_id", "")

        if not source_site or not source_id:
            return "skipped"

        # Check if record already exists
        existing = (
            self.client.table("vehicles")
            .select("id, price_yen, mileage_km")
            .eq("source_site", source_site)
            .eq("source_id", source_id)
            .limit(1)
            .execute()
        )

        # Build DB-compatible dict (only columns that exist in the table)
        db_fields = {
            "source_site", "source_url", "source_id", "model_name",
            "model_year", "mileage_km", "price_yen", "price_tax_included",
            "tonnage", "transmission", "fuel_type",
            "location_prefecture", "image_url", "scraped_at", "is_active",
        }
        db_record = {k: v for k, v in record.items() if k in db_fields}
        db_record["is_active"] = True

        # Strip fields that need foreign keys (handled separately)
        # maker -> manufacturer_id, body_type -> body_type_id resolved below

        # Resolve manufacturer_id from maker name
        maker = record.get("maker", "")
        if maker:
            mfr = (
                self.client.table("manufacturers")
                .select("id")
                .eq("name", maker)
                .limit(1)
                .execute()
            )
            if mfr.data:
                db_record["manufacturer_id"] = mfr.data[0]["id"]

        # Resolve body_type_id from body_type name
        body_type = record.get("body_type", "")
        if body_type:
            bt = (
                self.client.table("body_types")
                .select("id")
                .eq("name", body_type)
                .limit(1)
                .execute()
            )
            if bt.data:
                db_record["body_type_id"] = bt.data[0]["id"]

        # category_id is required; infer from body_type's category or default
        if "category_id" not in db_record and body_type:
            bt_with_cat = (
                self.client.table("body_types")
                .select("category_id")
                .eq("name", body_type)
                .limit(1)
                .execute()
            )
            if bt_with_cat.data and bt_with_cat.data[0].get("category_id"):
                db_record["category_id"] = bt_with_cat.data[0]["category_id"]

        # Fallback: get any category (required NOT NULL field)
        if "category_id" not in db_record:
            cats = (
                self.client.table("vehicle_categories")
                .select("id")
                .limit(1)
                .execute()
            )
            if cats.data:
                db_record["category_id"] = cats.data[0]["id"]

        # manufacturer_id is also NOT NULL; fallback
        if "manufacturer_id" not in db_record:
            mfrs = (
                self.client.table("manufacturers")
                .select("id")
                .limit(1)
                .execute()
            )
            if mfrs.data:
                db_record["manufacturer_id"] = mfrs.data[0]["id"]

        if existing.data:
            # Record exists -- update if anything changed
            existing_row = existing.data[0]
            existing_id = existing_row["id"]

            price_changed = (
                db_record.get("price_yen") is not None
                and db_record.get("price_yen") != existing_row.get("price_yen")
            )

            # Track price history if price changed
            if price_changed and db_record.get("price_yen") is not None:
                try:
                    self.client.table("vehicle_price_history").insert(
                        {
                            "source_site": source_site,
                            "source_vehicle_id": source_id,
                            "price_yen": db_record["price_yen"],
                            "price_tax_included": db_record.get(
                                "price_tax_included", False
                            ),
                        }
                    ).execute()
                except Exception as exc:
                    logger.warning(
                        "price_history_insert_failed: %s", str(exc)
                    )

            self.client.table("vehicles").update(db_record).eq(
                "id", existing_id
            ).execute()
            return "updated"
        else:
            # New record
            self.client.table("vehicles").insert(db_record).execute()

            # Record initial price in history
            if db_record.get("price_yen") is not None:
                try:
                    self.client.table("vehicle_price_history").insert(
                        {
                            "source_site": source_site,
                            "source_vehicle_id": source_id,
                            "price_yen": db_record["price_yen"],
                            "price_tax_included": db_record.get(
                                "price_tax_included", False
                            ),
                        }
                    ).execute()
                except Exception as exc:
                    logger.warning(
                        "price_history_insert_failed: %s", str(exc)
                    )

            return "new"
