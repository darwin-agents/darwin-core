from __future__ import annotations

import httpx
import pytest

from darwin_core.agents.web.browser import browser_connect as bc


def test_live_url_from_cdp_ws_encodes_wss_param() -> None:
    cdp = "wss://connect.browser-use.com?apiKey=secret&proxyCountryCode=es"
    live = bc.live_url_from_cdp_ws(cdp)
    assert live.startswith("https://live.browser-use.com?wss=")
    assert "apiKey%3Dsecret" in live or "apiKey=secret" in live


def test_request_browser_connect_parses_session_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/browser/connect")
        return httpx.Response(
            200,
            json={
                "browser_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "cdp_ws_url": "wss://xyz.cdp1.browser-use.com",
                "live_url": "https://live.browser-use.com?wss=xyz",
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(bc.httpx, "post", client.post)
        info = bc.request_browser_connect("http://localhost:8000")
    assert info.browser_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert info.cdp_ws_url == "wss://xyz.cdp1.browser-use.com"
    assert info.live_url == "https://live.browser-use.com?wss=xyz"
