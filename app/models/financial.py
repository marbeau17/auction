"""Pydantic models for transport company financial analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ #
# Financial analysis input
# ------------------------------------------------------------------ #


class FinancialAnalysisInput(BaseModel):
    """Input parameters for transport company financial diagnosis."""

    company_name: str = Field(
        ..., description="運送会社名", examples=["大和運輸株式会社"]
    )
    revenue: int = Field(
        ..., ge=0, description="売上高(年間,円)", examples=[500_000_000]
    )
    operating_profit: int = Field(
        ..., description="営業利益(年間,円)", examples=[25_000_000]
    )
    ordinary_profit: int = Field(
        ..., description="経常利益(年間,円)", examples=[22_000_000]
    )
    total_assets: int = Field(
        ..., ge=0, description="総資産(円)", examples=[300_000_000]
    )
    total_liabilities: int = Field(
        ..., ge=0, description="総負債(円)", examples=[180_000_000]
    )
    equity: int = Field(
        ..., description="自己資本(円)", examples=[120_000_000]
    )
    current_assets: int = Field(
        ..., ge=0, description="流動資産(円)", examples=[80_000_000]
    )
    current_liabilities: int = Field(
        ..., ge=0, description="流動負債(円)", examples=[60_000_000]
    )
    quick_assets: Optional[int] = Field(
        default=None, ge=0, description="当座資産(円)", examples=[50_000_000]
    )
    interest_bearing_debt: int = Field(
        default=0, ge=0, description="有利子負債(円)", examples=[100_000_000]
    )
    operating_cf: Optional[int] = Field(
        default=None, description="営業CF(年間,円)", examples=[30_000_000]
    )
    free_cf: Optional[int] = Field(
        default=None, description="フリーCF(年間,円)", examples=[15_000_000]
    )
    vehicle_count: int = Field(
        default=0, ge=0, description="保有車両台数", examples=[50]
    )
    vehicle_utilization_rate: float = Field(
        default=0, ge=0, le=1, description="稼働率", examples=[0.85]
    )
    existing_lease_monthly: int = Field(
        default=0, ge=0, description="既存リース月額合計(円)", examples=[2_000_000]
    )
    existing_loan_balance: int = Field(
        default=0, ge=0, description="既存ローン残高(円)", examples=[50_000_000]
    )


# ------------------------------------------------------------------ #
# Financial analysis result
# ------------------------------------------------------------------ #


class FinancialAnalysisResult(BaseModel):
    """Result of transport company financial diagnosis."""

    score: Literal["A", "B", "C", "D"] = Field(
        ..., description="総合スコア (A=優良, D=非推奨)", examples=["B"]
    )
    score_numeric: float = Field(
        ...,
        description="数値スコア (0-100)",
        ge=0,
        le=100,
        examples=[72.5],
    )
    risk_level: Literal["推奨", "要注意", "非推奨"] = Field(
        ..., description="リスクレベル", examples=["推奨"]
    )
    max_monthly_lease: int = Field(
        ...,
        description="推定最大月額リース可能額(円)",
        ge=0,
        examples=[3_000_000],
    )
    recommended_lease_term_min: int = Field(
        ...,
        description="推奨リース期間下限(月)",
        ge=1,
        examples=[24],
    )
    recommended_lease_term_max: int = Field(
        ...,
        description="推奨リース期間上限(月)",
        ge=1,
        examples=[60],
    )
    equity_ratio: float = Field(
        ..., description="自己資本比率", examples=[0.40]
    )
    current_ratio: float = Field(
        ..., description="流動比率", examples=[1.33]
    )
    quick_ratio: Optional[float] = Field(
        default=None, description="当座比率", examples=[0.83]
    )
    debt_ratio: float = Field(
        ..., description="負債比率", examples=[1.50]
    )
    operating_profit_margin: float = Field(
        ..., description="営業利益率", examples=[0.05]
    )
    ebitda: int = Field(
        ..., description="EBITDA概算(円)", examples=[35_000_000]
    )
    lease_to_revenue_ratio: float = Field(
        ...,
        description="リース負担率(既存リース年額/売上高)",
        examples=[0.048],
    )
    recommendations: list[str] = Field(
        ...,
        description="推奨事項(日本語)",
        examples=[["自己資本比率が高く安定した財務体質", "リース余力あり"]],
    )
    warnings: list[str] = Field(
        ...,
        description="警告事項(日本語)",
        examples=[["流動比率が業界平均を下回っています"]],
    )
    detail_scores: dict[str, float] = Field(
        ...,
        description="項目別スコア",
        examples=[{"収益性": 75.0, "安全性": 80.0, "流動性": 65.0, "効率性": 70.0}],
    )


# ------------------------------------------------------------------ #
# Combined financial + pricing result
# ------------------------------------------------------------------ #


class FinancialWithPricingInput(BaseModel):
    """Combined input for financial analysis + pricing simulation."""

    financial: FinancialAnalysisInput = Field(
        ..., description="財務分析入力データ"
    )
    pricing: "IntegratedPricingInput" = Field(
        ..., description="プライシングシミュレーション入力データ"
    )


class FinancialWithPricingResult(BaseModel):
    """Combined result from financial analysis and pricing simulation."""

    financial: FinancialAnalysisResult = Field(
        ..., description="財務分析結果"
    )
    pricing: "IntegratedPricingResult" = Field(
        ..., description="プライシングシミュレーション結果"
    )
    overall_assessment: Literal["推奨", "要検討", "非推奨"] = Field(
        ..., description="総合判定", examples=["推奨"]
    )
    overall_reasons: list[str] = Field(
        ...,
        description="総合判定理由(日本語)",
        examples=[["財務スコアB以上かつ利回り6%以上"]],
    )


# ------------------------------------------------------------------ #
# History entry
# ------------------------------------------------------------------ #


class FinancialAnalysisHistoryEntry(BaseModel):
    """A single historical financial analysis record."""

    id: UUID = Field(..., description="分析レコードID")
    company_name: str = Field(..., description="運送会社名")
    input_data: FinancialAnalysisInput = Field(
        ..., description="入力データ"
    )
    result: FinancialAnalysisResult = Field(
        ..., description="分析結果"
    )
    created_at: datetime = Field(..., description="分析実行日時")

    model_config = {"from_attributes": True}


# Deferred imports for forward references
from app.models.pricing import IntegratedPricingInput, IntegratedPricingResult  # noqa: E402

FinancialWithPricingInput.model_rebuild()
FinancialWithPricingResult.model_rebuild()
