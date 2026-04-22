"""Repository for invoice management."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from supabase import Client

logger = structlog.get_logger()

TABLE = "invoices"
LINE_ITEMS_TABLE = "invoice_line_items"
APPROVALS_TABLE = "invoice_approvals"
EMAIL_LOGS_TABLE = "email_logs"


class InvoiceRepository:
    """CRUD operations for invoice-related tables."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    async def list_invoices(
        self,
        fund_id: Optional[UUID] = None,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        allowed_fund_ids: Optional[list[str]] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List invoices with optional filters.

        ``allowed_fund_ids`` restricts results to the given fund IDs (used by
        non-admin callers for tenant scoping). ``None`` means unrestricted,
        an empty list means the caller may not see any invoices.

        Returns:
            A tuple of (list of invoice dicts, total count).
        """
        try:
            if allowed_fund_ids is not None and len(allowed_fund_ids) == 0:
                return [], 0

            query = (
                self._client.table(TABLE)
                .select("*", count="exact")
            )

            if fund_id:
                query = query.eq("fund_id", str(fund_id))
            if status:
                query = query.eq("status", status)
            if allowed_fund_ids is not None:
                query = query.in_("fund_id", allowed_fund_ids)

            offset = (page - 1) * per_page
            query = query.order("created_at", desc=True).range(
                offset, offset + per_page - 1
            )

            response = query.execute()

            data: list[dict[str, Any]] = response.data or []
            total_count: int = response.count or 0

            return data, total_count

        except Exception:
            logger.exception(
                "invoice_list_failed",
                fund_id=str(fund_id) if fund_id else None,
                status=status,
            )
            raise

    async def get_invoice(
        self, invoice_id: UUID
    ) -> dict[str, Any] | None:
        """Get invoice with line items.

        Returns:
            Invoice dict with embedded line_items list, or None if not found.
        """
        try:
            response = (
                self._client.table(TABLE)
                .select("*")
                .eq("id", str(invoice_id))
                .maybe_single()
                .execute()
            )

            if not response.data:
                return None

            line_items_response = (
                self._client.table(LINE_ITEMS_TABLE)
                .select("*")
                .eq("invoice_id", str(invoice_id))
                .order("display_order")
                .execute()
            )

            result = response.data
            result["line_items"] = line_items_response.data or []
            return result

        except Exception:
            logger.exception(
                "invoice_get_failed", invoice_id=str(invoice_id)
            )
            raise

    async def create_invoice(
        self,
        invoice_data: dict[str, Any],
        line_items: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Create invoice with line items.

        Returns:
            The created invoice with line items.
        """
        try:
            response = (
                self._client.table(TABLE)
                .insert(invoice_data)
                .execute()
            )

            data = response.data
            if not data or len(data) == 0:
                raise RuntimeError("Invoice insert returned no data")

            invoice = data[0]

            if line_items:
                for i, item in enumerate(line_items):
                    item["invoice_id"] = invoice["id"]
                    item["display_order"] = i

                self._client.table(LINE_ITEMS_TABLE).insert(
                    line_items
                ).execute()

            return await self.get_invoice(UUID(invoice["id"]))

        except Exception:
            logger.exception("invoice_create_failed")
            raise

    async def update_invoice_status(
        self, invoice_id: UUID, status: str
    ) -> dict[str, Any]:
        """Update invoice status.

        Returns:
            The updated invoice record.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            update_data: dict[str, Any] = {
                "status": status,
                "updated_at": now,
            }

            if status == "sent":
                update_data["sent_at"] = now
            elif status == "paid":
                update_data["paid_at"] = now

            response = (
                self._client.table(TABLE)
                .update(update_data)
                .eq("id", str(invoice_id))
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                return data[0]

            raise RuntimeError(
                f"Invoice {invoice_id} not found for status update"
            )

        except Exception:
            logger.exception(
                "invoice_update_status_failed",
                invoice_id=str(invoice_id),
                status=status,
            )
            raise

    async def generate_invoice_number(
        self, fund_id: UUID, billing_date: date
    ) -> str:
        """Generate unique invoice number: INV-{YYYYMM}-{seq}."""
        try:
            prefix = f"INV-{billing_date.strftime('%Y%m')}"

            existing = (
                self._client.table(TABLE)
                .select("invoice_number")
                .like("invoice_number", f"{prefix}%")
                .execute()
            )

            seq = len(existing.data or []) + 1
            return f"{prefix}-{seq:04d}"

        except Exception:
            logger.exception(
                "invoice_number_generation_failed",
                fund_id=str(fund_id),
            )
            raise

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    async def create_approval(
        self, approval_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Record an approval action.

        Returns:
            The created approval record.
        """
        try:
            response = (
                self._client.table(APPROVALS_TABLE)
                .insert(approval_data)
                .execute()
            )

            data = response.data
            if not data or len(data) == 0:
                raise RuntimeError("Approval insert returned no data")

            # Auto-update invoice status based on action
            action = approval_data["action"]
            invoice_id = approval_data["invoice_id"]

            if action == "approve":
                await self.update_invoice_status(
                    UUID(invoice_id), "approved"
                )
            elif action == "reject":
                await self.update_invoice_status(
                    UUID(invoice_id), "created"
                )

            return data[0]

        except Exception:
            logger.exception("approval_create_failed")
            raise

    async def get_approvals(
        self, invoice_id: UUID
    ) -> list[dict[str, Any]]:
        """Get approval history for an invoice.

        Returns:
            List of approval records, newest first.
        """
        try:
            response = (
                self._client.table(APPROVALS_TABLE)
                .select("*")
                .eq("invoice_id", str(invoice_id))
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "approvals_get_failed",
                invoice_id=str(invoice_id),
            )
            raise

    # ------------------------------------------------------------------
    # Email Logs
    # ------------------------------------------------------------------

    async def create_email_log(
        self, log_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Record an email send attempt.

        Returns:
            The created email log record.
        """
        try:
            response = (
                self._client.table(EMAIL_LOGS_TABLE)
                .insert(log_data)
                .execute()
            )

            data = response.data
            if not data or len(data) == 0:
                raise RuntimeError("Email log insert returned no data")

            return data[0]

        except Exception:
            logger.exception("email_log_create_failed")
            raise

    async def update_email_status(
        self,
        log_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update email send status.

        Returns:
            The updated email log record.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            update_data: dict[str, Any] = {"status": status}

            if status == "sent":
                update_data["sent_at"] = now
            if error_message:
                update_data["error_message"] = error_message

            response = (
                self._client.table(EMAIL_LOGS_TABLE)
                .update(update_data)
                .eq("id", str(log_id))
                .execute()
            )

            data = response.data
            if data and len(data) > 0:
                return data[0]

            raise RuntimeError(
                f"Email log {log_id} not found for status update"
            )

        except Exception:
            logger.exception(
                "email_status_update_failed",
                log_id=str(log_id),
                status=status,
            )
            raise

    async def get_email_logs(
        self, invoice_id: UUID
    ) -> list[dict[str, Any]]:
        """Get email logs for an invoice.

        Returns:
            List of email log records, newest first.
        """
        try:
            response = (
                self._client.table(EMAIL_LOGS_TABLE)
                .select("*")
                .eq("invoice_id", str(invoice_id))
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []

        except Exception:
            logger.exception(
                "email_logs_get_failed",
                invoice_id=str(invoice_id),
            )
            raise

    # ------------------------------------------------------------------
    # Bulk Operations
    # ------------------------------------------------------------------

    async def generate_monthly_invoices(
        self, fund_id: UUID, billing_month: date
    ) -> list[dict[str, Any]]:
        """Generate invoices for all active lease contracts in a fund.

        Queries lease_contracts for the fund and creates an invoice
        for each active contract for the given billing month.

        Returns:
            List of created invoice dicts.
        """
        try:
            contracts_response = (
                self._client.table("lease_contracts")
                .select("*")
                .eq("fund_id", str(fund_id))
                .eq("status", "active")
                .execute()
            )

            invoices: list[dict[str, Any]] = []

            for contract in contracts_response.data or []:
                billing_start = billing_month.replace(day=1)

                if billing_month.month == 12:
                    next_month_first = billing_month.replace(
                        year=billing_month.year + 1, month=1, day=1
                    )
                else:
                    next_month_first = billing_month.replace(
                        month=billing_month.month + 1, day=1
                    )
                billing_end = next_month_first - timedelta(days=1)

                invoice_number = await self.generate_invoice_number(
                    fund_id, billing_month
                )

                subtotal = contract["monthly_lease_amount"]
                tax_rate = float(contract.get("tax_rate", 0.10))
                tax_amount = int(subtotal * tax_rate)
                total = subtotal + tax_amount

                payment_day = contract.get("payment_day", 25)
                due_date = billing_end.replace(
                    day=min(payment_day, 28)
                )

                invoice_data: dict[str, Any] = {
                    "fund_id": str(fund_id),
                    "lease_contract_id": contract["id"],
                    "invoice_number": invoice_number,
                    "billing_period_start": billing_start.isoformat(),
                    "billing_period_end": billing_end.isoformat(),
                    "subtotal": subtotal,
                    "tax_rate": tax_rate,
                    "tax_amount": tax_amount,
                    "total_amount": total,
                    "due_date": due_date.isoformat(),
                    "status": "created",
                }

                line_items: list[dict[str, Any]] = [
                    {
                        "description": (
                            f"サブリース料"
                            f"（{billing_start.strftime('%Y年%m月')}分）"
                        ),
                        "quantity": 1,
                        "unit_price": subtotal,
                        "amount": subtotal,
                    }
                ]

                invoice = await self.create_invoice(
                    invoice_data, line_items
                )
                invoices.append(invoice)

            return invoices

        except Exception:
            logger.exception(
                "monthly_invoice_generation_failed",
                fund_id=str(fund_id),
                billing_month=billing_month.isoformat(),
            )
            raise

    async def get_overdue_invoices(
        self,
        allowed_fund_ids: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Get all overdue invoices (past due date, not paid).

        ``allowed_fund_ids`` restricts the result set to the given fund IDs;
        ``None`` means unrestricted, empty list means the caller may see none.

        Returns:
            List of overdue invoice dicts.
        """
        try:
            if allowed_fund_ids is not None and len(allowed_fund_ids) == 0:
                return []

            today = date.today().isoformat()

            query = (
                self._client.table(TABLE)
                .select("*")
                .lt("due_date", today)
                .not_.in_("status", ["paid", "cancelled"])
            )
            if allowed_fund_ids is not None:
                query = query.in_("fund_id", allowed_fund_ids)

            response = query.execute()
            return response.data or []

        except Exception:
            logger.exception("overdue_invoices_query_failed")
            raise
