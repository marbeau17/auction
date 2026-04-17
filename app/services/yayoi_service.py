"""Yayoi Accounting Online API integration service.

Provides:
- OAuth2 token management
- Journal entry creation from CVLPOS invoices
- Financial statement retrieval
- Monthly batch sync
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()

YAYOI_API_BASE = "https://api.yayoi-kk.co.jp"
YAYOI_AUTH_URL = "https://auth.yayoi-kk.co.jp/oauth2/token"
YAYOI_AUTHORIZE_URL = "https://auth.yayoi-kk.co.jp/oauth2/authorize"

# Yayoi account codes (勘定科目コード)
ACCOUNT_URIKAKEKIN = "1150"  # 売掛金 Accounts Receivable
ACCOUNT_URIAGE = "4100"  # 売上高 Revenue
ACCOUNT_FUTSU_YOKIN = "1120"  # 普通預金 Ordinary Deposit
TAX_CATEGORY_TAXABLE_10 = "課税売上10%"
TAX_CATEGORY_EXEMPT = "非課税"


class YayoiService:
    """Client for Yayoi Accounting Online API."""

    def __init__(self, supabase_client=None):
        self.supabase = supabase_client
        settings = get_settings()
        self.client_id = getattr(settings, "yayoi_client_id", "")
        self.client_secret = getattr(settings, "yayoi_client_secret", "")
        self.redirect_uri = getattr(settings, "yayoi_redirect_uri", "")
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self.enabled = bool(self.client_id and self.client_secret)

        if not self.enabled:
            logger.warning(
                "yayoi_service_disabled",
                reason="yayoi_client_id or yayoi_client_secret not configured",
            )

    # ------------------------------------------------------------------
    # OAuth2
    # ------------------------------------------------------------------

    def get_authorize_url(self, state: str) -> str:
        """Build the OAuth2 authorization URL for user redirect."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "openid profile",
            "state": state,
        }
        qs = "&".join(f"{k}={httpx.QueryParams({k: v})}" for k, v in params.items())
        # Use httpx for proper encoding
        return str(httpx.URL(YAYOI_AUTHORIZE_URL).copy_merge_params(params))

    async def authenticate(self, auth_code: str) -> dict:
        """Exchange authorization code for access token.

        Args:
            auth_code: The authorization code from the OAuth2 callback.

        Returns:
            Token response dict with access_token, refresh_token, expires_in.
        """
        if not self.enabled:
            logger.info("yayoi_auth_dry_run", code=auth_code[:8] + "...")
            self._access_token = "dry_run_token"
            self._token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
            return {
                "access_token": self._access_token,
                "token_type": "bearer",
                "expires_in": 3600,
                "dry_run": True,
            }

        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(YAYOI_AUTH_URL, data=payload)
                resp.raise_for_status()
                data = resp.json()

                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token")
                expires_in = data.get("expires_in", 3600)
                self._token_expires = datetime.now(timezone.utc) + timedelta(
                    seconds=expires_in
                )

                # Persist tokens to Supabase if available
                await self._store_tokens()

                logger.info("yayoi_auth_success", expires_in=expires_in)
                return data

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "yayoi_auth_failed",
                    status=exc.response.status_code,
                    body=exc.response.text,
                )
                raise
            except httpx.RequestError as exc:
                logger.error("yayoi_auth_request_error", error=str(exc))
                raise

    async def refresh_access_token(self) -> dict:
        """Refresh the access token using the stored refresh token.

        Returns:
            Updated token response dict.
        """
        if not self.enabled:
            logger.info("yayoi_refresh_dry_run")
            self._access_token = "dry_run_token_refreshed"
            self._token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
            return {
                "access_token": self._access_token,
                "token_type": "bearer",
                "expires_in": 3600,
                "dry_run": True,
            }

        if not self._refresh_token:
            # Try loading from Supabase
            await self._load_tokens()

        if not self._refresh_token:
            raise RuntimeError("No refresh token available. Re-authenticate required.")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(YAYOI_AUTH_URL, data=payload)
                resp.raise_for_status()
                data = resp.json()

                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                expires_in = data.get("expires_in", 3600)
                self._token_expires = datetime.now(timezone.utc) + timedelta(
                    seconds=expires_in
                )

                await self._store_tokens()

                logger.info("yayoi_token_refreshed", expires_in=expires_in)
                return data

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "yayoi_refresh_failed",
                    status=exc.response.status_code,
                    body=exc.response.text,
                )
                raise

    async def _ensure_token(self):
        """Ensure a valid access token is available, refreshing if needed."""
        if not self.enabled:
            return

        # Try loading from DB if not in memory
        if not self._access_token:
            await self._load_tokens()

        # Refresh if expired or about to expire (60s buffer)
        if self._token_expires and datetime.now(
            timezone.utc
        ) >= self._token_expires - timedelta(seconds=60):
            await self.refresh_access_token()

        if not self._access_token:
            raise RuntimeError(
                "Yayoi access token not available. OAuth2 authentication required."
            )

    async def _store_tokens(self):
        """Persist OAuth tokens to Supabase."""
        if not self.supabase:
            return
        try:
            data = {
                "provider": "yayoi",
                "access_token": self._access_token,
                "refresh_token": self._refresh_token or "",
                "expires_at": self._token_expires.isoformat() if self._token_expires else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.supabase.table("oauth_tokens").upsert(
                data, on_conflict="provider"
            ).execute()
        except Exception as exc:
            logger.error("yayoi_store_tokens_failed", error=str(exc))

    async def _load_tokens(self):
        """Load OAuth tokens from Supabase."""
        if not self.supabase:
            return
        try:
            result = (
                self.supabase.table("oauth_tokens")
                .select("*")
                .eq("provider", "yayoi")
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                self._access_token = row.get("access_token")
                self._refresh_token = row.get("refresh_token")
                expires_at = row.get("expires_at")
                if expires_at:
                    self._token_expires = datetime.fromisoformat(expires_at)
        except Exception as exc:
            logger.error("yayoi_load_tokens_failed", error=str(exc))

    def _auth_headers(self) -> dict:
        """Return authorization headers for API calls."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Journal Entries (仕訳)
    # ------------------------------------------------------------------

    async def create_journal_entry(self, invoice_data: dict) -> dict:
        """Create a journal entry from a CVLPOS invoice.

        Maps invoice to Yayoi journal format:
        - 借方 (debit):  売掛金 (Accounts Receivable)
        - 貸方 (credit): 売上高 (Revenue)
        - Tax handling:  消費税区分

        Args:
            invoice_data: Dict with invoice_number, total_amount, tax_amount,
                          subtotal, billing_period_start, due_date, etc.

        Returns:
            Created journal entry dict or dry-run confirmation.
        """
        invoice_number = invoice_data.get("invoice_number", "N/A")
        total_amount = invoice_data.get("total_amount", 0)
        tax_amount = invoice_data.get("tax_amount", 0)
        subtotal = invoice_data.get("subtotal", total_amount - tax_amount)
        txn_date = invoice_data.get(
            "billing_period_start", date.today().isoformat()
        )
        description = f"売上計上 請求書 {invoice_number}"

        journal_payload = {
            "Date": txn_date,
            "Number": invoice_number,
            "Memo": description,
            "Lines": [
                {
                    "DebitAccountCode": ACCOUNT_URIKAKEKIN,
                    "DebitAmount": total_amount,
                    "DebitTaxCategory": TAX_CATEGORY_TAXABLE_10,
                    "CreditAccountCode": ACCOUNT_URIAGE,
                    "CreditAmount": subtotal,
                    "CreditTaxCategory": TAX_CATEGORY_TAXABLE_10,
                    "Description": description,
                },
            ],
        }

        # Add tax line if applicable
        if tax_amount > 0:
            journal_payload["Lines"].append(
                {
                    "DebitAccountCode": "",
                    "DebitAmount": 0,
                    "CreditAccountCode": "2180",  # 仮受消費税
                    "CreditAmount": tax_amount,
                    "CreditTaxCategory": TAX_CATEGORY_TAXABLE_10,
                    "Description": f"消費税 {invoice_number}",
                }
            )

        if not self.enabled:
            logger.info(
                "yayoi_journal_dry_run",
                invoice=invoice_number,
                amount=total_amount,
            )
            return {
                "status": "dry_run",
                "journal": journal_payload,
                "message": "Yayoi credentials not configured; journal not posted.",
            }

        await self._ensure_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    f"{YAYOI_API_BASE}/v1/journals",
                    json=journal_payload,
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                result = resp.json()
                logger.info(
                    "yayoi_journal_created",
                    invoice=invoice_number,
                    journal_id=result.get("Id"),
                )

                # Log sync to Supabase
                await self._log_sync(
                    "journal_entry",
                    invoice_number,
                    "success",
                    result.get("Id"),
                )

                return result

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "yayoi_journal_failed",
                    invoice=invoice_number,
                    status=exc.response.status_code,
                    body=exc.response.text,
                )
                await self._log_sync(
                    "journal_entry",
                    invoice_number,
                    "failed",
                    error=exc.response.text,
                )
                raise
            except httpx.RequestError as exc:
                logger.error("yayoi_journal_request_error", error=str(exc))
                await self._log_sync(
                    "journal_entry", invoice_number, "failed", error=str(exc)
                )
                raise

    async def create_payment_entry(self, payment_data: dict) -> dict:
        """Create payment receipt journal entry.

        Maps:
        - 借方 (debit):  普通預金 (Bank deposit)
        - 貸方 (credit): 売掛金 (Accounts Receivable)

        Args:
            payment_data: Dict with invoice_number, amount, payment_date,
                          payment_method, etc.

        Returns:
            Created journal entry dict or dry-run confirmation.
        """
        invoice_number = payment_data.get("invoice_number", "N/A")
        amount = payment_data.get("amount", 0)
        payment_date = payment_data.get(
            "payment_date", date.today().isoformat()
        )
        description = f"入金 請求書 {invoice_number}"

        journal_payload = {
            "Date": payment_date,
            "Number": f"PMT-{invoice_number}",
            "Memo": description,
            "Lines": [
                {
                    "DebitAccountCode": ACCOUNT_FUTSU_YOKIN,
                    "DebitAmount": amount,
                    "DebitTaxCategory": TAX_CATEGORY_EXEMPT,
                    "CreditAccountCode": ACCOUNT_URIKAKEKIN,
                    "CreditAmount": amount,
                    "CreditTaxCategory": TAX_CATEGORY_EXEMPT,
                    "Description": description,
                },
            ],
        }

        if not self.enabled:
            logger.info(
                "yayoi_payment_dry_run",
                invoice=invoice_number,
                amount=amount,
            )
            return {
                "status": "dry_run",
                "journal": journal_payload,
                "message": "Yayoi credentials not configured; payment entry not posted.",
            }

        await self._ensure_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    f"{YAYOI_API_BASE}/v1/journals",
                    json=journal_payload,
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                result = resp.json()
                logger.info(
                    "yayoi_payment_created",
                    invoice=invoice_number,
                    journal_id=result.get("Id"),
                )
                await self._log_sync(
                    "payment_entry",
                    invoice_number,
                    "success",
                    result.get("Id"),
                )
                return result

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "yayoi_payment_failed",
                    invoice=invoice_number,
                    status=exc.response.status_code,
                    body=exc.response.text,
                )
                await self._log_sync(
                    "payment_entry",
                    invoice_number,
                    "failed",
                    error=exc.response.text,
                )
                raise

    async def batch_sync_invoices(self, fund_id: str, month: date) -> dict:
        """Sync all invoices for a fund/month to Yayoi.

        Queries Supabase for invoices matching the fund and month, then
        creates journal entries for each one that has not yet been synced.

        Args:
            fund_id: Fund UUID.
            month: Target month (first day).

        Returns:
            Summary dict with synced/skipped/failed counts.
        """
        month_start = month.replace(day=1)
        if month.month == 12:
            month_end = month.replace(year=month.year + 1, month=1, day=1)
        else:
            month_end = month.replace(month=month.month + 1, day=1)

        results = {"synced": 0, "skipped": 0, "failed": 0, "errors": []}

        if not self.supabase:
            logger.warning("yayoi_batch_sync_no_supabase")
            return {**results, "message": "Supabase client not available."}

        # Fetch invoices for the period
        try:
            query = (
                self.supabase.table("invoices")
                .select("*")
                .eq("fund_id", fund_id)
                .gte("billing_period_start", month_start.isoformat())
                .lt("billing_period_start", month_end.isoformat())
                .eq("status", "approved")
                .execute()
            )
            invoices = query.data or []
        except Exception as exc:
            logger.error("yayoi_batch_fetch_failed", error=str(exc))
            return {**results, "message": f"Failed to fetch invoices: {exc}"}

        logger.info(
            "yayoi_batch_sync_start",
            fund_id=fund_id,
            month=month_start.isoformat(),
            invoice_count=len(invoices),
        )

        # Check which invoices are already synced
        synced_numbers = set()
        try:
            sync_result = (
                self.supabase.table("yayoi_sync_log")
                .select("reference")
                .eq("status", "success")
                .eq("sync_type", "journal_entry")
                .execute()
            )
            synced_numbers = {r["reference"] for r in (sync_result.data or [])}
        except Exception:
            pass  # Table might not exist yet

        for inv in invoices:
            inv_number = inv.get("invoice_number", "")
            if inv_number in synced_numbers:
                results["skipped"] += 1
                continue

            try:
                await self.create_journal_entry(inv)
                results["synced"] += 1
            except Exception as exc:
                results["failed"] += 1
                results["errors"].append(
                    {"invoice_number": inv_number, "error": str(exc)}
                )

        logger.info("yayoi_batch_sync_complete", **results)
        return results

    # ------------------------------------------------------------------
    # Financial Data Retrieval
    # ------------------------------------------------------------------

    async def get_company_financials(self, company_code: str) -> dict:
        """Retrieve financial statements from Yayoi for a company.

        Returns P&L and balance sheet data for financial AI diagnosis
        of transport companies.

        Args:
            company_code: Internal company identifier.

        Returns:
            Dict with profit_loss and balance_sheet keys.
        """
        if not self.enabled:
            logger.info("yayoi_financials_dry_run", company=company_code)
            return {
                "status": "dry_run",
                "company_code": company_code,
                "profit_loss": {},
                "balance_sheet": {},
                "message": "Yayoi credentials not configured; returning empty data.",
            }

        await self._ensure_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Fetch P&L
                pl_resp = await client.get(
                    f"{YAYOI_API_BASE}/v1/reports/profit-loss",
                    params={"companyCode": company_code},
                    headers=self._auth_headers(),
                )
                pl_resp.raise_for_status()
                profit_loss = pl_resp.json()

                # Fetch Balance Sheet
                bs_resp = await client.get(
                    f"{YAYOI_API_BASE}/v1/reports/balance-sheet",
                    params={"companyCode": company_code},
                    headers=self._auth_headers(),
                )
                bs_resp.raise_for_status()
                balance_sheet = bs_resp.json()

                logger.info("yayoi_financials_retrieved", company=company_code)
                return {
                    "status": "ok",
                    "company_code": company_code,
                    "profit_loss": profit_loss,
                    "balance_sheet": balance_sheet,
                }

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "yayoi_financials_failed",
                    company=company_code,
                    status=exc.response.status_code,
                    body=exc.response.text,
                )
                raise
            except httpx.RequestError as exc:
                logger.error(
                    "yayoi_financials_request_error",
                    company=company_code,
                    error=str(exc),
                )
                raise

    async def get_trial_balance(self, fiscal_year: int, month: int) -> dict:
        """Get trial balance (残高試算表) for a period.

        Args:
            fiscal_year: Fiscal year (e.g. 2026).
            month: Month number (1-12).

        Returns:
            Trial balance data dict.
        """
        if not self.enabled:
            logger.info(
                "yayoi_trial_balance_dry_run",
                year=fiscal_year,
                month=month,
            )
            return {
                "status": "dry_run",
                "fiscal_year": fiscal_year,
                "month": month,
                "accounts": [],
                "message": "Yayoi credentials not configured; returning empty data.",
            }

        await self._ensure_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(
                    f"{YAYOI_API_BASE}/v1/reports/trial-balance",
                    params={
                        "fiscalYear": fiscal_year,
                        "month": month,
                    },
                    headers=self._auth_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info(
                    "yayoi_trial_balance_retrieved",
                    year=fiscal_year,
                    month=month,
                )
                return {
                    "status": "ok",
                    "fiscal_year": fiscal_year,
                    "month": month,
                    "accounts": data.get("Accounts", []),
                    "totals": data.get("Totals", {}),
                }

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "yayoi_trial_balance_failed",
                    year=fiscal_year,
                    month=month,
                    status=exc.response.status_code,
                    body=exc.response.text,
                )
                raise
            except httpx.RequestError as exc:
                logger.error(
                    "yayoi_trial_balance_request_error",
                    error=str(exc),
                )
                raise

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _log_sync(
        self,
        sync_type: str,
        reference: str,
        status: str,
        external_id: Optional[str] = None,
        error: Optional[str] = None,
    ):
        """Log a sync event to Supabase."""
        if not self.supabase:
            return
        try:
            self.supabase.table("yayoi_sync_log").insert(
                {
                    "sync_type": sync_type,
                    "reference": reference,
                    "status": status,
                    "external_id": external_id or "",
                    "error_message": error or "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ).execute()
        except Exception as exc:
            logger.error("yayoi_sync_log_failed", error=str(exc))

    def get_connection_status(self) -> dict:
        """Return current connection status."""
        return {
            "enabled": self.enabled,
            "authenticated": self._access_token is not None,
            "token_expires": (
                self._token_expires.isoformat() if self._token_expires else None
            ),
        }
