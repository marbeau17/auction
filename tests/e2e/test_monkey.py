"""Monkey testing - random input fuzzing for robustness.

These tests send random, malformed, and adversarial inputs to API endpoints
to verify that the server never crashes with 5xx errors. 4xx responses
(validation errors, auth failures) are acceptable.
"""

from __future__ import annotations

import random
import string
from typing import Any

import pytest
from httpx import AsyncClient


def _random_string(length: int = 10) -> str:
    """Generate a random ASCII string."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@pytest.mark.monkey
class TestMonkeySimulation:
    """Fuzz the simulation endpoint with random/extreme inputs."""

    @pytest.mark.parametrize("run", range(50))
    async def test_random_simulation_input(
        self,
        client: AsyncClient,
        run: int,
    ) -> None:
        """Send random simulation inputs - should never crash (4xx ok, 5xx not ok)."""
        data = self._generate_random_input()
        response = await client.post("/api/v1/simulations/calculate", json=data)
        # If endpoint not implemented, 404/405 is fine
        assert response.status_code < 500, (
            f"Server error {response.status_code} with input: {data}"
        )

    def _generate_random_input(self) -> dict[str, Any]:
        return {
            "maker": random.choice(
                ["日野", "いすゞ", "三菱ふそう", "", "INVALID", None, "x" * 1000]
            ),
            "model": random.choice(["プロフィア", "", "a" * 500, None]),
            "registration_year_month": random.choice(
                ["2020-01", "invalid", "9999-99", "", "1800-01"]
            ),
            "mileage_km": random.choice([0, -1, 100000, 99999999, 0.5, None, "abc"]),
            "acquisition_price": random.choice(
                [0, -100, 5000000, 999999999999, None]
            ),
            "book_value": random.choice([0, 1000000, -1, None]),
            "vehicle_class": random.choice(["大型", "小型", "", "INVALID", None]),
            "body_type": random.choice(
                ["ウイング", "ダンプ", "", None, "x" * 100]
            ),
            "target_yield_rate": random.choice([0, -5, 5.0, 100, 0.001, None]),
            "lease_term_months": random.choice([0, -12, 12, 36, 60, 999, None]),
        }


@pytest.mark.monkey
class TestMonkeyMarketSearch:
    """Fuzz market price search with random parameters."""

    @pytest.mark.parametrize("run", range(20))
    async def test_random_market_search(
        self,
        client: AsyncClient,
        run: int,
    ) -> None:
        """Fuzz market price search with random parameters."""
        params: dict[str, Any] = {
            "maker": random.choice(["日野", "", "x" * 500]),
            "year_from": random.choice([None, 1900, 2020, 9999, -1]),
            "year_to": random.choice([None, 2025, 0]),
            "price_from": random.choice([None, 0, -100, 99999999]),
            "page": random.choice([0, 1, -1, 99999]),
            "per_page": random.choice([0, 1, 20, 10000]),
        }
        params = {k: v for k, v in params.items() if v is not None}
        response = await client.get("/api/v1/market-prices/", params=params)
        assert response.status_code < 500, (
            f"Server error {response.status_code} with params: {params}"
        )


@pytest.mark.monkey
class TestMonkeyInjection:
    """Test with SQL injection and XSS payloads."""

    PAYLOADS = [
        "'; DROP TABLE vehicles; --",
        "<script>alert('xss')</script>",
        "{{7*7}}",
        "${7*7}",
        "../../../etc/passwd",
        "\x00\x01\x02",
        "a" * 10000,
        "日本語テスト" * 100,
        "Robert'); DROP TABLE students;--",
        '{"$gt": ""}',
        "%00%0d%0a",
        "UNION SELECT * FROM users--",
    ]

    @pytest.mark.parametrize("run", range(20))
    async def test_random_strings_injection(
        self,
        client: AsyncClient,
        run: int,
    ) -> None:
        """Test with SQL injection and XSS payloads - should never crash."""
        data: dict[str, Any] = {
            "maker": random.choice(self.PAYLOADS),
            "model": random.choice(self.PAYLOADS),
            "registration_year_month": "2020-01",
            "mileage_km": 100000,
            "acquisition_price": 5000000,
            "book_value": 3000000,
            "vehicle_class": "大型",
            "body_type": "ウイング",
            "target_yield_rate": 0.08,
            "lease_term_months": 36,
        }
        response = await client.post("/api/v1/simulations/calculate", json=data)
        assert response.status_code < 500, (
            f"Server error {response.status_code} with payload"
        )
        # XSS check: if we got a successful response, ensure no script tags reflected
        if response.status_code == 200:
            body = response.text
            assert "<script>" not in body, "Possible XSS reflection detected"

    @pytest.mark.parametrize("run", range(10))
    async def test_injection_in_search_params(
        self,
        client: AsyncClient,
        run: int,
    ) -> None:
        """Injection payloads in search params should not cause server errors."""
        payload = random.choice(self.PAYLOADS)
        response = await client.get(
            "/api/v1/market-prices/",
            params={"maker": payload},
        )
        assert response.status_code < 500, (
            f"Server error {response.status_code} with payload: {payload!r}"
        )

    @pytest.mark.parametrize("run", range(10))
    async def test_injection_in_statistics(
        self,
        client: AsyncClient,
        run: int,
    ) -> None:
        """Injection payloads in statistics endpoint should not cause errors."""
        payload = random.choice(self.PAYLOADS)
        response = await client.get(
            "/api/v1/market-prices/statistics",
            params={"maker": payload},
        )
        assert response.status_code < 500


@pytest.mark.monkey
class TestMonkeyEdgeCases:
    """Test edge cases and boundary values."""

    async def test_empty_json_body(self, client: AsyncClient) -> None:
        """POST with empty JSON body should return 4xx, not 5xx."""
        response = await client.post(
            "/api/v1/simulations/calculate",
            json={},
        )
        assert response.status_code < 500

    async def test_non_json_body(self, client: AsyncClient) -> None:
        """POST with non-JSON body should return 4xx, not 5xx."""
        response = await client.post(
            "/api/v1/simulations/calculate",
            content=b"this is not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code < 500

    async def test_extremely_large_page_number(
        self,
        client: AsyncClient,
    ) -> None:
        """Extremely large page number should not crash."""
        response = await client.get(
            "/api/v1/market-prices/",
            params={"page": 999999999},
        )
        assert response.status_code < 500

    async def test_negative_price_filter(self, client: AsyncClient) -> None:
        """Negative price filter should be rejected gracefully."""
        response = await client.get(
            "/api/v1/market-prices/",
            params={"price_from": -1},
        )
        assert response.status_code < 500

    async def test_unicode_overflow_in_maker(
        self,
        client: AsyncClient,
    ) -> None:
        """Very long Unicode string should not crash the server."""
        response = await client.get(
            "/api/v1/market-prices/",
            params={"maker": "あ" * 5000},
        )
        assert response.status_code < 500

    async def test_null_bytes_in_query(self, client: AsyncClient) -> None:
        """Null bytes in query params should be handled safely."""
        response = await client.get(
            "/api/v1/market-prices/",
            params={"maker": "test\x00value"},
        )
        assert response.status_code < 500

    async def test_duplicate_query_params(self, client: AsyncClient) -> None:
        """Duplicate query parameters should not crash."""
        response = await client.get(
            "/api/v1/market-prices/?maker=日野&maker=いすゞ",
        )
        assert response.status_code < 500

    async def test_invalid_uuid_in_path(self, client: AsyncClient) -> None:
        """Invalid UUID in path should return 422, not 5xx."""
        response = await client.get("/api/v1/market-prices/not-a-uuid")
        assert response.status_code < 500
        assert response.status_code == 422

    async def test_health_always_works(self, client: AsyncClient) -> None:
        """Health endpoint should always return 200."""
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
