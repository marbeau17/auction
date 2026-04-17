"""Stakeholder and RBAC models for the CVLPOS system."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Stakeholder role types (all 10 roles in the leaseback scheme)
# ---------------------------------------------------------------------------

StakeholderRoleType = Literal[
    "spc",
    "operator",
    "investor",
    "end_user",
    "guarantor",
    "trustee",
    "private_placement_agent",
    "asset_manager",
    "accounting_firm",
    "accounting_delegate",
]


# ---------------------------------------------------------------------------
# Stakeholder CRUD models
# ---------------------------------------------------------------------------

class StakeholderCreate(BaseModel):
    """Create a new stakeholder entry linked to a simulation."""

    simulation_id: UUID = Field(..., description="Associated simulation ID")
    role_type: StakeholderRoleType = Field(
        ..., description="Stakeholder role in the deal structure"
    )
    company_name: str = Field(
        ..., description="Legal entity name", examples=["株式会社カーチス"]
    )
    representative_name: Optional[str] = Field(
        default=None, description="Representative / signatory name"
    )
    address: Optional[str] = Field(
        default=None, description="Registered address"
    )
    phone: Optional[str] = Field(
        default=None, description="Phone number", examples=["03-1234-5678"]
    )
    email: Optional[str] = Field(
        default=None, description="Contact email address"
    )
    registration_number: Optional[str] = Field(
        default=None,
        description="Corporate registration number (法人番号)",
        examples=["1234567890123"],
    )
    seal_required: bool = Field(
        default=False, description="Whether a physical seal is required on contracts"
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for the stakeholder",
    )
    display_order: int = Field(
        default=0, description="Display ordering weight"
    )

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        import re
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", v):
            raise ValueError("Invalid email address format")
        return v


class StakeholderResponse(BaseModel):
    """Stakeholder response returned from the API."""

    id: UUID
    simulation_id: UUID
    role_type: StakeholderRoleType
    company_name: str
    representative_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    registration_number: Optional[str] = None
    seal_required: bool = False
    metadata: dict = Field(default_factory=dict)
    display_order: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Address book (reusable stakeholder entries across simulations)
# ---------------------------------------------------------------------------

class StakeholderAddressBook(BaseModel):
    """Reusable stakeholder entry stored in the address book."""

    id: UUID
    company_name: str = Field(
        ..., description="Legal entity name", examples=["株式会社カーチス"]
    )
    role_type: StakeholderRoleType = Field(
        ..., description="Default role for this entity"
    )
    representative_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    registration_number: Optional[str] = None
    is_default: bool = Field(
        default=False,
        description="Whether this entry is the default for its role_type",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# RBAC models
# ---------------------------------------------------------------------------

RBACAction = Literal["read", "write", "delete"]


class RBACPermission(BaseModel):
    """A single permission rule mapping a resource + action to allowed roles."""

    resource: str = Field(
        ...,
        description="Protected resource identifier",
        examples=["pricing_logic", "market_data", "contracts"],
    )
    action: RBACAction = Field(
        ..., description="Action on the resource"
    )
    allowed_roles: list[str] = Field(
        ..., description="Roles permitted to perform this action"
    )


# ---------------------------------------------------------------------------
# RBAC matrix constant
# ---------------------------------------------------------------------------

RBAC_MATRIX: dict[str, dict[str, list[str]]] = {
    "pricing_logic": {
        "read": ["admin", "operator", "asset_manager"],
        "write": ["admin"],
    },
    "market_data": {
        "read": ["admin", "operator", "asset_manager"],
        "write": ["admin", "operator"],
    },
    "simulations": {
        "read": ["admin", "operator", "investor", "end_user", "asset_manager"],
        "write": ["admin", "operator"],
    },
    "contracts": {
        "read": [
            "admin",
            "operator",
            "investor",
            "end_user",
            "asset_manager",
            "private_placement_agent",
            "accounting_firm",
            "accounting_delegate",
        ],
        "write": ["admin", "operator"],
    },
    "invoices": {
        "read": ["admin", "operator", "end_user", "accounting_firm", "accounting_delegate"],
        "write": ["admin", "operator"],
    },
    "fund_info": {
        "read": [
            "admin",
            "operator",
            "investor",
            "asset_manager",
            "accounting_firm",
            "accounting_delegate",
        ],
        "write": ["admin"],
    },
    "vehicle_inventory": {
        "read": ["admin", "operator", "investor", "asset_manager"],
        "write": ["admin", "operator"],
    },
    "dashboard": {
        "read": [
            "admin",
            "operator",
            "investor",
            "asset_manager",
            "accounting_firm",
            "accounting_delegate",
        ],
        "write": ["admin"],
    },
}
