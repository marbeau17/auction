"""Pydantic models for the Commercial Vehicle Leaseback Pricing Optimizer."""

from app.models.common import (
    ErrorDetail,
    ErrorResponse,
    PaginatedResponse,
    PaginationMeta,
    SuccessResponse,
)
from app.models.master import (
    BodyTypeCreate,
    BodyTypeResponse,
    MakerCreate,
    MakerResponse,
    ModelCreate,
    ModelResponse,
    VehicleCategoryResponse,
)
from app.models.simulation import (
    MonthlyScheduleItem,
    SimulationInput,
    SimulationResponse,
    SimulationResult,
)
from app.models.vehicle import (
    VehicleBase,
    VehicleCreate,
    VehicleResponse,
    VehicleSearchParams,
)

__all__ = [
    # Common
    "ErrorDetail",
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationMeta",
    "SuccessResponse",
    # Master
    "BodyTypeCreate",
    "BodyTypeResponse",
    "MakerCreate",
    "MakerResponse",
    "ModelCreate",
    "ModelResponse",
    "VehicleCategoryResponse",
    # Simulation
    "MonthlyScheduleItem",
    "SimulationInput",
    "SimulationResponse",
    "SimulationResult",
    # Vehicle
    "VehicleBase",
    "VehicleCreate",
    "VehicleResponse",
    "VehicleSearchParams",
]
