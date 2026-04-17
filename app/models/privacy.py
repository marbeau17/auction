"""Pydantic models for APPI / GDPR privacy endpoints.

These map to :mod:`supabase/migrations/20260417000005_privacy_requests.sql`.
They are consumed by :mod:`app.api.privacy`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DeletionStatus = Literal["pending_review", "approved", "executed", "rejected"]


class DeletionRequest(BaseModel):
    """Body accepted by ``POST /api/v1/privacy/delete-request``.

    The caller can attach a free-form ``reason`` for audit and regulatory
    review.  The ``user_id`` is **always** taken from the authenticated
    session on the server side, never from this payload.
    """

    reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional user-supplied reason for the deletion request.",
        examples=["退会のためアカウント情報を削除してください。"],
    )


class DeletionRequestResponse(BaseModel):
    """Response shape for a single ``privacy_deletion_requests`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Deletion request identifier.")
    user_id: UUID = Field(..., description="Subject of the erasure request.")
    requested_at: datetime = Field(..., description="When the user filed the request.")
    reason: Optional[str] = Field(default=None, description="User-supplied reason.")
    status: DeletionStatus = Field(..., description="Workflow status.")
    reviewed_by: Optional[UUID] = Field(
        default=None, description="Admin user-id who reviewed the request."
    )
    reviewed_at: Optional[datetime] = Field(
        default=None, description="Review timestamp."
    )
    executed_at: Optional[datetime] = Field(
        default=None, description="Timestamp of hard-execution (redaction)."
    )
    notes: Optional[str] = Field(
        default=None,
        description="Admin notes (e.g. retained records, identity-verification outcome).",
    )
