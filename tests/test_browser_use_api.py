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
        session = bu_api.create_browser_session(proxy_country_code="es")
    assert seen == ["POST /api/v3/browsers"]
    assert session.browser_id == "11111111-1111-1111-1111-111111111111"
    assert session.cdp_url == "wss://abc.cdp1.browser-use.com"
    assert session.live_url == "https://live.browser-use.com?wss=encoded"


def test_stop_browser_session_posts_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_USE_API_KEY", "bu_test")
    bid = "22222222-2222-2222-2222-222222222222"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith(f"/browsers/{bid}/stop")
        return httpx.Response(200, json={"id": bid, "status": "stopped"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(bu_api.httpx, "post", client.post)
        bu_api.stop_browser_session(bid)
