"""Notify the human owner on Telegram when the planner hits a non-automatable wall (CAPTCHA, QR, SMS, etc.)."""

from __future__ import annotations

import html
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

_LAST_UPDATE_ID: int = 0
_LAST_OWNER_TELEGRAM_REPLY: str | None = None

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


def _is_owner_continue_message(text: str) -> bool:
    """True for owner replies that mean \"resume\" (supports ``/continue@BotName`` Telegram form)."""
    t = (text or "").strip().lower()
    if not t:
        return False
    first = t.split()[0]
    cmd = first.split("@", 1)[0]
    if cmd in _CONTINUE_MARKERS:
        return True
    return t in _CONTINUE_MARKERS


def consume_last_owner_telegram_reply() -> str | None:
    """Pop the last owner Telegram text queued after ``request_human`` (one-shot for the next planner turn)."""
    global _LAST_OWNER_TELEGRAM_REPLY  # noqa: PLW0603
    r = _LAST_OWNER_TELEGRAM_REPLY
    _LAST_OWNER_TELEGRAM_REPLY = None
    return r


def _set_last_owner_reply(text: str | None) -> None:
    global _LAST_OWNER_TELEGRAM_REPLY  # noqa: PLW0603
    _LAST_OWNER_TELEGRAM_REPLY = text


def _telegram_strict_continue_only() -> bool:
    """When true, only ``/continue``-style commands end the wait; default is any text (natural language)."""
    v = os.getenv("DARWIN_WEB_TELEGRAM_STRICT_CONTINUE", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def classify_human_input_kind(*, reason: str, instructions: str) -> str:
    """Rough class for Telegram copy: ``qr``, ``secret``, ``browser_ui``, or ``generic``."""
    blob = f"{reason} {instructions}".lower()
    if any(k in blob for k in ("qr", "scan the code", "scan on your phone")):
        return "qr"
    if any(k in blob for k in ("otp", "one-time", "verification code", "sms code", "inbox", "6-digit")):
        return "secret"
    if any(
        k in blob
        for k in (
            "captcha",
            "press and hold",
            "press-and-hold",
            "hold down",
            "mantener pulsado",
            "pulsar y mantener",
            "prove you are human",
            "prove you're human",
            "human verification",
            "not a robot",
        )
    ):
        return "browser_ui"
    return "generic"


def owner_browser_action_notice_plain() -> str:
    """When the owner must interact with the live tab (CAPTCHA, press-and-hold), not Telegram."""
    return (
        "Action required in the live browser window the agent controls — not in Telegram. "
        "Open the live view link in the message (not the raw WebSocket URL in a CDP connect box). "
        "The screenshot is only a reference. Complete the step there (e.g. press-and-hold), then reply."
    )


def owner_browser_action_notice_html() -> str:
    return (
        "<b>Action required in the browser</b> (not in Telegram). "
        "Open the <b>live view link</b> below in a normal browser tab — do <b>not</b> paste the "
        "raw WebSocket URL into “Connect to CDP endpoint” (that often shows <code>about:blank</code>). "
        "The screenshot is only a reference; complete the step in the live view, then reply below."
    )


def owner_telegram_reply_hint_plain(*, hil_kind: str = "generic") -> str:
    """Plain-text hint sent to the owner after a human-input request (also logged in artifacts)."""
    if _telegram_strict_continue_only():
        return (
            "Reply with /continue (or done) when the browser tab is ready for the agent to continue."
        )
    if hil_kind == "browser_ui":
        return (
            "When finished in the browser tab, send /continue, or reply in plain language "
            "(e.g. 'done', 'passed captcha', 'use accessible challenge')."
        )
    if hil_kind == "secret":
        return (
            "Type the OTP or secret into the browser tab yourself, or paste it here in plain language "
            "so the next planner turn can fill it. Send /continue when the tab is ready."
        )
    if hil_kind == "qr":
        return (
            "Scan the QR from the screenshot or the decoded link message on your phone. "
            "Send /continue when the browser tab has moved on."
        )
    return (
        "Reply in plain language to tell the agent what to do (language choice, OTP, corrections, "
        "etc.). The next planner turn will see your message. You can also send /continue when the "
        "tab is already in the right state and no extra instructions are needed."
    )


def owner_telegram_reply_hint_html(*, hil_kind: str = "generic") -> str:
    """Telegram HTML variant of :func:`owner_telegram_reply_hint_plain`."""
    if _telegram_strict_continue_only():
        return (
            "Reply with <code>/continue</code> (or <code>done</code>) when the browser tab is ready "
            "for the agent to continue."
        )
    if hil_kind == "browser_ui":
        return (
            "When finished in the <b>browser tab</b>, send <code>/continue</code> or reply in plain "
            "language (e.g. passed captcha)."
        )
    if hil_kind == "secret":
        return (
            "Enter the code in the <b>browser tab</b>, or paste it here in plain language for the next "
            "planner turn. Then <code>/continue</code> when ready."
        )
    if hil_kind == "qr":
        return (
            "Scan the QR from the screenshot or the decoded link on your phone. "
            "Send <code>/continue</code> when the browser tab has moved on."
        )
    return (
        "Reply in <b>plain language</b> to tell the agent what to do (language choice, OTP, corrections, "
        "etc.). The next planner turn will see your message. You can also send <code>/continue</code> "
        "when the tab is already in the right state and no extra instructions are needed."
    )


@dataclass
class RequestHumanResult:
    """Outcome of ``notify_owner_request_human`` (for logs and darwin_web2 artifacts)."""

    error: str | None = None
    owner_reply_hint: str = ""
    owner_reply: str | None = None
    waited_for_owner: bool = False
    telegram_configured: bool = True
    hil_kind: str = "generic"
    browser_action_notice: str | None = None
    browser_cdp_ws_url: str | None = None
    browser_live_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_artifact_dict(
        self,
        *,
        thought: str | None,
        reason: str,
        instructions: str,
        why_not_automated: str,
        page_url: str,
    ) -> dict[str, Any]:
        return {
            "agent": {
                "thought": thought,
                "reason": reason,
                "instructions": instructions,
                "why_not_automated": why_not_automated,
            },
            "owner_channel": {
                "telegram": {
                    "configured": self.telegram_configured,
                    "hil_kind": self.hil_kind,
                    "browser_action_notice": self.browser_action_notice,
                    "browser_cdp_ws_url": self.browser_cdp_ws_url,
                    "browser_live_url": self.browser_live_url,
                    "hint_message": self.owner_reply_hint or None,
                    "owner_reply": self.owner_reply,
                    "waited_for_owner": self.waited_for_owner,
                    "error": self.error,
                    "page_url": page_url or None,
                }
            },
        }


def _owner_message_ends_wait(text: str) -> bool:
    if not (text or "").strip():
        return False
    if _telegram_strict_continue_only():
        return _is_owner_continue_message(text)
    return True


def try_decode_http_qr_from_png(path: Path) -> str | None:
    """If ``DARWIN_WEB_DECODE_QR`` is enabled and OpenCV is installed, return first HTTP(S) string from a QR in the PNG.

    The browser address bar URL is often **not** the same as the URL encoded in a verification QR; decoding the
    screenshot can surface the mobile link. Optional dependency: ``opencv-python-headless`` (see ``telegram_qr`` extra).
    """
    gate = os.getenv("DARWIN_WEB_DECODE_QR", "0").strip().lower()
    if gate not in ("1", "true", "yes", "on"):
        return None
    if not path.is_file():
        return None
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        img = cv2.imread(str(path))
        if img is None:
            return None
        det = cv2.QRCodeDetector()
        out = det.detectAndDecode(img)
        val = ""
        if isinstance(out, tuple) and len(out) >= 1 and isinstance(out[0], str):
            val = out[0]
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    if s.startswith(("http://", "https://")):
        return s[:2000]
    return None


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


def send_telegram_decoded_qr_link(
    client: httpx.Client,
    *,
    base: str,
    chat_id: str,
    decoded_url: str,
) -> str | None:
    """Send mobile URL as tappable HTML link plus a plain-text duplicate (``<code>`` URLs are not clickable)."""
    u = decoded_url.strip()
    if not u:
        return None
    if len(u) > 4000:
        u = u[:4000]
    href_esc = html.escape(u, quote=True)
    html_msg = (
        "<b>Mobile link from QR</b> (tap below). If it does not open, use the next message which is plain text.\n"
        f'<a href="{href_esc}">Open on phone</a>'
    )
    for part in _chunk_text(html_msg, 4096):
        rq = client.post(
            f"{base}/sendMessage",
            json={"chat_id": chat_id, "text": part, "parse_mode": "HTML"},
        )
        if not _tg_ok(rq):
            return f"telegram sendMessage HTTP {rq.status_code}"
    rp = client.post(
        f"{base}/sendMessage",
        json={"chat_id": chat_id, "text": u},
    )
    if not _tg_ok(rp):
        return f"telegram sendMessage (plain URL) HTTP {rp.status_code}"
    return None


def notify_owner_request_human(
    *,
    reason: str,
    instructions: str,
    page_url: str,
    image_path: Path | None,
    wait_for_owner: bool,
    max_wait_s: float,
    browser_cdp_ws_url: str | None = None,
    browser_live_url: str | None = None,
    client: httpx.Client | None = None,
) -> RequestHumanResult:
    """Send owner Telegram updates (text + optional screenshot). Optionally block until they reply."""
    hil_kind = classify_human_input_kind(reason=reason, instructions=instructions)
    browser_notice: str | None = None
    if hil_kind == "browser_ui":
        browser_notice = owner_browser_action_notice_plain()
    hint_plain = owner_telegram_reply_hint_plain(hil_kind=hil_kind)
    cdp = (browser_cdp_ws_url or "").strip() or None
    live = (browser_live_url or "").strip() or None
    if live is None and cdp:
        from darwin_web.browser_connect import live_url_from_cdp_ws

        live = live_url_from_cdp_ws(cdp)
    token = os.getenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "").strip()
    chat_raw = os.getenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_raw:
        return RequestHumanResult(
            error="telegram: DARWIN_WEB_TELEGRAM_BOT_TOKEN and DARWIN_WEB_TELEGRAM_CHAT_ID must be set",
            owner_reply_hint=hint_plain,
            waited_for_owner=wait_for_owner,
            telegram_configured=False,
            hil_kind=hil_kind,
            browser_action_notice=browser_notice,
            browser_cdp_ws_url=cdp,
            browser_live_url=live,
        )
    er = html.escape(reason.strip(), quote=False)
    eu = html.escape(page_url.strip(), quote=False)
    ei = html.escape(instructions.strip(), quote=False)
    # Keep Telegram content aligned with the planner: reason + instructions first; no generic QR boilerplate here.
    header = (
        "<b>darwin_web — human input</b>\n\n"
        f"<b>Reason:</b> {er}\n\n"
        f"<b>Instructions (from planner):</b>\n{ei}"
    )
    if browser_notice is not None:
        header += f"\n\n{owner_browser_action_notice_html()}"
    if page_url.strip():
        header += f"\n\n<b>Page URL</b> (reference only):\n<code>{eu}</code>"
    if live:
        href_esc = html.escape(live, quote=True)
        header += (
            "\n\n<b>Live browser</b> — open this link to control the <b>same</b> session "
            f'the agent uses:\n<a href="{href_esc}">Open live browser</a>'
        )
        if hil_kind == "browser_ui":
            header += (
                "\n<i>Do not paste the WebSocket URL into “Connect to CDP endpoint”; "
                "that UI often attaches to a blank tab.</i>"
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
                return RequestHumanResult(
                    error=f"telegram sendMessage HTTP {r0.status_code}",
                    owner_reply_hint=hint_plain,
                    waited_for_owner=wait_for_owner,
                    hil_kind=hil_kind,
                    browser_action_notice=browser_notice,
                    browser_cdp_ws_url=cdp,
                    browser_live_url=live,
                )

        if live:
            for part in _chunk_text(live, 4096):
                rp = c.post(
                    f"{base}/sendMessage",
                    json={"chat_id": chat_raw, "text": part},
                )
                if not _tg_ok(rp):
                    return RequestHumanResult(
                        error=f"telegram sendMessage (live URL) HTTP {rp.status_code}",
                        owner_reply_hint=hint_plain,
                        waited_for_owner=wait_for_owner,
                        hil_kind=hil_kind,
                        browser_action_notice=browser_notice,
                        browser_cdp_ws_url=cdp,
                        browser_live_url=live,
                    )

        if image_path is not None and image_path.is_file():
            photo_caption = (
                "Reference screenshot of the agent's browser tab (interact in that window, not here)."
                if hil_kind == "browser_ui"
                else "Screenshot of the page the agent is on."
            )
            with image_path.open("rb") as f:
                r1 = c.post(
                    f"{base}/sendPhoto",
                    data={
                        "chat_id": chat_raw,
                        "caption": photo_caption,
                        "parse_mode": "HTML",
                    },
                    files={"photo": (image_path.name, f, "image/png")},
                )
            if not _tg_ok(r1):
                return RequestHumanResult(
                    error=f"telegram sendPhoto HTTP {r1.status_code}",
                    owner_reply_hint=hint_plain,
                    waited_for_owner=wait_for_owner,
                    hil_kind=hil_kind,
                    browser_action_notice=browser_notice,
                    browser_cdp_ws_url=cdp,
                    browser_live_url=live,
                )

            decoded = try_decode_http_qr_from_png(image_path)
            if decoded:
                qr_err = send_telegram_decoded_qr_link(
                    c, base=base, chat_id=chat_raw, decoded_url=decoded
                )
                if qr_err:
                    return RequestHumanResult(
                        error=qr_err,
                        owner_reply_hint=hint_plain,
                        waited_for_owner=wait_for_owner,
                        hil_kind=hil_kind,
                        browser_action_notice=browser_notice,
                        browser_cdp_ws_url=cdp,
                        browser_live_url=live,
                    )

        owner_reply: str | None = None
        if wait_for_owner:
            r3 = c.post(
                f"{base}/sendMessage",
                json={
                    "chat_id": chat_raw,
                    "text": owner_telegram_reply_hint_html(hil_kind=hil_kind),
                    "parse_mode": "HTML",
                },
            )
            if not _tg_ok(r3):
                return RequestHumanResult(
                    error=f"telegram sendMessage HTTP {r3.status_code}",
                    owner_reply_hint=hint_plain,
                    waited_for_owner=True,
                    hil_kind=hil_kind,
                    browser_action_notice=browser_notice,
                    browser_cdp_ws_url=cdp,
                    browser_live_url=live,
                )
            reply = _wait_for_owner_message(
                c,
                token=token,
                chat_id_filter=chat_raw,
                max_wait_s=max_wait_s,
            )
            if reply:
                owner_reply = reply[:4000]
                _set_last_owner_reply(owner_reply)
        return RequestHumanResult(
            owner_reply_hint=hint_plain,
            owner_reply=owner_reply,
            waited_for_owner=wait_for_owner,
            hil_kind=hil_kind,
            browser_action_notice=browser_notice,
            browser_cdp_ws_url=cdp,
            browser_live_url=live,
        )
    except httpx.HTTPError as exc:
        return RequestHumanResult(
            error=f"telegram HTTP: {exc}",
            owner_reply_hint=hint_plain,
            waited_for_owner=wait_for_owner,
            hil_kind=hil_kind,
            browser_action_notice=browser_notice,
            browser_cdp_ws_url=cdp,
            browser_live_url=live,
        )
    finally:
        if own_client:
            hc.close()


def _wait_for_owner_message(
    client: httpx.Client,
    *,
    token: str,
    chat_id_filter: str,
    max_wait_s: float,
) -> str | None:
    """Block until the owner sends a text message that ends the wait; return that text (trimmed) or ``None`` on timeout."""
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
            if _owner_message_ends_wait(text):
                return text.strip()[:4000]
    return None
