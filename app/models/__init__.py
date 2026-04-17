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
from app.models.pricing import (
    AcquisitionPriceResult,
    IntegratedPricingInput,
    IntegratedPricingResponse,
    IntegratedPricingResult,
    LeaseFeeBreakdown,
    LeasePriceResult,
    NAVPoint,
    PricingMasterCreate,
    PricingMasterResponse,
    ResidualValueResult,
    ScenarioValue,
)
from app.models.invoice import (
    EmailLogResponse,
    InvoiceApprovalCreate,
    InvoiceApprovalResponse,
    InvoiceCreate,
    InvoiceLineItemCreate,
    InvoiceLineItemResponse,
    InvoiceResponse,
    InvoiceSendRequest,
    InvoiceStatusUpdate,
)
from app.models.financial import (
    FinancialAnalysisInput,
    FinancialAnalysisResult,
    FinancialWithPricingInput,
    FinancialWithPricingResult,
    FinancialAnalysisHistoryEntry,
)
from app.models.stakeholder import (
    StakeholderCreate,
    StakeholderResponse,
    StakeholderAddressBook,
    StakeholderRoleType,
    RBAC_MATRIX,
    RBACPermission,
)
from app.models.vehicle import (
    VehicleBase,
    VehicleCreate,
    VehicleResponse,
    VehicleSearchParams,
)
from app.models.vehicle_inventory import (
    VehicleInventory,
    VehicleInventoryList,
    VehicleInventoryStatus,
    VehicleNAVHistoryPoint,
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
    # Invoice
    "EmailLogResponse",
    "InvoiceApprovalCreate",
    "InvoiceApprovalResponse",
    "InvoiceCreate",
    "InvoiceLineItemCreate",
    "InvoiceLineItemResponse",
    "InvoiceResponse",
    "InvoiceSendRequest",
    "InvoiceStatusUpdate",
    # Pricing
    "AcquisitionPriceResult",
    "IntegratedPricingInput",
    "IntegratedPricingResponse",
    "IntegratedPricingResult",
    "LeaseFeeBreakdown",
    "LeasePriceResult",
    "NAVPoint",
    "PricingMasterCreate",
    "PricingMasterResponse",
    "ResidualValueResult",
    "ScenarioValue",
    # Financial
    "FinancialAnalysisInput",
    "FinancialAnalysisResult",
    "FinancialWithPricingInput",
    "FinancialWithPricingResult",
    "FinancialAnalysisHistoryEntry",
    # Stakeholder
    "StakeholderCreate",
    "StakeholderResponse",
    "StakeholderAddressBook",
    "StakeholderRoleType",
    "RBAC_MATRIX",
    "RBACPermission",
    # Vehicle
    "VehicleBase",
    "VehicleCreate",
    "VehicleResponse",
    "VehicleSearchParams",
    # Vehicle inventory (Epic 4)
    "VehicleInventory",
    "VehicleInventoryList",
    "VehicleInventoryStatus",
    "VehicleNAVHistoryPoint",
]
