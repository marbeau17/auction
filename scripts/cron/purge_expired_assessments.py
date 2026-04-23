"""Purge ``finance_assessments`` rows past their 7-year retention window.

Run nightly via Render cron (or any external scheduler).

Usage::

    python -m scripts.cron.purge_expired_assessments

Exit status is the number of rows purged (0 when nothing aged out). A
non-zero exit code does NOT mean failure here — it's a deliberate count
so the scheduler log records how much aged out on each run.

Retention window: 7 years, per 法人税法 施行規則 第59条.
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from supabase import create_client

from app.config import get_settings
from app.db.repositories.finance_assessment_repo import (
    FinanceAssessmentRepository,
)

logger = structlog.get_logger()


async def main() -> int:
    """Instantiate a service-role client and run the purge."""
    settings = get_settings()
    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    repo = FinanceAssessmentRepository(client=client)
    deleted = await repo.purge_expired()
    logger.info("finance_assessments_purge_completed", count=deleted)
    return int(deleted)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
