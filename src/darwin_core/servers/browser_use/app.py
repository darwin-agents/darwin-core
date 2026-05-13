from __future__ import annotations

import os
from urllib.parse import urlencode

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Browser Use Server", version="0.1.0")


class BrowserConnectRequest(BaseModel):
    proxy_country_code: str | None = Field(
        default=None,
        description="Optional proxy country (ISO 3166-1 alpha-2), e.g. es Spain, us US, de Germany.",
    )
    profile_id: str | None = Field(default=None, description="Optional Browser Use profile ID.")
    timeout_seconds: int | None = Field(
        default=None,
        ge=60,
        le=14400,
        description="Optional session timeout in seconds.",
    )
    browser_screen_width: int | None = Field(default=None, ge=320, le=7680)
    browser_screen_height: int | None = Field(default=None, ge=240, le=4320)


class BrowserConnectResponse(BaseModel):
    cdp_ws_url: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/browser/connect", response_model=BrowserConnectResponse)
def browser_connect(payload: BrowserConnectRequest) -> BrowserConnectResponse:
    api_key = os.getenv("BROWSER_USE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing BROWSER_USE_API_KEY.")

    proxy_country_code = payload.proxy_country_code or os.getenv("BROWSER_USE_PROXY_COUNTRY_CODE")
    profile_id = payload.profile_id or os.getenv("BROWSER_USE_PROFILE_ID")

    params: dict[str, str] = {"apiKey": api_key}
    if proxy_country_code:
        params["proxyCountryCode"] = proxy_country_code
    if profile_id:
        params["profileId"] = profile_id
    if payload.timeout_seconds is not None:
        params["timeout"] = str(payload.timeout_seconds)
    if payload.browser_screen_width is not None:
        params["browserScreenWidth"] = str(payload.browser_screen_width)
    if payload.browser_screen_height is not None:
        params["browserScreenHeight"] = str(payload.browser_screen_height)

    connect_base_url = os.getenv("BROWSER_USE_CONNECT_BASE_URL", "wss://connect.browser-use.com").rstrip("/")
    cdp_ws_url = f"{connect_base_url}?{urlencode(params)}"
    return BrowserConnectResponse(cdp_ws_url=cdp_ws_url)


def main() -> None:
    load_dotenv()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("darwin_core.servers.browser_use.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

