"""Background scheduler for recurring business tasks.

This module is designed to be **import-safe in serverless environments**
(Vercel, AWS Lambda, etc.) where APScheduler cannot run because there is no
persistent event loop.  To guarantee that, **nothing heavy is imported at
module top level**:

* ``apscheduler`` is imported lazily inside :func:`start_scheduler` and
  guarded with ``try/except ImportError``.
* Repository / service / Supabase / PDF stacks are imported lazily inside
  each job function body.

The scheduler is started from the application's ``lifespan`` context (see
:mod:`app.main`) on long-running hosts and currently owns:

* **Monthly invoice generation** (03:00 on day 1)
* **Monthly Yayoi sync** (02:00 on day 5)
* **Monthly investor reports** (04:00 on day 3)

If ``VERCEL=1`` or ``SKIP_SCHEDULER=1`` is set, :func:`start_scheduler`
returns early and logs ``scheduler_skipped_serverless`` /
``scheduler_skipped_env``.  If APScheduler is not installed at all,
:func:`start_scheduler` logs ``apscheduler_not_installed`` and returns
``None`` — never raises.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Optional

import structlog

from app.config import get_settings

logger = structlog.get_logger()


def _build_supabase_client():
    """Create a service-role Supabase client for background jobs.

    Imported lazily so module import never pulls the supabase stack.
    """
    from supabase import create_client  # local import

    settings = get_settings()
    return create_client(
        settings.supabase_url, settings.supabase_service_role_key
    )


async def run_monthly_invoice_generation() -> None:
    """Generate monthly invoices for every fund for the current month.

    Intended to be invoked by APScheduler on the 1st of each month.  Can
    also be called manually for ad-hoc backfills / smoke tests.
    """
    # Lazy imports: keep module import side-effect free.
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
    # Lazy imports: keep module import side-effect free.
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
    # Lazy imports: keep module import side-effect free (PDF stack is heavy).
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


def start_scheduler() -> Optional[Any]:
    """Construct, configure, and start the AsyncIOScheduler.

    Returns the running scheduler instance, or ``None`` when the scheduler
    is skipped (serverless / env-disabled) or APScheduler is unavailable.
    The caller is responsible for shutting it down on app termination.

    Safe to call in any environment: never raises.
    """
    # Serverless / explicit opt-out: return early before importing anything.
    if os.getenv("VERCEL") == "1":
        logger.info("scheduler_skipped_serverless")
        return None
    if os.getenv("SKIP_SCHEDULER") == "1":
        logger.info("scheduler_skipped_env")
        return None

    # APScheduler is an optional runtime dependency.  Import it here (not at
    # module top level) so this module stays importable on Vercel / any host
    # that doesn't ship the wheel.
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "apscheduler_not_installed",
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

    try:
        scheduler.start()
    except Exception:
        logger.exception("scheduler_start_failed")
        return None

    logger.info(
        "scheduler_started",
        jobs=[job.id for job in scheduler.get_jobs()],
    )
    return scheduler


def shutdown_scheduler(scheduler: Optional[Any]) -> None:
    """Gracefully stop the scheduler if one was started.

    Safe to call with ``None`` (the common serverless case).
    """
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
    except Exception:
        logger.exception("scheduler_shutdown_failed")
