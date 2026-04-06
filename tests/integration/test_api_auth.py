"""Integration tests for the authentication API endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.conftest import (
    ADMIN_EMAIL,
    ADMIN_USER_ID,
    _make_mock_supabase,
    _make_jwt,
)


class TestLoginSuccess:
    """POST /auth/login with valid credentials."""

    async def test_login_success(self) -> None:
        """Valid email/password should set cookies and redirect to /dashboard."""
        from app.main import create_app

        mock_sb = _make_mock_supabase()
        app = create_app()

        with patch("app.api.auth.get_supabase_client", return_value=mock_sb):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as ac:
                response = await ac.post(
                    "/auth/login",
                    data={"email": ADMIN_EMAIL, "password": "correct-password"},
                )

        # Should redirect to /dashboard
        assert response.status_code == 302
        assert "/dashboard" in response.headers.get("location", "")
        # Should set auth cookies
        cookies = response.headers.get_list("set-cookie")
        cookie_text = " ".join(cookies)
        assert "access_token" in cookie_text
        assert "refresh_token" in cookie_text

    async def test_login_success_htmx(self) -> None:
        """HTMX login should return 200 with HX-Redirect header."""
        from app.main import create_app

        mock_sb = _make_mock_supabase()
        app = create_app()

        with patch("app.api.auth.get_supabase_client", return_value=mock_sb):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as ac:
                response = await ac.post(
                    "/auth/login",
                    data={"email": ADMIN_EMAIL, "password": "correct-password"},
                    headers={"HX-Request": "true"},
                )

        assert response.status_code == 200
        assert response.headers.get("hx-redirect") == "/dashboard"


class TestLoginFailure:
    """POST /auth/login with invalid credentials."""

    async def test_login_failure(self) -> None:
        """Invalid password should return an error response."""
        from app.main import create_app

        mock_sb = MagicMock()
        mock_sb.auth.sign_in_with_password.side_effect = Exception("Invalid credentials")
        app = create_app()

        with patch("app.api.auth.get_supabase_client", return_value=mock_sb):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as ac:
                response = await ac.post(
                    "/auth/login",
                    data={"email": "user@example.com", "password": "wrong-password"},
                )

        # Non-HTMX: should redirect back to login with error
        assert response.status_code == 302
        location = response.headers.get("location", "")
        assert "/login" in location
        assert "error" in location

    async def test_login_failure_htmx(self) -> None:
        """HTMX login failure should return HTML error div."""
        from app.main import create_app

        mock_sb = MagicMock()
        mock_sb.auth.sign_in_with_password.side_effect = Exception("Invalid credentials")
        app = create_app()

        with patch("app.api.auth.get_supabase_client", return_value=mock_sb):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as ac:
                response = await ac.post(
                    "/auth/login",
                    data={"email": "user@example.com", "password": "wrong-password"},
                    headers={"HX-Request": "true"},
                )

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "login-error" in response.text
        assert "Invalid" in response.text or "invalid" in response.text.lower()


class TestLogout:
    """POST /auth/logout"""

    async def test_logout(self) -> None:
        """Logout should clear cookies and redirect to /login."""
        from app.main import create_app

        mock_sb = MagicMock()
        mock_sb.auth.sign_out.return_value = None
        app = create_app()

        with patch("app.api.auth.get_supabase_client", return_value=mock_sb):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as ac:
                response = await ac.post("/auth/logout")

        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")
        # Cookies should be cleared (max-age=0 or expires in the past)
        cookies = response.headers.get_list("set-cookie")
        cookie_text = " ".join(cookies)
        assert "access_token" in cookie_text

    async def test_logout_htmx(self) -> None:
        """HTMX logout should return 200 with HX-Redirect."""
        from app.main import create_app

        mock_sb = MagicMock()
        mock_sb.auth.sign_out.return_value = None
        app = create_app()

        with patch("app.api.auth.get_supabase_client", return_value=mock_sb):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as ac:
                response = await ac.post(
                    "/auth/logout",
                    headers={"HX-Request": "true"},
                )

        assert response.status_code == 200
        assert response.headers.get("hx-redirect") == "/login"


class TestProtectedEndpoint:
    """Unauthenticated access to protected endpoints."""

    async def test_protected_endpoint_without_auth(
        self,
        client_unauthenticated: AsyncClient,
    ) -> None:
        """Accessing /dashboard without auth should return 401."""
        response = await client_unauthenticated.get("/dashboard")
        assert response.status_code == 401

    async def test_auth_me_without_token(
        self,
        client_unauthenticated: AsyncClient,
    ) -> None:
        """GET /auth/me without token should return 401."""
        response = await client_unauthenticated.get("/auth/me")
        assert response.status_code == 401

    async def test_auth_me_with_valid_token(
        self,
        client: AsyncClient,
    ) -> None:
        """GET /auth/me with valid token should return user info."""
        response = await client.get("/auth/me")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == ADMIN_USER_ID
        assert body["email"] == ADMIN_EMAIL
        assert body["role"] == "admin"
