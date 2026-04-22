"""Tests that CSRFMiddleware preserves the request body for downstream handlers.

Covers the regression where `await request.form()` inside the middleware
consumed the ASGI receive stream, causing downstream route handlers to see
an empty body (422 on every form POST).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.middleware.csrf import CSRFMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/prime")
    async def prime() -> dict:
        return {"ok": True}

    @app.post("/api/echo")
    async def echo(request: Request) -> dict:
        form = await request.form()
        return {
            "csrf_token": form.get("csrf_token", ""),
            "payload": form.get("payload", ""),
        }

    return app


async def _prime(ac: AsyncClient) -> str:
    resp = await ac.get("/prime")
    assert resp.status_code == 200
    return resp.cookies.get("csrf_token", "")


@pytest.mark.asyncio
async def test_form_body_preserved_when_csrf_in_header(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        csrf = await _prime(ac)
        resp = await ac.post(
            "/api/echo",
            data={"payload": "hello"},
            headers={"X-CSRF-Token": csrf},
            cookies={"csrf_token": csrf},
        )
    assert resp.status_code == 200
    assert resp.json()["payload"] == "hello"


@pytest.mark.asyncio
async def test_form_body_preserved_when_csrf_in_body(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        csrf = await _prime(ac)
        resp = await ac.post(
            "/api/echo",
            data={"csrf_token": csrf, "payload": "world"},
            cookies={"csrf_token": csrf},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["csrf_token"] == csrf
    assert body["payload"] == "world"


@pytest.mark.asyncio
async def test_missing_csrf_still_rejected(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        csrf = await _prime(ac)
        resp = await ac.post(
            "/api/echo",
            data={"payload": "nope"},
            cookies={"csrf_token": csrf},
        )
    assert resp.status_code == 403
