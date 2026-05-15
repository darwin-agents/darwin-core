"""Browser Use Cloud API v3 (standalone browser sessions for Playwright + live view)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

_API_BASE = os.getenv("BROWSER_USE_API_BASE_URL", "https://api.browser-use.com/api/v3").rstrip("/")


@dataclass(frozen=True)
class BrowserSessionCreated:
    """One dedicated cloud browser (shared by Playwright and live.browser-use.com)."""

    browser_id: str
    cdp_url: str
    live_url: str


def _api_key() -> str:
    key = os.getenv("BROWSER_USE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing BROWSER_USE_API_KEY.")
    return key


def _headers() -> dict[str, str]:
    return {"X-Browser-Use-API-Key": _api_key(), "Content-Type": "application/json"}


def create_browser_session(
    *,
    proxy_country_code: str | None = None,
    profile_id: str | None = None,
    timeout_minutes: int | None = None,
    browser_screen_width: int | None = None,
    browser_screen_height: int | None = None,
    timeout: float = 60.0,
) -> BrowserSessionCreated:
    """``POST /browsers`` — session-specific CDP + live URLs (not the generic connect pool)."""
    body: dict[str, Any] = {}
    proxy = proxy_country_code or os.getenv("BROWSER_USE_PROXY_COUNTRY_CODE")
    if proxy and str(proxy).strip():
        body["proxyCountryCode"] = str(proxy).strip().lower()
    prof = profile_id or os.getenv("BROWSER_USE_PROFILE_ID")
    if prof and str(prof).strip():
        body["profileId"] = str(prof).strip()
    if timeout_minutes is not None:
        body["timeout"] = max(1, min(240, int(timeout_minutes)))
    if browser_screen_width is not None:
        body["browserScreenWidth"] = browser_screen_width
    if browser_screen_height is not None:
        body["browserScreenHeight"] = browser_screen_height

    response = httpx.post(f"{_API_BASE}/browsers", headers=_headers(), json=body, timeout=timeout)
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"Browser Use POST /browsers failed ({response.status_code}): {detail}")
    data = response.json()
    browser_id = data.get("id")
    cdp_url = data.get("cdpUrl")
    live_url = data.get("liveUrl")
    if not isinstance(browser_id, str) or not browser_id:
        raise RuntimeError("Browser Use /browsers response missing id.")
    if not isinstance(cdp_url, str) or not cdp_url.strip():
        raise RuntimeError("Browser Use /browsers response missing cdpUrl.")
    if not isinstance(live_url, str) or not live_url.strip():
        raise RuntimeError("Browser Use /browsers response missing liveUrl.")
    return BrowserSessionCreated(
        browser_id=browser_id,
        cdp_url=cdp_url.strip(),
        live_url=live_url.strip(),
    )


def stop_browser_session(browser_id: str, *, timeout: float = 30.0) -> None:
    """``POST /browsers/{id}/stop`` — release billing when the agent run ends."""
    bid = browser_id.strip()
    if not bid:
        return
    response = httpx.post(
        f"{_API_BASE}/browsers/{bid}/stop",
        headers=_headers(),
        timeout=timeout,
    )
    if response.status_code in (200, 201, 204, 404):
        return
    raise RuntimeError(f"Browser Use stop failed ({response.status_code}): {response.text[:500]}")
