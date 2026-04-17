"""NAV curve generator and profit conversion analyzer.

Produces month-by-month NAV (Net Asset Value) curves for commercial-vehicle
leaseback deals and identifies critical conversion points such as:

* **Profit conversion month** -- when cumulative profit first turns positive.
* **Termination break-even month** -- when early-exit recovery exceeds zero.
* **Scenario curves** -- Bull / Base / Bear residual-value variants.

All monetary values are **integers in JPY** (no sub-yen fractions).
"""

from __future__ import annotations

import math

import structlog

from app.models.pricing import NAVPoint

logger = structlog.get_logger()


class NAVCalculator:
    """Generates NAV curves and analyzes profit conversion points.

    The NAV curve tracks month-by-month:

    - **Asset book value** -- declining via straight-line depreciation from
      acquisition price to residual value over the lease term.
    - **Cumulative lease income** -- total sub-lease fees received to date.
    - **Cumulative costs** -- financing (investor dividend), AM fee,
      placement fee amortisation, accounting fee, and operator margin.
    - **Cumulative profit** -- income minus costs (excluding depreciation,
      which is a non-cash charge already reflected in book value).
    - **NAV** -- book value of the asset *plus* the net cash position
      (cumulative income minus cumulative costs).  This represents the
      total economic value of the leasing position.
    - **Termination value** -- what you would actually recover if you
      liquidated the position today: forced-sale proceeds of the truck
      plus net cash already in hand minus the outstanding acquisition
      cost still to be recovered.
    """

    # Forced / early-sale discount -- trucks sold outside of normal
    # auction timing typically fetch ~85 % of book value.
    FORCED_SALE_DISCOUNT: float = 0.85

    # -------------------------------------------------------------- #
    #  Primary curve generation
    # -------------------------------------------------------------- #

    def generate_nav_curve(
        self,
        acquisition_price: int,
        residual_value: int,
        monthly_lease_fee: int,
        lease_term_months: int,
        monthly_costs: dict[str, int],
    ) -> list[NAVPoint]:
        """Generate the complete NAV curve for one lease deal.

        Parameters
        ----------
        acquisition_price:
            Vehicle purchase price (JPY).
        residual_value:
            Expected residual value at the end of the lease (JPY).
        monthly_lease_fee:
            Monthly sub-lease fee charged to the operator (JPY).
        lease_term_months:
            Duration of the lease in months (e.g. 36, 48, 60).
        monthly_costs:
            Dict of monthly cost components, typically containing keys
            ``investor``, ``am``, ``placement``, ``accounting``, and
            ``margin``.  All values in JPY.

        Returns
        -------
        list[NAVPoint]
            One entry per month from month 1 to ``lease_term_months``.
        """
        if lease_term_months <= 0:
            logger.warning(
                "nav_curve.invalid_term",
                lease_term_months=lease_term_months,
            )
            return []

        # Straight-line monthly depreciation (precise float, rounded per-month)
        depreciable_amount = acquisition_price - residual_value
        monthly_depreciation = depreciable_amount / lease_term_months

        total_monthly_cost = sum(monthly_costs.values())

        points: list[NAVPoint] = []
        cumulative_income = 0
        cumulative_costs = 0

        for month in range(1, lease_term_months + 1):
            # ---- asset book value (straight-line) ----
            # Use math.ceil on the remaining value to avoid sub-yen rounding
            # that would make the final month's book value != residual_value.
            book_value = acquisition_price - int(
                math.floor(monthly_depreciation * month + 0.5)
            )
            # Clamp so book value never drops below residual
            book_value = max(book_value, residual_value)

            # ---- cumulative income & costs ----
            cumulative_income += monthly_lease_fee
            cumulative_costs += total_monthly_cost

            # ---- cumulative profit ----
            # Profit tracks the *cash-flow* perspective: income received
            # minus cash costs paid.  Depreciation is a non-cash charge
            # and is NOT deducted here -- it is already captured in the
            # declining book_value.
            cumulative_profit = cumulative_income - cumulative_costs

            # ---- NAV ----
            # Economic value of the position = remaining asset value +
            # net cash accumulated.
            nav = book_value + cumulative_profit

            # ---- termination (early exit) value ----
            # If we liquidated now we would:
            #   + receive forced-sale proceeds for the truck
            #   + keep the net cash already received (income - costs)
            #   - but we already spent `acquisition_price` to buy the truck
            #
            # termination_value
            #   = forced_sale_proceeds + cumulative_income
            #     - acquisition_price - cumulative_costs
            #
            # where forced_sale_proceeds = book_value * FORCED_SALE_DISCOUNT
            forced_sale_proceeds = int(
                math.floor(book_value * self.FORCED_SALE_DISCOUNT + 0.5)
            )
            termination_value = (
                forced_sale_proceeds
                + cumulative_income
                - acquisition_price
                - cumulative_costs
            )

            points.append(
                NAVPoint(
                    month=month,
                    asset_book_value=book_value,
                    cumulative_lease_income=cumulative_income,
                    cumulative_costs=cumulative_costs,
                    cumulative_profit=cumulative_profit,
                    nav=nav,
                    termination_value=termination_value,
                )
            )

        logger.info(
            "nav_curve.generated",
            acquisition_price=acquisition_price,
            residual_value=residual_value,
            lease_term_months=lease_term_months,
            final_nav=points[-1].nav,
            final_termination_value=points[-1].termination_value,
        )

        return points

    # -------------------------------------------------------------- #
    #  Conversion-point analysis
    # -------------------------------------------------------------- #

    def find_profit_conversion_month(
        self, nav_curve: list[NAVPoint]
    ) -> int | None:
        """Return the first month where cumulative profit turns positive.

        Returns ``None`` if profit never turns positive within the curve.
        """
        for point in nav_curve:
            if point.cumulative_profit > 0:
                return point.month
        return None

    def find_termination_breakeven_month(
        self, nav_curve: list[NAVPoint]
    ) -> int | None:
        """Return the first month where termination value exceeds zero.

        This is the earliest point at which the deal can be exited
        without a loss (accounting for forced-sale discount).

        Returns ``None`` if termination value never turns positive.
        """
        for point in nav_curve:
            if point.termination_value > 0:
                return point.month
        return None

    # -------------------------------------------------------------- #
    #  Scenario analysis
    # -------------------------------------------------------------- #

    def generate_scenario_curves(
        self,
        acquisition_price: int,
        residual_scenarios: dict[str, int],
        monthly_lease_fee: int,
        lease_term_months: int,
        monthly_costs: dict[str, int],
    ) -> dict[str, list[NAVPoint]]:
        """Generate NAV curves for multiple residual-value scenarios.

        Parameters
        ----------
        residual_scenarios:
            Mapping of scenario label to residual value, e.g.
            ``{"bull": 1_200_000, "base": 1_000_000, "bear": 800_000}``.

        Returns
        -------
        dict[str, list[NAVPoint]]
            One NAV curve per scenario.
        """
        curves: dict[str, list[NAVPoint]] = {}
        for scenario, residual in residual_scenarios.items():
            curves[scenario] = self.generate_nav_curve(
                acquisition_price=acquisition_price,
                residual_value=residual,
                monthly_lease_fee=monthly_lease_fee,
                lease_term_months=lease_term_months,
                monthly_costs=monthly_costs,
            )
        return curves

    # -------------------------------------------------------------- #
    #  Summary helpers
    # -------------------------------------------------------------- #

    def summarise_curve(self, nav_curve: list[NAVPoint]) -> dict:
        """Return a compact summary dict suitable for API responses.

        Keys: ``profit_conversion_month``, ``termination_breakeven_month``,
        ``final_nav``, ``final_termination_value``, ``total_profit``,
        ``total_income``, ``total_costs``, ``term_months``.
        """
        if not nav_curve:
            return {}

        last = nav_curve[-1]
        return {
            "profit_conversion_month": self.find_profit_conversion_month(
                nav_curve
            ),
            "termination_breakeven_month": (
                self.find_termination_breakeven_month(nav_curve)
            ),
            "final_nav": last.nav,
            "final_termination_value": last.termination_value,
            "total_profit": last.cumulative_profit,
            "total_income": last.cumulative_lease_income,
            "total_costs": last.cumulative_costs,
            "term_months": last.month,
        }
