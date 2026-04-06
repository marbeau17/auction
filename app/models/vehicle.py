"""Vehicle-related Pydantic models."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class VehicleBase(BaseModel):
    """Base vehicle model with shared fields."""

    source_site: str = Field(
        ..., description="Scraping source site name", examples=["truckmarket"]
    )
    source_url: str = Field(
        ...,
        description="Original listing URL",
        examples=["https://example.com/listing/12345"],
    )
    source_id: str = Field(
        ..., description="ID on the source site", examples=["TM-12345"]
    )
    maker: str = Field(..., description="Vehicle manufacturer name", examples=["いすゞ"])
    model_name: str = Field(
        ..., description="Vehicle model name", examples=["エルフ"]
    )
    body_type: str = Field(..., description="Vehicle body type", examples=["平ボディ"])
    model_year: int = Field(
        ..., description="Model year", ge=1970, le=2100, examples=[2020]
    )
    mileage_km: int = Field(
        ..., description="Mileage in kilometers", ge=0, examples=[85000]
    )
    price_yen: Optional[int] = Field(
        default=None,
        description="Vehicle price in yen (tax excluded)",
        ge=0,
        examples=[3500000],
    )
    price_tax_included: bool = Field(
        ..., description="Whether the price includes tax", examples=[True]
    )
    tonnage: Optional[float] = Field(
        default=None, description="Payload capacity in tons", ge=0, examples=[2.0]
    )
    transmission: Optional[str] = Field(
        default=None, description="Transmission type", examples=["AT"]
    )
    fuel_type: Optional[str] = Field(
        default=None, description="Fuel type", examples=["軽油"]
    )
    location_prefecture: Optional[str] = Field(
        default=None, description="Location prefecture", examples=["東京都"]
    )
    listing_status: str = Field(
        ..., description="Current listing status", examples=["active"]
    )
    scraped_at: datetime = Field(
        ..., description="Datetime when the listing was scraped"
    )


class VehicleCreate(VehicleBase):
    """Model for creating a new vehicle record."""

    pass


class VehicleResponse(VehicleBase):
    """Vehicle response model with database-generated fields."""

    id: UUID = Field(..., description="Unique vehicle identifier")
    category_id: Optional[UUID] = Field(
        default=None, description="Vehicle category ID"
    )
    manufacturer_id: Optional[UUID] = Field(
        default=None, description="Manufacturer master ID"
    )
    body_type_id: Optional[UUID] = Field(
        default=None, description="Body type master ID"
    )
    is_active: bool = Field(
        default=True, description="Whether the record is active"
    )
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Record last update timestamp")

    model_config = {"from_attributes": True}


class VehicleSearchParams(BaseModel):
    """Query parameters for vehicle search."""

    maker: Optional[str] = Field(default=None, description="Filter by maker name")
    model_name: Optional[str] = Field(
        default=None, description="Filter by model name"
    )
    year_from: Optional[int] = Field(
        default=None, description="Minimum model year", ge=1970, examples=[2018]
    )
    year_to: Optional[int] = Field(
        default=None, description="Maximum model year", le=2100, examples=[2024]
    )
    mileage_from: Optional[int] = Field(
        default=None, description="Minimum mileage (km)", ge=0
    )
    mileage_to: Optional[int] = Field(
        default=None, description="Maximum mileage (km)", ge=0
    )
    body_type: Optional[str] = Field(
        default=None, description="Filter by body type"
    )
    price_from: Optional[int] = Field(
        default=None, description="Minimum price (yen)", ge=0
    )
    price_to: Optional[int] = Field(
        default=None, description="Maximum price (yen)", ge=0
    )
    page: int = Field(default=1, description="Page number", ge=1, examples=[1])
    per_page: int = Field(
        default=20, description="Results per page", ge=1, le=100, examples=[20]
    )
    sort: str = Field(
        default="scraped_at",
        description="Sort field",
        examples=["scraped_at"],
    )
    order: Literal["asc", "desc"] = Field(
        default="desc", description="Sort order", examples=["desc"]
    )
