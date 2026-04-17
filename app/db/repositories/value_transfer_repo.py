"""Repository for value_allocations and transfer_instructions tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog

from app.models.value_transfer import (
    DistributionPlan,
    StakeholderShare,
    TransferInstruction,
    ValueAllocation,
)

logger = structlog.get_logger()

ALLOCATIONS_TABLE = "value_allocations"
INSTRUCTIONS_TABLE = "transfer_instructions"


class ValueTransferRepository:
    """CRUD + domain operations for the Value Transfer Engine tables."""

    def __init__(self, client: Any) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Create: allocation + instructions in one logical unit
    # ------------------------------------------------------------------

    async def create_allocation(
        self,
        allocation: ValueAllocation,
        plan: DistributionPlan,
    ) -> dict[str, Any]:
        """Persist a computed allocation and its instruction plan.

        Returns the created allocation dict with an ``instructions`` key
        containing the persisted transfer_instructions rows.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            # Build the JSONB allocation breakdown keyed by canonical
            # role label.
            allocation_json: dict[str, Any] = {
                s.role: s.amount_jpy for s in allocation.shares
            }

            row: dict[str, Any] = {
                "fund_id": str(allocation.fund_id),
                "period_start": allocation.period_start.isoformat(),
                "period_end": allocation.period_end.isoformat(),
                "gross_income": allocation.gross_income,
                "net_income": allocation.net_income,
                "allocation": allocation_json,
                "reconciliation_diff": allocation.reconciliation_diff,
                "status": allocation.status,
                "created_at": now,
            }

            resp = (
                self._client.table(ALLOCATIONS_TABLE).insert(row).execute()
            )
            data = resp.data or []
            if not data:
                raise RuntimeError("value_allocation insert returned no data")

            allocation_row = data[0]
            allocation_id = allocation_row["id"]

            # Persist the plan
            instruction_rows: list[dict[str, Any]] = []
            for inst in plan.instructions:
                instruction_rows.append(
                    {
                        "allocation_id": allocation_id,
                        "stakeholder_role": inst.to_stakeholder_role,
                        "amount_jpy": inst.amount_jpy,
                        "memo": inst.memo,
                        "status": inst.status,
                        "created_at": now,
                    }
                )

            if instruction_rows:
                resp2 = (
                    self._client.table(INSTRUCTIONS_TABLE)
                    .insert(instruction_rows)
                    .execute()
                )
                persisted = resp2.data or []
            else:
                persisted = []

            allocation_row["instructions"] = persisted
            return allocation_row

        except Exception:
            logger.exception(
                "value_allocation_create_failed",
                fund_id=str(allocation.fund_id),
            )
            raise

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_allocation(
        self, allocation_id: UUID
    ) -> Optional[dict[str, Any]]:
        """Load a single allocation joined with its instructions."""
        try:
            resp = (
                self._client.table(ALLOCATIONS_TABLE)
                .select("*")
                .eq("id", str(allocation_id))
                .maybe_single()
                .execute()
            )
            allocation = resp.data
            if not allocation:
                return None

            inst_resp = (
                self._client.table(INSTRUCTIONS_TABLE)
                .select("*")
                .eq("allocation_id", str(allocation_id))
                .order("created_at")
                .execute()
            )
            allocation["instructions"] = inst_resp.data or []
            return allocation

        except Exception:
            logger.exception(
                "value_allocation_get_failed",
                allocation_id=str(allocation_id),
            )
            raise

    async def list_allocations(
        self,
        fund_id: Optional[UUID] = None,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List allocations, optionally filtered by fund and status."""
        try:
            query = self._client.table(ALLOCATIONS_TABLE).select("*")
            if fund_id is not None:
                query = query.eq("fund_id", str(fund_id))
            if status is not None:
                query = query.eq("status", status)
            resp = query.order("period_start", desc=True).execute()
            return resp.data or []
        except Exception:
            logger.exception(
                "value_allocation_list_failed",
                fund_id=str(fund_id) if fund_id else None,
                status=status,
            )
            raise

    async def list_instructions(
        self, allocation_id: UUID
    ) -> list[dict[str, Any]]:
        """List all transfer_instructions for a given allocation."""
        try:
            resp = (
                self._client.table(INSTRUCTIONS_TABLE)
                .select("*")
                .eq("allocation_id", str(allocation_id))
                .order("created_at")
                .execute()
            )
            return resp.data or []
        except Exception:
            logger.exception(
                "value_allocation_instructions_list_failed",
                allocation_id=str(allocation_id),
            )
            raise

    # ------------------------------------------------------------------
    # Approve (lock)
    # ------------------------------------------------------------------

    async def approve_allocation(
        self,
        allocation_id: UUID,
        approver_user_id: UUID,
    ) -> dict[str, Any]:
        """Promote a draft allocation to ``approved`` (locks the row)."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            resp = (
                self._client.table(ALLOCATIONS_TABLE)
                .update(
                    {
                        "status": "approved",
                        "approved_at": now,
                        "approved_by": str(approver_user_id),
                    }
                )
                .eq("id", str(allocation_id))
                .execute()
            )
            data = resp.data or []
            if not data:
                raise RuntimeError(
                    f"value_allocation {allocation_id} not found for approval"
                )
            return data[0]
        except Exception:
            logger.exception(
                "value_allocation_approve_failed",
                allocation_id=str(allocation_id),
            )
            raise
