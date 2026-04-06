#!/usr/bin/env python3
"""CLI for running scrapers manually.

Usage examples::

    # Run all scrapers (full mode)
    python -m scripts.run_scraper

    # Run a specific site
    python -m scripts.run_scraper --site truck_kingdom

    # Quick mode (first page only per category)
    python -m scripts.run_scraper --site steerlink --mode listing

    # Dry run (scrape + parse but skip DB writes)
    python -m scripts.run_scraper --site truck_kingdom --dry-run

    # Limit pages
    python -m scripts.run_scraper --site truck_kingdom --max-pages 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work when invoked as a script
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from scraper.parsers.vehicle_parser import VehicleParser
from scraper.sites import SCRAPERS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run commercial vehicle scrapers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--site",
        choices=list(SCRAPERS.keys()),
        default=None,
        help="Site to scrape. If omitted, all sites are scraped sequentially.",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "listing"],
        default="full",
        help=(
            "Scraping mode: 'full' = listing pages + detail pages, "
            "'listing' = listing pages only. (default: full)"
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum number of pages to scrape per category. (default: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and parse but do not write to the database.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write parsed results to a JSON file (useful with --dry-run).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


async def _run_dry(site_name: str, config: dict) -> list[dict]:
    """Run a scraper in dry-run mode: scrape + parse, no DB writes."""
    scraper_cls = SCRAPERS[site_name]
    scraper = scraper_cls(config=config)
    run_result = await scraper.run(mode=config.get("mode", "full"))
    raw_items = run_result.get("data", [])

    parser = VehicleParser()
    parsed = parser.parse_batch(raw_items, source_site=site_name)
    return parsed


async def _run_with_db(site_name: str, config: dict) -> dict:
    """Run a scraper with full DB upsert via ScraperScheduler."""
    from app.db.supabase_client import get_supabase_client
    from scraper.scheduler import ScraperScheduler

    client = get_supabase_client(service_role=True)
    scheduler = ScraperScheduler(supabase_client=client, config=config)

    if site_name:
        return await scheduler.run_site(site_name, mode=config.get("mode", "full"))
    else:
        return await scheduler.run_all(mode=config.get("mode", "full"))


async def main() -> None:
    args = _build_parser().parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("run_scraper")

    config = {
        "max_pages": args.max_pages,
        "mode": args.mode,
        "triggered_by": "manual_cli",
    }

    sites = [args.site] if args.site else list(SCRAPERS.keys())

    if args.dry_run:
        logger.info("DRY RUN mode -- no database writes will be made.")
        all_results: dict[str, list[dict]] = {}
        for site in sites:
            logger.info("Running scraper: %s (mode=%s)", site, args.mode)
            try:
                parsed = await _run_dry(site, config)
                all_results[site] = parsed
                logger.info(
                    "Site %s: scraped and parsed %d records.", site, len(parsed)
                )
            except Exception as exc:
                logger.error("Site %s failed: %s", site, exc, exc_info=True)
                all_results[site] = []

        # Output results
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(
                json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Results written to %s", output_path)
        else:
            # Print summary to stdout
            for site, records in all_results.items():
                print(f"\n{'=' * 60}")
                print(f"Site: {site}  |  Records: {len(records)}")
                print(f"{'=' * 60}")
                for r in records[:5]:
                    print(
                        f"  {r.get('maker', '?')} {r.get('model_name', '?')} "
                        f"| {r.get('model_year', '?')}年 "
                        f"| {r.get('mileage_km', '?')}km "
                        f"| {r.get('price_yen', '?')}円"
                    )
                if len(records) > 5:
                    print(f"  ... and {len(records) - 5} more records")
    else:
        logger.info("LIVE mode -- records will be upserted to the database.")
        for site in sites:
            logger.info("Running scraper: %s (mode=%s)", site, args.mode)
            try:
                stats = await _run_with_db(site, config)
                logger.info("Site %s complete: %s", site, stats)
            except Exception as exc:
                logger.error("Site %s failed: %s", site, exc, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
