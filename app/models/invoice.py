"""Invoice and billing-related Pydantic models for the CVLPOS system."""

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Line Items
# ---------------------------------------------------------------------------


class InvoiceLineItemCreate(BaseModel):
    """Model for creating a single invoice line item."""

    description: str = Field(
        ..., description="Line item description", examples=["月額リース料"]
    )
    quantity: int = Field(
        default=1, description="Quantity", ge=1, examples=[1]
    )
    unit_price: int = Field(
        ..., description="Unit price in yen", ge=0, examples=[150000]
    )
    amount: int = Field(
        ..., description="Line item amount in yen", ge=0, examples=[150000]
    )


class InvoiceLineItemResponse(InvoiceLineItemCreate):
    """Invoice line item response model with database-generated fields."""

    id: UUID = Field(..., description="Unique line item identifier")
    invoice_id: UUID = Field(..., description="Parent invoice identifier")
    display_order: int = Field(
        ..., description="Display order within the invoice", ge=0, examples=[1]
    )
    created_at: datetime = Field(..., description="Record creation timestamp")


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


class InvoiceCreate(BaseModel):
    """Model for creating a new invoice."""

    fund_id: UUID = Field(..., description="Fund identifier")
    lease_contract_id: UUID = Field(..., description="Lease contract identifier")
    invoice_number: str = Field(
        ...,
        description="Unique invoice number",
        examples=["INV-2026-0001"],
    )
    billing_period_start: date = Field(
        ..., description="Billing period start date", examples=["2026-04-01"]
    )
    billing_period_end: date = Field(
        ..., description="Billing period end date", examples=["2026-04-30"]
    )
    subtotal: int = Field(
        ..., description="Subtotal amount in yen (tax excluded)", ge=0, examples=[150000]
    )
    tax_rate: float = Field(
        default=0.10,
        description="Tax rate",
        ge=0.0,
        le=1.0,
        examples=[0.10],
    )
    tax_amount: int = Field(
        ..., description="Tax amount in yen", ge=0, examples=[15000]
    )
    total_amount: int = Field(
        ..., description="Total amount in yen (tax included)", ge=0, examples=[165000]
    )
    due_date: date = Field(
        ..., description="Payment due date", examples=["2026-04-30"]
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional notes for the invoice",
        examples=["初回請求"],
    )
    line_items: list[InvoiceLineItemCreate] = Field(
        ..., description="List of invoice line items"
    )


InvoiceStatusType = Literal[
    "created",
    "pending_review",
    "approved",
    "pdf_ready",
    "sent",
    "paid",
    "overdue",
    "cancelled",
]


class InvoiceResponse(BaseModel):
    """Invoice response model with database-generated fields."""

    id: UUID = Field(..., description="Unique invoice identifier")
    fund_id: UUID = Field(..., description="Fund identifier")
    lease_contract_id: UUID = Field(..., description="Lease contract identifier")
    invoice_number: str = Field(
        ...,
        description="Unique invoice number",
        examples=["INV-2026-0001"],
    )
    billing_period_start: date = Field(
        ..., description="Billing period start date", examples=["2026-04-01"]
    )
    billing_period_end: date = Field(
        ..., description="Billing period end date", examples=["2026-04-30"]
    )
    subtotal: int = Field(
        ..., description="Subtotal amount in yen (tax excluded)", ge=0, examples=[150000]
    )
    tax_rate: float = Field(
        default=0.10,
        description="Tax rate",
        ge=0.0,
        le=1.0,
        examples=[0.10],
    )
    tax_amount: int = Field(
        ..., description="Tax amount in yen", ge=0, examples=[15000]
    )
    total_amount: int = Field(
        ..., description="Total amount in yen (tax included)", ge=0, examples=[165000]
    )
    due_date: date = Field(
        ..., description="Payment due date", examples=["2026-04-30"]
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional notes for the invoice",
        examples=["初回請求"],
    )
    status: InvoiceStatusType = Field(
        ..., description="Current invoice status", examples=["created"]
    )
    pdf_url: Optional[str] = Field(
        default=None,
        description="URL to the generated PDF",
        examples=["https://storage.example.com/invoices/INV-2026-0001.pdf"],
    )
    sent_at: Optional[datetime] = Field(
        default=None, description="Datetime when the invoice was sent"
    )
    paid_at: Optional[datetime] = Field(
        default=None, description="Datetime when the invoice was paid"
    )
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")
    line_items: list[InvoiceLineItemResponse] = Field(
        ..., description="List of invoice line items"
    )


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

InvoiceApprovalActionType = Literal["approve", "reject", "request_change"]


class InvoiceApprovalCreate(BaseModel):
    """Model for creating an invoice approval decision."""

    invoice_id: UUID = Field(..., description="Invoice identifier to act on")
    action: InvoiceApprovalActionType = Field(
        ..., description="Approval action", examples=["approve"]
    )
    comment: Optional[str] = Field(
        default=None,
        description="Approval comment or reason",
        examples=["内容確認済み、承認します"],
    )


class InvoiceApprovalResponse(InvoiceApprovalCreate):
    """Invoice approval response model with database-generated fields."""

    id: UUID = Field(..., description="Unique approval record identifier")
    approver_user_id: UUID = Field(..., description="User who performed the action")
    created_at: datetime = Field(..., description="Record creation timestamp")


# ---------------------------------------------------------------------------
# Status Update
# ---------------------------------------------------------------------------


class InvoiceStatusUpdate(BaseModel):
    """Model for updating an invoice status."""

    status: str = Field(
        ..., description="New invoice status", examples=["approved"]
    )
    comment: Optional[str] = Field(
        default=None,
        description="Reason for the status change",
        examples=["承認完了"],
    )


# ---------------------------------------------------------------------------
# Send / Email
# ---------------------------------------------------------------------------


class InvoiceSendRequest(BaseModel):
    """Model for sending an invoice via email."""

    recipient_email: str = Field(
        ...,
        description="Recipient email address",
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        examples=["tenant@example.com"],
    )
    subject: Optional[str] = Field(
        default="請求書送付のご案内",
        description="Email subject line",
        examples=["請求書送付のご案内"],
    )
    include_pdf: bool = Field(
        default=True, description="Whether to attach the PDF invoice", examples=[True]
    )


class EmailLogResponse(BaseModel):
    """Email send log response model."""

    id: UUID = Field(..., description="Unique email log identifier")
    invoice_id: UUID = Field(..., description="Related invoice identifier")
    recipient_email: str = Field(
        ..., description="Recipient email address", examples=["tenant@example.com"]
    )
    subject: str = Field(
        ..., description="Email subject line", examples=["請求書送付のご案内"]
    )
    status: str = Field(
        ..., description="Email delivery status", examples=["sent"]
    )
    sent_at: Optional[datetime] = Field(
        default=None, description="Datetime when the email was sent"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if delivery failed"
    )
    created_at: datetime = Field(..., description="Record creation timestamp")
