"""Market data analysis for pricing support.

Provides statistical analysis of auction/retail price data, trend
detection, outlier filtering, comparable vehicle search, and histogram
generation for Chart.js front-end visualisation.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np


class MarketAnalyzer:
    """Analyzes market data to support pricing decisions."""

    # ------------------------------------------------------------------ #
    # Statistical summary
    # ------------------------------------------------------------------ #

    def calculate_statistics(self, prices: list[float]) -> dict[str, Any]:
        """Calculate statistical summary of price data.

        Parameters
        ----------
        prices:
            List of numeric prices.

        Returns
        -------
        dict
            Keys: count, mean, median, min, max, std, q25, q75, iqr.
            Returns zeroed dict when *prices* is empty.
        """
        empty: dict[str, Any] = {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
            "std": 0.0,
            "q25": 0.0,
            "q75": 0.0,
            "iqr": 0.0,
        }
        if not prices:
            return empty

        arr = np.array(prices, dtype=np.float64)
        # Filter out NaN / inf
        arr = arr[np.isfinite(arr)]
        if len(arr) == 0:
            return empty

        q25 = float(np.percentile(arr, 25))
        q75 = float(np.percentile(arr, 75))

        return {
            "count": int(len(arr)),
            "mean": round(float(np.mean(arr)), 2),
            "median": round(float(np.median(arr)), 2),
            "min": round(float(np.min(arr)), 2),
            "max": round(float(np.max(arr)), 2),
            "std": round(float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0, 2),
            "q25": round(q25, 2),
            "q75": round(q75, 2),
            "iqr": round(q75 - q25, 2),
        }

    # ------------------------------------------------------------------ #
    # Outlier detection
    # ------------------------------------------------------------------ #

    def detect_outliers(
        self,
        prices: list[float],
        method: str = "iqr",
        factor: float = 3.0,
    ) -> list[int]:
        """Detect outlier indices using the IQR method.

        Parameters
        ----------
        prices:
            Price list.
        method:
            Detection method. Currently only ``"iqr"`` is supported.
        factor:
            Multiplier for IQR to set fence distance.  A value of 1.5 is
            the classic Tukey fence; 3.0 (default) is more conservative
            and suitable for auction data with naturally wide spreads.

        Returns
        -------
        list[int]
            Indices of outlier elements in the original *prices* list.
        """
        if not prices or len(prices) < 4:
            return []

        arr = np.array(prices, dtype=np.float64)
        q25 = float(np.percentile(arr, 25))
        q75 = float(np.percentile(arr, 75))
        iqr = q75 - q25

        if iqr == 0:
            return []

        lower_fence = q25 - factor * iqr
        upper_fence = q75 + factor * iqr

        return [
            int(i)
            for i, p in enumerate(prices)
            if not math.isfinite(p) or p < lower_fence or p > upper_fence
        ]

    # ------------------------------------------------------------------ #
    # Trend calculation
    # ------------------------------------------------------------------ #

    def calculate_trend(
        self,
        price_history: list[dict[str, Any]],
        recent_days: int = 30,
        baseline_days: int = 180,
    ) -> dict[str, Any]:
        """Calculate price trend from historical data.

        Parameters
        ----------
        price_history:
            List of dicts each containing ``date`` (str ISO or datetime)
            and ``price`` (float).
        recent_days:
            Window for the "recent" average.
        baseline_days:
            Window for the "baseline" average.

        Returns
        -------
        dict
            trend_factor, recent_avg, baseline_avg, direction
        """
        neutral: dict[str, Any] = {
            "trend_factor": 1.0,
            "recent_avg": 0.0,
            "baseline_avg": 0.0,
            "direction": "stable",
        }

        if not price_history:
            return neutral

        # Parse dates
        now = datetime.utcnow()
        recent_cutoff = now - timedelta(days=recent_days)
        baseline_cutoff = now - timedelta(days=baseline_days)

        recent_prices: list[float] = []
        baseline_prices: list[float] = []

        for entry in price_history:
            raw_date = entry.get("date")
            price = entry.get("price")
            if raw_date is None or price is None:
                continue
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue

            if isinstance(raw_date, str):
                try:
                    dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    dt = dt.replace(tzinfo=None)
                except ValueError:
                    continue
            elif isinstance(raw_date, datetime):
                dt = raw_date.replace(tzinfo=None)
            else:
                continue

            if dt >= recent_cutoff:
                recent_prices.append(price)
            if dt >= baseline_cutoff:
                baseline_prices.append(price)

        if not recent_prices or not baseline_prices:
            return neutral

        recent_avg = float(np.mean(recent_prices))
        baseline_avg = float(np.mean(baseline_prices))

        if baseline_avg <= 0:
            return neutral

        trend_factor = recent_avg / baseline_avg

        if trend_factor > 1.03:
            direction = "up"
        elif trend_factor < 0.97:
            direction = "down"
        else:
            direction = "stable"

        return {
            "trend_factor": round(trend_factor, 4),
            "recent_avg": round(recent_avg, 2),
            "baseline_avg": round(baseline_avg, 2),
            "direction": direction,
        }

    # ------------------------------------------------------------------ #
    # Volatility
    # ------------------------------------------------------------------ #

    def calculate_volatility(self, prices: list[float]) -> float:
        """Calculate coefficient of variation as a volatility measure.

        Parameters
        ----------
        prices:
            List of prices.

        Returns
        -------
        float
            CV (std / mean).  Returns 0.0 for empty or constant data.
        """
        if not prices or len(prices) < 2:
            return 0.0

        arr = np.array(prices, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if len(arr) < 2:
            return 0.0

        mean = float(np.mean(arr))
        if mean == 0:
            return 0.0

        std = float(np.std(arr, ddof=1))
        return round(abs(std / mean), 4)

    # ------------------------------------------------------------------ #
    # Comparable vehicles
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fuzzy_match_score(a: str, b: str) -> float:
        """Simple fuzzy string similarity (Jaccard on character bigrams)."""
        if not a or not b:
            return 0.0
        a_lower = a.lower()
        b_lower = b.lower()
        if a_lower == b_lower:
            return 1.0

        def _bigrams(s: str) -> set[str]:
            return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

        bg_a = _bigrams(a_lower)
        bg_b = _bigrams(b_lower)
        intersection = bg_a & bg_b
        union = bg_a | bg_b
        if not union:
            return 0.0
        return len(intersection) / len(union)

    def find_comparable_vehicles(
        self,
        target: dict[str, Any],
        vehicles: list[dict[str, Any]],
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Find similar vehicles for price comparison.

        Parameters
        ----------
        target:
            Dict describing the subject vehicle.  Expected keys:
            ``maker``, ``model``, ``year``, ``mileage``, ``body_type``.
        vehicles:
            Candidate pool -- list of dicts with the same keys plus
            ``price``.
        max_results:
            Maximum number of results to return.

        Returns
        -------
        list[dict]
            Matching vehicles sorted by descending similarity, each
            augmented with a ``similarity_score`` key.
        """
        if not vehicles:
            return []

        t_maker = str(target.get("maker", ""))
        t_model = str(target.get("model", ""))
        t_year = target.get("year", 0)
        t_mileage = target.get("mileage", 0)
        t_body = str(target.get("body_type", ""))

        try:
            t_year = int(t_year)
        except (TypeError, ValueError):
            t_year = 0
        try:
            t_mileage = int(t_mileage)
        except (TypeError, ValueError):
            t_mileage = 0

        scored: list[tuple[float, dict[str, Any]]] = []

        for v in vehicles:
            score = 0.0

            # Maker -- exact match (weight 20)
            v_maker = str(v.get("maker", ""))
            if v_maker and v_maker == t_maker:
                score += 20.0
            elif v_maker:
                continue  # different maker = not comparable

            # Model -- fuzzy match (weight 30)
            v_model = str(v.get("model", ""))
            model_sim = self._fuzzy_match_score(t_model, v_model)
            if model_sim < 0.3:
                continue  # too dissimilar
            score += 30.0 * model_sim

            # Year -- within ±2 (weight 20)
            try:
                v_year = int(v.get("year", 0))
            except (TypeError, ValueError):
                v_year = 0
            year_diff = abs(t_year - v_year)
            if year_diff > 2:
                continue
            score += 20.0 * (1.0 - year_diff / 3.0)

            # Mileage -- within ±30% (weight 20)
            try:
                v_mileage = int(v.get("mileage", 0))
            except (TypeError, ValueError):
                v_mileage = 0
            if t_mileage > 0:
                mileage_ratio = abs(v_mileage - t_mileage) / t_mileage
                if mileage_ratio > 0.30:
                    continue
                score += 20.0 * (1.0 - mileage_ratio / 0.30)
            else:
                score += 10.0  # no target mileage -- partial credit

            # Body type -- exact match (weight 10)
            v_body = str(v.get("body_type", ""))
            if v_body and v_body == t_body:
                score += 10.0

            result = dict(v)
            result["similarity_score"] = round(score, 2)
            scored.append((score, result))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:max_results]]

    # ------------------------------------------------------------------ #
    # Deviation rate
    # ------------------------------------------------------------------ #

    def calculate_deviation_rate(
        self, auction_price: float, retail_price: float
    ) -> float:
        """Calculate price deviation between auction and retail.

        Parameters
        ----------
        auction_price:
            Price achieved at auction.
        retail_price:
            Retail / asking price.

        Returns
        -------
        float
            Deviation as a ratio ``(retail - auction) / retail``.
            Returns 0.0 when retail_price is zero.
        """
        if retail_price == 0:
            return 0.0
        return round((retail_price - auction_price) / retail_price, 4)

    # ------------------------------------------------------------------ #
    # Price distribution histogram
    # ------------------------------------------------------------------ #

    def generate_price_distribution(
        self, prices: list[float], bins: int = 10
    ) -> dict[str, Any]:
        """Generate price distribution histogram data for Chart.js.

        Parameters
        ----------
        prices:
            List of prices.
        bins:
            Number of histogram bins.

        Returns
        -------
        dict
            ``labels`` -- list of human-readable bin-range strings.
            ``values`` -- list of counts per bin.
        """
        empty: dict[str, Any] = {"labels": [], "values": []}

        if not prices:
            return empty

        arr = np.array(prices, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if len(arr) == 0:
            return empty

        bins = max(bins, 1)

        counts, bin_edges = np.histogram(arr, bins=bins)

        labels: list[str] = []
        for i in range(len(counts)):
            low = int(round(bin_edges[i]))
            high = int(round(bin_edges[i + 1]))
            # Format large numbers in 万円 if >= 10,000
            if high >= 10_000:
                low_label = f"{low // 10_000}万"
                high_label = f"{high // 10_000}万"
                labels.append(f"{low_label}-{high_label}")
            else:
                labels.append(f"{low}-{high}")

        values = [int(c) for c in counts]

        return {"labels": labels, "values": values}
