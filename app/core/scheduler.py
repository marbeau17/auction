"""Background scheduler for recurring business tasks.

This module wires up an :class:`~apscheduler.schedulers.asyncio.AsyncIOScheduler`
that runs inside the FastAPI process.  The scheduler is started from the
application's ``lifespan`` context (see :mod:`app.main`) and currently owns:

* **Monthly invoice generation** — fires at 03:00 on the first day of every
  month and delegates to :meth:`InvoiceRepository.generate_monthly_invoices`
  for each fund.  Uses the current calendar month as the billing month.
* **Monthly Yayoi sync** — fires at 02:00 on day 5 of every month (after
  invoices are finalized, before investor reports) for every user who has
  opted in via ``user_integration_settings.yayoi_auto_sync_monthly``.
* **Monthly investor reports** — fires at 04:00 on day 3 of every month
  (after invoice month-close) and generates a per-fund PDF statement via
  :class:`app.core.investor_report_generator.InvestorReportGenerator`.

If APScheduler is not installed (optional dependency), :func:`start_scheduler`
logs a warning and returns ``None`` so the application can still boot.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import structlog

from app.config import get_settings

logger = structlog.get_logger()

# APScheduler is an optional runtime dependency.  Import lazily / defensively
# so a missing wheel doesn't break app startup.
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    _APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover - only hit when the dep is absent
    AsyncIOScheduler = None  # type: ignore[assignment,misc]
    CronTrigger = None  # type: ignore[assignment,misc]
    _APSCHEDULER_AVAILABLE = False


def _build_supabase_client():
    """Create a service-role Supabase client for background jobs."""
    from supabase import create_client

    settings = get_settings()
    return create_client(
        settings.supabase_url, settings.supabase_service_role_key
    )


async def run_monthly_invoice_generation() -> None:
    """Generate monthly invoices for every fund for the current month.

    Intended to be invoked by APScheduler on the 1st of each month.  Can
    also be called manually for ad-hoc backfills / smoke tests.
    """
    from app.db.repositories.invoice_repo import InvoiceRepository

    try:
        client = _build_supabase_client()
    except Exception:
        logger.exception("scheduler_supabase_client_failed")
        return

    billing_month = date.today().replace(day=1)

    try:
        funds_resp = client.table("funds").select("id").execute()
    except Exception:
        logger.exception("scheduler_funds_query_failed")
        return

    funds = funds_resp.data or []
    if not funds:
        logger.info("scheduler_monthly_invoice_no_funds")
        return

    repo = InvoiceRepository(client=client)
    total_created = 0
    failed_funds: list[str] = []

    for fund in funds:
        fund_id = fund.get("id")
        if not fund_id:
            continue
        try:
            invoices = await repo.generate_monthly_invoices(
                fund_id=fund_id,
                billing_month=billing_month,
            )
            total_created += len(invoices)
            logger.info(
                "scheduler_monthly_invoice_fund_ok",
                fund_id=str(fund_id),
                created=len(invoices),
            )
        except Exception:
            failed_funds.append(str(fund_id))
            logger.exception(
                "scheduler_monthly_invoice_fund_failed",
                fund_id=str(fund_id),
            )

    logger.info(
        "scheduler_monthly_invoice_done",
        billing_month=billing_month.isoformat(),
        funds_processed=len(funds),
        invoices_created=total_created,
        failed_funds=failed_funds,
    )


async def run_monthly_yayoi_sync() -> None:
    """Run last month's Yayoi batch sync for every opted-in user.

    Iterates ``user_integration_settings`` rows where
    ``yayoi_auto_sync_monthly = true`` and, for each distinct fund that the
    user can see, invokes :meth:`YayoiService.batch_sync_invoices` for the
    previous calendar month.  Failures are logged but do not abort the
    remaining users / funds.
    """
    from app.services.yayoi_service import YayoiService

    try:
        client = _build_supabase_client()
    except Exception:
        logger.exception("scheduler_yayoi_supabase_client_failed")
        return

    try:
        settings_resp = (
            client.table("user_integration_settings")
            .select("user_id, yayoi_auto_sync_monthly")
            .eq("yayoi_auto_sync_monthly", True)
            .execute()
        )
        opted_in = settings_resp.data or []
    except Exception:
        logger.exception("scheduler_yayoi_settings_query_failed")
        return

    if not opted_in:
        logger.info("scheduler_yayoi_monthly_no_users")
        return

    # Previous calendar month, anchored to day 1.
    today = date.today()
    if today.month == 1:
        last_month = today.replace(year=today.year - 1, month=12, day=1)
    else:
        last_month = today.replace(month=today.month - 1, day=1)

    # Collect distinct fund IDs. Auto-sync is tenant-wide: we process every
    # fund once regardless of how many users opted in so we don't double-post
    # the same invoices.
    try:
        fund_resp = client.table("funds").select("id").execute()
        fund_ids = [f.get("id") for f in (fund_resp.data or []) if f.get("id")]
    except Exception:
        logger.exception("scheduler_yayoi_funds_query_failed")
        return

    if not fund_ids:
        logger.info("scheduler_yayoi_monthly_no_funds")
        return

    service = YayoiService(supabase_client=client)
    total = {"synced": 0, "skipped": 0, "failed": 0}

    for fund_id in fund_ids:
        try:
            result = await service.batch_sync_invoices(fund_id, last_month)
            for k in total:
                total[k] += int(result.get(k, 0) or 0)
            logger.info(
                "scheduler_yayoi_monthly_fund_ok",
                fund_id=str(fund_id),
                **{k: v for k, v in result.items() if k != "errors"},
            )
        except Exception:
            logger.exception(
                "scheduler_yayoi_monthly_fund_failed",
                fund_id=str(fund_id),
            )

    logger.info(
        "scheduler_yayoi_monthly_done",
        billing_month=last_month.isoformat(),
        funds_processed=len(fund_ids),
        users_opted_in=len(opted_in),
        **total,
    )


async def run_monthly_investor_reports() -> None:
    """Generate the monthly investor PDF for every active fund.

    Intended to fire on the 3rd of each month (after invoice month-close).
    Uses the *current* calendar month as the reporting month since invoices
    for that month have just been finalized on day 1.
    """
    from datetime import datetime, timezone

    from app.core.investor_report_generator import InvestorReportGenerator
    from app.db.repositories.investor_report_repo import InvestorReportRepository

    try:
        client = _build_supabase_client()
    except Exception:
        logger.exception("scheduler_investor_reports_supabase_client_failed")
        return

    report_month = date.today().replace(day=1)

    try:
        funds_resp = (
            client.table("funds")
            .select("id, fund_name")
            .eq("status", "active")
            .execute()
        )
    except Exception:
        logger.exception("scheduler_investor_reports_funds_query_failed")
        return

    funds = funds_resp.data or []
    if not funds:
        logger.info("scheduler_investor_reports_no_active_funds")
        return

    repo = InvestorReportRepository(client=client)
    generator = InvestorReportGenerator(client=client)

    generated = 0
    failed: list[str] = []

    for fund in funds:
        fund_id = fund.get("id")
        if not fund_id:
            continue
        try:
            pdf_bytes, metrics = generator.generate(fund_id, report_month)

            # Best-effort upload to Supabase Storage.
            storage_path = f"{fund_id}/{report_month.strftime('%Y-%m')}.pdf"
            try:
                bucket = client.storage.from_("investor-reports")
                bucket.upload(
                    storage_path,
                    pdf_bytes,
                    file_options={
                        "content-type": "application/pdf",
                        "upsert": "true",
                    },
                )
            except Exception:
                logger.warning(
                    "scheduler_investor_report_storage_upload_skipped",
                    storage_path=storage_path,
                    exc_info=True,
                )

            payload = {
                "fund_id": str(fund_id),
                "report_month": report_month.isoformat(),
                "storage_path": storage_path,
                "nav_total": int(metrics["nav_total"]),
                "dividend_paid": int(metrics["dividend_paid"]),
                "dividend_scheduled": int(metrics["dividend_scheduled"]),
                "risk_flags": metrics["risk_flags"],
                "generated_by": None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            await repo.upsert_for_month(fund_id, report_month, payload)
            generated += 1
            logger.info(
                "scheduler_investor_report_fund_ok",
                fund_id=str(fund_id),
                nav_total=metrics["nav_total"],
                risk_flag_count=len(metrics["risk_flags"]),
            )
        except Exception:
            failed.append(str(fund_id))
            logger.exception(
                "scheduler_investor_report_fund_failed", fund_id=str(fund_id)
            )

    logger.info(
        "scheduler_investor_reports_done",
        report_month=report_month.isoformat(),
        funds_processed=len(funds),
        generated=generated,
        failed_funds=failed,
    )


def start_scheduler() -> Optional["AsyncIOScheduler"]:
    """Construct, configure, and start the AsyncIOScheduler.

    Returns the running scheduler instance, or ``None`` when APScheduler is
    unavailable.  The caller is responsible for shutting it down on app
    termination.
    """
    if not _APSCHEDULER_AVAILABLE:
        logger.warning(
            "scheduler_disabled_apscheduler_missing",
            hint="pip install 'apscheduler>=3.10' to enable cron jobs",
        )
        return None

    scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")

    # Monthly invoice generation — 03:00 on day 1 of every month.
    scheduler.add_job(
        run_monthly_invoice_generation,
        trigger=CronTrigger(day=1, hour=3, minute=0),
        id="monthly_invoice_generation",
        name="Generate monthly invoices for all funds",
        replace_existing=True,
        misfire_grace_time=3600,  # tolerate up to 1 hour of lag
        coalesce=True,
        max_instances=1,
    )

    # Monthly Yayoi sync — 02:00 on day 5, after invoices are finalized and
    # before investor reports go out.
    scheduler.add_job(
        run_monthly_yayoi_sync,
        trigger=CronTrigger(day=5, hour=2, minute=0),
        id="monthly_yayoi_sync",
        name="Sync previous month's invoices to Yayoi (opted-in users)",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

    # Monthly investor reports — 04:00 on day 3 of every month (after the
    # invoice cron on day 1 has completed).
    scheduler.add_job(
        run_monthly_investor_reports,
        trigger=CronTrigger(day=3, hour=4, minute=0),
        id="monthly_investor_reports",
        name="Generate monthly investor PDF for every active fund",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        jobs=[job.id for job in scheduler.get_jobs()],
    )
    return scheduler


def shutdown_scheduler(scheduler: Optional["AsyncIOScheduler"]) -> None:
    """Gracefully stop the scheduler if one was started."""
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
    except Exception:
        logger.exception("scheduler_shutdown_failed")
