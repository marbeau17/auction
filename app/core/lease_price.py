"""Step 3: Calculate appropriate lease price incorporating all stakeholder yields.

The sub-lease fee is composed of six cost components that together ensure
all stakeholders (investor, AM company, operator, accountant) are
compensated while the asset is depreciated over the lease term.

All monetary results are rounded **up** (``math.ceil``) so that fee
shortfalls are never carried by the platform.
"""

from __future__ import annotations

import math

import structlog

from app.models.pricing import LeaseFeeBreakdown, LeasePriceResult

logger = structlog.get_logger()

TAX_RATE = 0.10  # 消費税 10 %


class LeasePriceCalculator:
    """Step 3: Calculate monthly sub-lease fee.

    The lease fee must cover:

    1. **Depreciation** – straight-line recovery of
       ``(acquisition_price - residual_value)`` over the lease term.
    2. **Investor dividend** – annual yield on the full acquisition price,
       prorated monthly (÷ 12).
    3. **AM fee** – annual asset-management fee on the acquisition price,
       prorated monthly (÷ 12).
    4. **Placement fee** – one-time placement fee amortised evenly over
       the lease term.
    5. **Accounting fee** – a fixed monthly amount.
    6. **Operator margin** – margin on the depreciation base, amortised
       over the lease term.
    """

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def calculate(
        self,
        acquisition_price: int,
        residual_value: int,
        lease_term_months: int,
        investor_yield_rate: float = 0.08,
        am_fee_rate: float = 0.02,
        placement_fee_rate: float = 0.03,
        accounting_fee_monthly: int = 50_000,
        operator_margin_rate: float = 0.02,
    ) -> LeasePriceResult:
        """Calculate the monthly lease fee and full breakdown.

        Parameters
        ----------
        acquisition_price:
            Vehicle purchase price (JPY, tax-exclusive).
        residual_value:
            Projected residual / salvage value at lease end (JPY).
        lease_term_months:
            Lease duration in months (must be >= 1).
        investor_yield_rate:
            Annual investor dividend rate (e.g. 0.08 = 8 %).
        am_fee_rate:
            Annual asset-management fee rate.
        placement_fee_rate:
            One-time placement fee rate, amortised over the lease term.
        accounting_fee_monthly:
            Fixed monthly accounting / bookkeeping fee (JPY).
        operator_margin_rate:
            Operator profit-margin rate on the depreciation base.

        Returns
        -------
        LeasePriceResult
            Fully populated result including breakdown, tax-inclusive fee,
            effective yield, and breakeven month.

        Raises
        ------
        ValueError
            If ``lease_term_months < 1`` or ``acquisition_price <= 0``.
        """
        # --- Validation --------------------------------------------------
        if lease_term_months < 1:
            raise ValueError(
                f"lease_term_months must be >= 1, got {lease_term_months}"
            )
        if acquisition_price <= 0:
            raise ValueError(
                f"acquisition_price must be > 0, got {acquisition_price}"
            )
        if residual_value < 0:
            raise ValueError(
                f"residual_value must be >= 0, got {residual_value}"
            )
        if residual_value >= acquisition_price:
            raise ValueError(
                "residual_value must be less than acquisition_price "
                f"({residual_value} >= {acquisition_price})"
            )

        depreciation_base = acquisition_price - residual_value

        # --- Monthly components (ceil to avoid shortfalls) ----------------
        depreciation_monthly = math.ceil(depreciation_base / lease_term_months)
        investor_monthly = math.ceil(
            acquisition_price * investor_yield_rate / 12
        )
        am_monthly = math.ceil(acquisition_price * am_fee_rate / 12)
        placement_monthly = math.ceil(
            acquisition_price * placement_fee_rate / lease_term_months
        )
        accounting_monthly = accounting_fee_monthly
        margin_monthly = math.ceil(
            depreciation_base * operator_margin_rate / lease_term_months
        )

        total_monthly = (
            depreciation_monthly
            + investor_monthly
            + am_monthly
            + placement_monthly
            + accounting_monthly
            + margin_monthly
        )

        # --- Breakdown model ----------------------------------------------
        breakdown = LeaseFeeBreakdown(
            depreciation_portion=depreciation_monthly,
            investor_dividend_portion=investor_monthly,
            am_fee_portion=am_monthly,
            placement_fee_portion=placement_monthly,
            accounting_fee_portion=accounting_monthly,
            operator_margin_portion=margin_monthly,
            total_monthly_fee=total_monthly,
        )

        # --- Derived totals -----------------------------------------------
        monthly_tax_incl = math.ceil(total_monthly * (1 + TAX_RATE))
        annual_fee = total_monthly * 12
        total_fee = total_monthly * lease_term_months

        # --- Breakeven month ----------------------------------------------
        breakeven = self._calculate_breakeven_month(
            acquisition_price=acquisition_price,
            residual_value=residual_value,
            lease_term_months=lease_term_months,
            monthly_fee=total_monthly,
            depreciation_monthly=depreciation_monthly,
        )

        # --- Effective yield rate -----------------------------------------
        effective_yield = self._calculate_effective_yield(
            acquisition_price=acquisition_price,
            residual_value=residual_value,
            lease_term_months=lease_term_months,
            total_lease_income=total_fee,
        )

        result = LeasePriceResult(
            monthly_lease_fee=total_monthly,
            monthly_lease_fee_tax_incl=monthly_tax_incl,
            annual_lease_fee=annual_fee,
            total_lease_fee=total_fee,
            fee_breakdown=breakdown,
            effective_yield_rate=round(effective_yield, 4),
            breakeven_month=breakeven,
        )

        logger.info(
            "lease_price_calculated",
            acquisition_price=acquisition_price,
            residual_value=residual_value,
            lease_term_months=lease_term_months,
            monthly_fee=total_monthly,
            monthly_fee_tax_incl=monthly_tax_incl,
            effective_yield=round(effective_yield, 4),
            breakeven_month=breakeven,
        )

        return result

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _calculate_breakeven_month(
        acquisition_price: int,
        residual_value: int,
        lease_term_months: int,
        monthly_fee: int,
        depreciation_monthly: int,
    ) -> int | None:
        """Find the first month where cumulative income covers the gap
        between the purchase price and the current asset book value.

        Breakeven at month *m* when::

            cumulative_income(m) >= acquisition_price - asset_value(m)

        where ``asset_value`` depreciates linearly from ``acquisition_price``
        toward ``residual_value``.

        Returns
        -------
        int | None
            1-based month number, or ``None`` if never reached within the
            lease term.
        """
        cumulative_income = 0
        for month in range(1, lease_term_months + 1):
            cumulative_income += monthly_fee
            # Asset value at this month (straight-line depreciation)
            asset_value = acquisition_price - depreciation_monthly * month
            asset_value = max(asset_value, residual_value)
            # Gap = how much we still need to recover
            gap = acquisition_price - asset_value
            if cumulative_income >= gap:
                return month
        return None

    @staticmethod
    def _calculate_effective_yield(
        acquisition_price: int,
        residual_value: int,
        lease_term_months: int,
        total_lease_income: int,
    ) -> float:
        """Calculate the effective annual yield rate for the investor.

        Formula::

            net_profit = total_lease_income + residual_value - acquisition_price
            years      = lease_term_months / 12
            yield      = net_profit / acquisition_price / years

        Returns
        -------
        float
            Annual effective yield rate (e.g. 0.08 for 8 %).
        """
        if acquisition_price <= 0 or lease_term_months <= 0:
            return 0.0

        net_profit = total_lease_income + residual_value - acquisition_price
        years = lease_term_months / 12.0
        return net_profit / acquisition_price / years
