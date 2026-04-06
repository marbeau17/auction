"""Common response models used across the application."""

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    total_count: int = Field(..., description="Total number of records", examples=[150])
    page: int = Field(..., description="Current page number", examples=[1])
    per_page: int = Field(..., description="Number of records per page", examples=[20])
    total_pages: int = Field(..., description="Total number of pages", examples=[8])


class ErrorDetail(BaseModel):
    """Error detail information."""

    code: str = Field(..., description="Error code", examples=["VALIDATION_ERROR"])
    message: str = Field(..., description="Human-readable error message", examples=["入力値が不正です"])
    details: Optional[list[Any]] = Field(
        default=None, description="Additional error details"
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated API response wrapper."""

    status: str = Field(default="success", description="Response status")
    data: list[T] = Field(..., description="List of result items")
    meta: PaginationMeta = Field(..., description="Pagination metadata")


class ErrorResponse(BaseModel):
    """Error API response wrapper."""

    status: str = Field(default="error", description="Response status")
    error: ErrorDetail = Field(..., description="Error detail")


class SuccessResponse(BaseModel):
    """Success API response wrapper."""

    status: str = Field(default="success", description="Response status")
    data: Any = Field(..., description="Response data")
    meta: Optional[dict[str, Any]] = Field(
        default=None, description="Optional metadata"
    )
