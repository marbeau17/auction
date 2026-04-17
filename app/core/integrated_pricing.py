"""Integrated pricing engine orchestrating 3-step price calculation.

Combines the three pricing steps into a single pipeline:

- **Step 1** :class:`AcquisitionPriceCalculator` -- appropriate purchase price
- **Step 2** :class:`ResidualValueCalculatorV2` -- residual / exit value with
  bull / base / bear scenarios
- **Step 3** :class:`LeasePriceCalculator` -- monthly sub-lease fee with
  stakeholder yield allocation

Then generates the NAV (Net Asset Value) curve via :class:`NAVCalculator`
and performs deal-quality assessment.
"""

from __future__ import annotations

from typing import Literal

import structlog
from supabase import Client

from app.core.acquisition_price import AcquisitionPriceCalculator
from app.core.lease_price import LeasePriceCalculator
from app.core.nav_calculator import NAVCalculator
from app.core.residual_value_v2 import ResidualValueCalculatorV2
from app.core.pricing_constants import DEFAULT_PRICING_PARAMS
from app.models.pricing import (
    IntegratedPricingInput,
    IntegratedPricingResult,
    NAVPoint,
)

logger = structlog.get_logger()


class IntegratedPricingEngine:
    """Orchestrates the 3-step integrated pricing calculation.

    Step 1: AcquisitionPriceCalculator  -> appropriate purchase price
    Step 2: ResidualValueCalculatorV2   -> residual / exit value with scenarios
    Step 3: LeasePriceCalculator        -> monthly lease fee with stakeholder yields
    +       NAVCalculator               -> NAV curve generation & profit conversion analysis
    """

    _DEFAULTS: dict[str, float | int | str] = DEFAULT_PRICING_PARAMS

    def __init__(self, supabase_client: Client) -> None:
        self.supabase = supabase_client
        self.acquisition_calc = AcquisitionPriceCalculator(supabase_client)
        self.residual_calc = ResidualValueCalculatorV2()
        self.lease_calc = LeasePriceCalculator()
        self.nav_calc = NAVCalculator()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def calculate(
        self,
        input_data: IntegratedPricingInput,
        pricing_params: dict | None = None,
    ) -> IntegratedPricingResult:
        """Run the full 3-step calculation pipeline.

        Parameters
        ----------
        input_data:
            Vehicle identification, lease terms, and optional parameter
            overrides.
        pricing_params:
            External pricing-parameter overrides (e.g. from a
            ``pricing_masters`` database row).

        Returns
        -------
        IntegratedPricingResult
            Combined result covering all three steps, the NAV curve,
            profit-conversion month, and the deal assessment.
        """
        log = logger.bind(
            maker=input_data.maker,
            model=input_data.model,
            lease_term=input_data.lease_term_months,
        )
        log.info("integrated_pricing.start")

        # Resolve merged parameters
        params = self._resolve_params(input_data, pricing_params)

        # ---- Step 1: Acquisition price ----------------------------------
        acq_input = self._build_acquisition_input(input_data)
        acquisition = await self.acquisition_calc.calculate(
            acq_input, float(params["safety_margin_rate"])
        )
        log.info(
            "integrated_pricing.step1_done",
            recommended=acquisition.recommended_price,
            sample_count=acquisition.sample_count,
        )

        # ---- Step 2: Residual value (uses acquisition from Step 1) ------
        residual = self.residual_calc.calculate(
            acquisition_price=acquisition.recommended_price,
            vehicle_class=input_data.vehicle_class,
            body_type=input_data.body_type,
            lease_term_months=input_data.lease_term_months,
            current_mileage_km=input_data.mileage_km,
            registration_year_month=input_data.registration_year_month,
            depreciation_method=str(params["depreciation_method"]),
        )
        log.info(
            "integrated_pricing.step2_done",
            base_residual=residual.base_residual_value,
            scenarios=[s.label for s in residual.scenarios],
        )

        # ---- Step 3: Lease price (uses acq + residual from 1 & 2) -------
        lease = self.lease_calc.calculate(
            acquisition_price=acquisition.recommended_price,
            residual_value=residual.base_residual_value,
            lease_term_months=input_data.lease_term_months,
            investor_yield_rate=float(params["investor_yield_rate"]),
            am_fee_rate=float(params["am_fee_rate"]),
            placement_fee_rate=float(params["placement_fee_rate"]),
            accounting_fee_monthly=int(params["accounting_fee_monthly"]),
            operator_margin_rate=float(params["operator_margin_rate"]),
        )
        log.info(
            "integrated_pricing.step3_done",
            monthly_fee=lease.monthly_lease_fee,
            effective_yield=lease.effective_yield_rate,
        )

        # ---- NAV curve --------------------------------------------------
        monthly_costs = self._extract_monthly_costs(lease.fee_breakdown)
        nav_curve = self.nav_calc.generate_nav_curve(
            acquisition_price=acquisition.recommended_price,
            residual_value=residual.base_residual_value,
            monthly_lease_fee=lease.monthly_lease_fee,
            lease_term_months=input_data.lease_term_months,
            monthly_costs=monthly_costs,
        )

        # Profit conversion month
        profit_month = self.nav_calc.find_profit_conversion_month(nav_curve)
        if profit_month is None:
            profit_month = input_data.lease_term_months  # fallback to end

        # ---- Deal assessment --------------------------------------------
        assessment, reasons = self._assess_deal(
            acquisition=acquisition,
            residual=residual,
            lease=lease,
            profit_month=profit_month,
            lease_term=input_data.lease_term_months,
            nav_curve=nav_curve,
        )

        log.info(
            "integrated_pricing.done",
            assessment=assessment,
            profit_conversion_month=profit_month,
        )

        return IntegratedPricingResult(
            acquisition=acquisition,
            residual=residual,
            lease=lease,
            nav_curve=nav_curve,
            profit_conversion_month=profit_month,
            assessment=assessment,
            assessment_reasons=reasons,
        )

    # ------------------------------------------------------------------
    # Parameter resolution
    # ------------------------------------------------------------------

    def _resolve_params(
        self,
        input_data: IntegratedPricingInput,
        pricing_params: dict | None,
    ) -> dict:
        """Merge default -> master -> input-level parameter overrides.

        Priority (highest wins):
            1. Explicit fields on ``input_data`` (e.g. ``investor_yield_rate``)
            2. ``pricing_params`` dict (from pricing_master table)
            3. Built-in ``_DEFAULTS``
        """
        merged: dict = dict(self._DEFAULTS)

        # Layer 2: pricing_params from external source (e.g. DB)
        if pricing_params:
            merged.update(
                {k: v for k, v in pricing_params.items() if v is not None}
            )

        # Layer 1: input-level overrides (highest priority)
        _OVERRIDE_KEYS = [
            "investor_yield_rate",
            "am_fee_rate",
            "placement_fee_rate",
            "accounting_fee_monthly",
            "operator_margin_rate",
            "safety_margin_rate",
            "depreciation_method",
        ]
        for key in _OVERRIDE_KEYS:
            val = getattr(input_data, key, None)
            if val is not None:
                merged[key] = val

        return merged

    # ------------------------------------------------------------------
    # Input adapters
    # ------------------------------------------------------------------

    @staticmethod
    def _build_acquisition_input(
        input_data: IntegratedPricingInput,
    ) -> dict:
        """Convert IntegratedPricingInput to the dict expected by
        AcquisitionPriceCalculator.calculate().
        """
        result: dict = {
            "maker": input_data.maker,
            "model": input_data.model,
            "registration_year_month": input_data.registration_year_month,
            "mileage_km": input_data.mileage_km,
            "vehicle_class": input_data.vehicle_class,
            "body_type": input_data.body_type,
            "body_option_value": input_data.body_option_value,
        }
        if input_data.model_code is not None:
            result["model_code"] = input_data.model_code
        if input_data.book_value is not None:
            result["book_value"] = input_data.book_value
        return result

    @staticmethod
    def _extract_monthly_costs(breakdown) -> dict[str, int]:
        """Extract monthly cost components from LeaseFeeBreakdown into a
        dict suitable for NAVCalculator.
        """
        return {
            "investor": breakdown.investor_dividend_portion,
            "am": breakdown.am_fee_portion,
            "placement": breakdown.placement_fee_portion,
            "accounting": breakdown.accounting_fee_portion,
            "margin": breakdown.operator_margin_portion,
        }

    # ------------------------------------------------------------------
    # Deal assessment
    # ------------------------------------------------------------------

    def _assess_deal(
        self,
        acquisition,
        residual,
        lease,
        profit_month: int,
        lease_term: int,
        nav_curve: list[NAVPoint],
    ) -> tuple[Literal["推奨", "要検討", "非推奨"], list[str]]:
        """Assess overall deal quality and return Japanese reasons.

        Evaluation criteria:

        1. **Breakeven ratio** -- ``profit_month / lease_term``
           - < 0.70  -> positive
           - 0.70-0.90 -> neutral
           - > 0.90  -> negative

        2. **Effective yield rate**
           - >= 0.06 (6 %) -> positive
           - 0.04-0.06     -> neutral
           - < 0.04        -> negative

        3. **Residual rate** -- ``base_residual / acquisition``
           - 0.05-0.50 -> reasonable
           - outside   -> risky

        4. **Sample count** (market data confidence)
           - >= 5 -> adequate
           - < 5  -> caution

        5. **Termination recovery** -- final month's termination value
           - > 0  -> positive
           - <= 0 -> caution

        Scoring: +1 per positive criterion, -1 per negative.
        >= 3 -> 推奨, >= 1 -> 要検討, else -> 非推奨
        """
        reasons: list[str] = []
        score = 0

        # ---- 1. Breakeven ratio ----
        if lease_term > 0:
            breakeven_ratio = profit_month / lease_term
        else:
            breakeven_ratio = 1.0

        if breakeven_ratio < 0.70:
            score += 1
            pct = int(breakeven_ratio * 100)
            reasons.append(
                f"損益分岐点がリース期間の{pct}%時点であり、"
                f"早期に利益転換が見込めます（{profit_month}ヶ月目/{lease_term}ヶ月）"
            )
        elif breakeven_ratio <= 0.90:
            reasons.append(
                f"損益分岐点はリース期間の{int(breakeven_ratio * 100)}%時点です"
                f"（{profit_month}ヶ月目/{lease_term}ヶ月）"
            )
        else:
            score -= 1
            reasons.append(
                f"損益分岐点がリース期間の{int(breakeven_ratio * 100)}%と遅く、"
                f"利益転換までの期間が長い点にご注意ください"
                f"（{profit_month}ヶ月目/{lease_term}ヶ月）"
            )

        # ---- 2. Effective yield ----
        effective_yield = lease.effective_yield_rate

        if effective_yield >= 0.06:
            score += 1
            reasons.append(
                f"実効利回りが{effective_yield:.1%}と良好な水準です"
            )
        elif effective_yield >= 0.04:
            reasons.append(
                f"実効利回りは{effective_yield:.1%}で許容範囲内です"
            )
        else:
            score -= 1
            reasons.append(
                f"実効利回りが{effective_yield:.1%}と低く、"
                f"収益性の確保が困難な可能性があります"
            )

        # ---- 3. Residual rate ----
        acq_price = acquisition.recommended_price
        residual_value = residual.base_residual_value
        if acq_price > 0:
            residual_rate = residual_value / acq_price
        else:
            residual_rate = 0.0

        if 0.05 <= residual_rate <= 0.50:
            score += 1
            reasons.append(
                f"残価率{residual_rate:.1%}は妥当な範囲内です"
            )
        elif residual_rate > 0.50:
            score -= 1
            reasons.append(
                f"残価率{residual_rate:.1%}が高く、"
                f"エグジット時の価格下落リスクにご注意ください"
            )
        else:
            reasons.append(
                f"残価率{residual_rate:.1%}は低めですが、"
                f"残価リスクは限定的です"
            )

        # ---- 4. Market data confidence ----
        sample_count = acquisition.sample_count

        if sample_count >= 10:
            score += 1
            reasons.append(
                f"市場データ{sample_count}件に基づく高信頼度の価格算出です"
            )
        elif sample_count >= 5:
            reasons.append(
                f"市場データ{sample_count}件を使用しています"
            )
        else:
            score -= 1
            reasons.append(
                f"市場データが{sample_count}件と少なく、"
                f"価格精度が低い可能性があります"
            )

        # ---- 5. Termination recovery ----
        if nav_curve:
            final_termination = nav_curve[-1].termination_value
            if final_termination > 0:
                score += 1
                reasons.append(
                    f"リース満了時の清算価値が"
                    f"{final_termination:,}円のプラスとなります"
                )
            else:
                score -= 1
                reasons.append(
                    f"リース満了時の清算価値が"
                    f"{final_termination:,}円のマイナスとなる見込みです"
                )

        # ---- Final assessment ----
        if score >= 3:
            assessment: Literal["推奨", "要検討", "非推奨"] = "推奨"
        elif score >= 1:
            assessment = "要検討"
        else:
            assessment = "非推奨"

        return assessment, reasons
