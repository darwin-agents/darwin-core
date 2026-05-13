"""Notify the human owner on Telegram when the planner hits a non-automatable wall (CAPTCHA, QR, SMS, etc.)."""

from __future__ import annotations

import html
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

_LAST_UPDATE_ID: int = 0

_CONTINUE_MARKERS = frozenset(
    {
        "/continue",
        "/done",
        "continue",
        "done",
        "ok",
        "ready",
        "go",
    }
)


def telegram_hil_env_enabled() -> bool:
    """True when bot token and chat id are set (optional ``DARWIN_WEB_TELEGRAM_HIL`` gate)."""
    gate = os.getenv("DARWIN_WEB_TELEGRAM_HIL", "1").strip().lower()
    if gate in ("0", "false", "no", "off"):
        return False
    token = os.getenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "").strip()
    return bool(token and chat)


def _bot_base(token: str) -> str:
    return f"https://api.telegram.org/bot{token.strip()}"


def coerce_bool(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("0", "false", "no", "off"):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
    return default


def coerce_max_wait_s(value: Any, *, default: float = 3600.0) -> float:
    if value is None:
        raw = os.getenv("DARWIN_WEB_TELEGRAM_MAX_WAIT_S", str(int(default)))
    else:
        raw = value
    if isinstance(raw, (int, float)):
        return max(5.0, float(raw))
    if isinstance(raw, str):
        try:
            return max(5.0, float(raw.strip()))
        except ValueError:
            return max(5.0, default)
    return max(5.0, default)


def _chunk_text(text: str, max_len: int) -> list[str]:
    t = text
    if len(t) <= max_len:
        return [t] if t else []
    return [t[i : i + max_len] for i in range(0, len(t), max_len)]


def _tg_ok(resp: httpx.Response) -> bool:
    if resp.status_code != 200:
        return False
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and bool(data.get("ok"))


def notify_owner_request_human(
    *,
    reason: str,
    instructions: str,
    page_url: str,
    image_path: Path | None,
    wait_for_owner: bool,
    max_wait_s: float,
    client: httpx.Client | None = None,
) -> str | None:
    """Send owner Telegram updates (text + optional screenshot). Optionally block until they reply.

    Returns ``None`` on success, or a short error string for the agent log.
    """
    token = os.getenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "").strip()
    chat_raw = os.getenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_raw:
        return "telegram: DARWIN_WEB_TELEGRAM_BOT_TOKEN and DARWIN_WEB_TELEGRAM_CHAT_ID must be set"

    er = html.escape(reason.strip(), quote=False)
    eu = html.escape(page_url.strip(), quote=False)
    ei = html.escape(instructions.strip(), quote=False)
    header = (
        "<b>darwin_web — human step required</b>\n\n"
        f"<b>Reason:</b> {er}\n"
        f"<b>Page:</b> {eu}\n\n"
        "<b>Instructions:</b>"
    )

    own_client = client is None
    hc = httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0))
    try:
        c = hc if client is None else client
        base = _bot_base(token)

        for part in _chunk_text(header, 4096):
            r0 = c.post(
                f"{base}/sendMessage",
                json={"chat_id": chat_raw, "text": part, "parse_mode": "HTML"},
            )
            if not _tg_ok(r0):
                return f"telegram sendMessage HTTP {r0.status_code}"

        if image_path is not None and image_path.is_file():
            with image_path.open("rb") as f:
                r1 = c.post(
                    f"{base}/sendPhoto",
                    data={
                        "chat_id": chat_raw,
                        "caption": "Current page (screenshot)",
                        "parse_mode": "HTML",
                    },
                    files={"photo": (image_path.name, f, "image/png")},
                )
            if not _tg_ok(r1):
                return f"telegram sendPhoto HTTP {r1.status_code}"

        for part in _chunk_text(ei, 4096):
            r2 = c.post(
                f"{base}/sendMessage",
                json={"chat_id": chat_raw, "text": part, "parse_mode": "HTML"},
            )
            if not _tg_ok(r2):
                return f"telegram sendMessage HTTP {r2.status_code}"

        hint = (
            "Reply with <code>/continue</code> (or <code>done</code>) in this chat when you have "
            "finished on the browser so the agent can resume."
        )
        if wait_for_owner:
            r3 = c.post(
                f"{base}/sendMessage",
                json={"chat_id": chat_raw, "text": hint, "parse_mode": "HTML"},
            )
            if not _tg_ok(r3):
                return f"telegram sendMessage HTTP {r3.status_code}"
            _wait_for_owner_message(
                c,
                token=token,
                chat_id_filter=chat_raw,
                max_wait_s=max_wait_s,
            )
        return None
    except httpx.HTTPError as exc:
        return f"telegram HTTP: {exc}"
    finally:
        if own_client:
            hc.close()


def _wait_for_owner_message(
    client: httpx.Client,
    *,
    token: str,
    chat_id_filter: str,
    max_wait_s: float,
) -> None:
    global _LAST_UPDATE_ID  # noqa: PLW0603
    deadline = time.monotonic() + max(1.0, float(max_wait_s))
    base = _bot_base(token)
    want = str(chat_id_filter).strip()

    while time.monotonic() < deadline:
        remain = deadline - time.monotonic()
        timeout = int(min(30, max(1, remain)))
        try:
            r = client.get(
                f"{base}/getUpdates",
                params={
                    "offset": _LAST_UPDATE_ID + 1,
                    "timeout": timeout,
                    "allowed_updates": json.dumps(["message"]),
                },
            )
        except httpx.HTTPError:
            time.sleep(1.0)
            continue
        if r.status_code != 200:
            time.sleep(1.0)
            continue
        try:
            payload = r.json()
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not payload.get("ok"):
            continue
        results = payload.get("result")
        if not isinstance(results, list):
            continue
        for upd in results:
            if not isinstance(upd, dict):
                continue
            uid = upd.get("update_id")
            if isinstance(uid, int):
                _LAST_UPDATE_ID = max(_LAST_UPDATE_ID, uid)
            msg = upd.get("message")
            if not isinstance(msg, dict):
                continue
            chat = msg.get("chat")
            if not isinstance(chat, dict):
                continue
            cid = chat.get("id")
            if str(cid).strip() != want:
                continue
            text = msg.get("text")
            if not isinstance(text, str):
                continue
            key = text.strip().lower()
            if not key:
                continue
            first = key.split()[0] if key else ""
            if key in _CONTINUE_MARKERS or first in _CONTINUE_MARKERS:
                return
