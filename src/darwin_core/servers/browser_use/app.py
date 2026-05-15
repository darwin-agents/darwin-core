from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from darwin_core.servers.browser_use.api import create_browser_session, stop_browser_session

app = FastAPI(title="Browser Use Server", version="0.2.0")


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
        description="Optional session timeout in seconds (max 4h).",
    )
    browser_screen_width: int | None = Field(default=None, ge=320, le=7680)
    browser_screen_height: int | None = Field(default=None, ge=240, le=4320)


class BrowserConnectResponse(BaseModel):
    browser_id: str
    cdp_ws_url: str
    live_url: str


class BrowserDisconnectRequest(BaseModel):
    browser_id: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/browser/connect", response_model=BrowserConnectResponse)
def browser_connect(payload: BrowserConnectRequest) -> BrowserConnectResponse:
    """Create a dedicated Browser Use Cloud session (agent + live view share the same tab)."""
    if not os.getenv("BROWSER_USE_API_KEY"):
        raise HTTPException(status_code=500, detail="Missing BROWSER_USE_API_KEY.")

    timeout_minutes: int | None = None
    if payload.timeout_seconds is not None:
        timeout_minutes = max(1, min(240, (payload.timeout_seconds + 59) // 60))

    try:
        session = create_browser_session(
            proxy_country_code=payload.proxy_country_code,
            profile_id=payload.profile_id,
            timeout_minutes=timeout_minutes,
            browser_screen_width=payload.browser_screen_width,
            browser_screen_height=payload.browser_screen_height,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return BrowserConnectResponse(
        browser_id=session.browser_id,
        cdp_ws_url=session.cdp_url,
        live_url=session.live_url,
    )


@app.post("/browser/disconnect")
def browser_disconnect(payload: BrowserDisconnectRequest) -> dict[str, str]:
    """Stop a browser session created by :func:`browser_connect`."""
    try:
        stop_browser_session(payload.browser_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "stopped"}


def main() -> None:
    load_dotenv()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("darwin_core.servers.browser_use.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
