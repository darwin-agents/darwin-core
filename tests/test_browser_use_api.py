from __future__ import annotations

import json

import httpx
import pytest

from darwin_core.servers.browser_use import api as bu_api


def test_create_browser_session_maps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_USE_API_KEY", "bu_test")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        assert request.method == "POST"
        assert request.url.path.endswith("/browsers")
        body = json.loads(request.content.decode())
        assert body.get("proxyCountryCode") == "es"
        return httpx.Response(
            201,
            json={
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "active",
                "cdpUrl": "wss://abc.cdp1.browser-use.com",
                "liveUrl": "https://live.browser-use.com?wss=encoded",
                "timeoutAt": "2026-01-01T00:00:00Z",
                "startedAt": "2026-01-01T00:00:00Z",
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(bu_api.httpx, "post", client.post)
        session = bu_api.create_browser_session(proxy_country_code="es", _retry_after_release=False)
    assert seen == ["POST /api/v3/browsers"]
    assert session.browser_id == "11111111-1111-1111-1111-111111111111"
    assert session.cdp_url == "wss://abc.cdp1.browser-use.com"
    assert session.live_url == "https://live.browser-use.com?wss=encoded"


def test_stop_browser_session_uses_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_USE_API_KEY", "bu_test")
    bid = "22222222-2222-2222-2222-222222222222"
    seen: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.content))
        assert request.method == "PATCH"
        assert request.url.path.endswith(f"/browsers/{bid}")
        assert json.loads(request.content.decode()) == {"action": "stop"}
        return httpx.Response(200, json={"id": bid, "status": "stopped"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(bu_api.httpx, "patch", client.patch)
        bu_api.stop_browser_session(bid)
    assert len(seen) == 1


def test_create_retries_after_429_when_auto_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_USE_API_KEY", "bu_test")
    monkeypatch.setenv("BROWSER_USE_AUTO_RELEASE_SESSIONS", "1")
    posts = 0

    def post_handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        if posts == 1:
            return httpx.Response(429, json={"detail": "limit"})
        return httpx.Response(
            201,
            json={
                "id": "33333333-3333-3333-3333-333333333333",
                "status": "active",
                "cdpUrl": "wss://x.cdp0.browser-use.com",
                "liveUrl": "https://live.browser-use.com?wss=x",
                "timeoutAt": "2026-01-01T00:00:00Z",
                "startedAt": "2026-01-01T00:00:00Z",
            },
        )

    def get_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "status": "active"}],
                "totalItems": 1,
                "pageNumber": 1,
                "pageSize": 100,
            },
        )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "status": "stopped"})

    def route(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return post_handler(request)
        if request.method == "GET":
            return get_handler(request)
        if request.method == "PATCH":
            return patch_handler(request)
        return httpx.Response(405)

    transport = httpx.MockTransport(route)
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(bu_api.httpx, "post", client.post)
        monkeypatch.setattr(bu_api.httpx, "get", client.get)
        monkeypatch.setattr(bu_api.httpx, "patch", client.patch)
        session = bu_api.create_browser_session(_retry_after_release=True)
    assert posts == 2
    assert session.browser_id == "33333333-3333-3333-3333-333333333333"
