"""Master data Pydantic models (makers, models, body types, categories, depreciation curves)."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Maker ---


class MakerCreate(BaseModel):
    """Model for creating a new maker record."""

    name: str = Field(..., description="Maker name (Japanese)", examples=["いすゞ"])
    name_en: Optional[str] = Field(
        default=None, description="Maker name (English)", examples=["Isuzu"]
    )
    code: str = Field(
        ..., description="Unique maker code", examples=["ISUZU"]
    )


class MakerResponse(BaseModel):
    """Maker response model."""

    id: UUID = Field(..., description="Maker ID")
    name: str = Field(..., description="Maker name (Japanese)", examples=["いすゞ"])
    name_en: Optional[str] = Field(
        default=None, description="Maker name (English)", examples=["Isuzu"]
    )
    code: str = Field(..., description="Unique maker code", examples=["ISUZU"])
    display_order: int = Field(
        ..., description="Display order for UI sorting", examples=[1]
    )
    is_active: bool = Field(
        default=True, description="Whether the record is active"
    )

    model_config = {"from_attributes": True}


# --- Model ---


class ModelCreate(BaseModel):
    """Model for creating a new vehicle model record."""

    name: str = Field(..., description="Model name", examples=["エルフ"])
    code: Optional[str] = Field(
        default=None, description="Unique model code", examples=["ELF"]
    )


class ModelResponse(BaseModel):
    """Vehicle model response model."""

    id: UUID = Field(..., description="Model ID")
    maker_id: UUID = Field(..., description="Parent maker ID")
    name: str = Field(..., description="Model name", examples=["エルフ"])
    code: Optional[str] = Field(
        default=None, description="Unique model code", examples=["ELF"]
    )
    display_order: int = Field(
        ..., description="Display order for UI sorting", examples=[1]
    )
    is_active: bool = Field(
        default=True, description="Whether the record is active"
    )

    model_config = {"from_attributes": True}


# --- Body Type ---


class BodyTypeCreate(BaseModel):
    """Model for creating a new body type record."""

    name: str = Field(..., description="Body type name", examples=["平ボディ"])
    code: str = Field(
        ..., description="Unique body type code", examples=["FLATBODY"]
    )


class BodyTypeResponse(BaseModel):
    """Body type response model."""

    id: UUID = Field(..., description="Body type ID")
    name: str = Field(..., description="Body type name", examples=["平ボディ"])
    code: str = Field(
        ..., description="Unique body type code", examples=["FLATBODY"]
    )
    category_id: Optional[UUID] = Field(
        default=None, description="Associated vehicle category ID"
    )
    display_order: int = Field(
        ..., description="Display order for UI sorting", examples=[1]
    )
    is_active: bool = Field(
        default=True, description="Whether the record is active"
    )

    model_config = {"from_attributes": True}


class BodyTypeUpdate(BaseModel):
    """Model for updating a body type record."""

    name: Optional[str] = Field(default=None, description="Body type name")
    code: Optional[str] = Field(default=None, description="Unique body type code")
    category_id: Optional[UUID] = Field(
        default=None, description="Associated vehicle category ID"
    )
    display_order: Optional[int] = Field(
        default=None, description="Display order for UI sorting"
    )


# --- Vehicle Category ---


class VehicleCategoryResponse(BaseModel):
    """Vehicle category response model."""

    id: UUID = Field(..., description="Category ID")
    name: str = Field(..., description="Category name", examples=["小型トラック"])
    code: str = Field(
        ..., description="Unique category code", examples=["SMALL_TRUCK"]
    )
    display_order: int = Field(
        ..., description="Display order for UI sorting", examples=[1]
    )
    is_active: bool = Field(
        default=True, description="Whether the record is active"
    )

    model_config = {"from_attributes": True}


# --- Depreciation Curve ---


class DepreciationCurveCreate(BaseModel):
    """Model for creating/updating a depreciation curve."""

    category_id: UUID = Field(
        ..., description="Vehicle category ID this curve applies to"
    )
    year: int = Field(
        ..., description="Vehicle age in years", ge=0, le=30, examples=[3]
    )
    rate: float = Field(
        ...,
        description="Depreciation rate (decimal, 1.0 = 100% of original value)",
        ge=0,
        le=1,
        examples=[0.65],
    )
    mileage_adjustment: Optional[float] = Field(
        default=None,
        description="Mileage-based adjustment factor",
        examples=[0.02],
    )


class DepreciationCurveResponse(BaseModel):
    """Depreciation curve response model."""

    id: UUID = Field(..., description="Depreciation curve point ID")
    category_id: UUID = Field(
        ..., description="Vehicle category ID this curve applies to"
    )
    year: int = Field(
        ..., description="Vehicle age in years", ge=0, examples=[3]
    )
    rate: float = Field(
        ..., description="Depreciation rate (decimal)", examples=[0.65]
    )
    mileage_adjustment: Optional[float] = Field(
        default=None, description="Mileage-based adjustment factor"
    )
    created_at: Optional[datetime] = Field(
        default=None, description="Record creation timestamp"
    )
    updated_at: Optional[datetime] = Field(
        default=None, description="Record last update timestamp"
    )

    model_config = {"from_attributes": True}
