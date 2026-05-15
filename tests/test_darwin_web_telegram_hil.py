from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from darwin_web import telegram_hil as th


def test_notify_includes_browser_live_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "99")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "1")
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "sendMessage" in str(request.url):
            body = json.loads(request.content.decode())
            sent.append(body.get("text", ""))
        if "getUpdates" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {
                            "update_id": 1,
                            "message": {"chat": {"id": 99}, "text": "/continue"},
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
    cdp = "wss://connect.browser-use.com?apiKey=test&proxyCountryCode=es"
    live = "https://live.browser-use.com?wss=wss%3A%2F%2Fconnect.browser-use.com%3FapiKey%3Dtest"
    result = th.notify_owner_request_human(
        reason="CAPTCHA",
        instructions="Hold the button.",
        page_url="https://signup.live.com/",
        image_path=None,
        wait_for_owner=True,
        max_wait_s=5.0,
        browser_cdp_ws_url=cdp,
        browser_live_url=live,
        client=client,
    )
    assert result.ok
    assert result.browser_cdp_ws_url == cdp
    assert result.browser_live_url == live
    assert any("live.browser-use.com" in t for t in sent)
    assert any("Open live browser" in t for t in sent)
    assert not any("CDP WebSocket" in t for t in sent)


def test_classify_browser_ui_captcha() -> None:
    assert th.classify_human_input_kind(
        reason="CAPTCHA requires manual interaction",
        instructions="Press and hold the button in the browser",
    ) == "browser_ui"


def test_telegram_hil_env_enabled_respects_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "0")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "1")
    assert th.telegram_hil_env_enabled() is False

    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "1")
    assert th.telegram_hil_env_enabled() is True


def test_notify_owner_accepts_plain_language_reply(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "99")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "1")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_STRICT_CONTINUE", "0")
    th._LAST_UPDATE_ID = 0
    th.consume_last_owner_telegram_reply()

    def handler(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            body = {
                "ok": True,
                "result": [
                    {
                        "update_id": 8,
                        "message": {"chat": {"id": 99}, "text": "I don't care about language"},
                    }
                ],
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=5.0)
    img = tmp_path / "s.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    result = th.notify_owner_request_human(
        reason="Language",
        instructions="Confirm language preference.",
        page_url="https://example.com/x",
        image_path=img,
        wait_for_owner=True,
        max_wait_s=30.0,
        client=client,
    )
    assert result.ok
    assert "plain language" in result.owner_reply_hint
    assert th.consume_last_owner_telegram_reply() == "I don't care about language"


def test_consume_last_owner_reply_is_one_shot() -> None:
    th._set_last_owner_reply("hello")
    assert th.consume_last_owner_telegram_reply() == "hello"
    assert th.consume_last_owner_telegram_reply() is None


def test_notify_owner_sends_messages_and_waits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "99")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "1")
    th._LAST_UPDATE_ID = 0
    th.consume_last_owner_telegram_reply()

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append((request.method, url))
        if "getUpdates" in url:
            body = {
                "ok": True,
                "result": [
                    {
                        "update_id": 7,
                        "message": {"chat": {"id": 99}, "text": "/continue"},
                    }
                ],
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=5.0)
    img = tmp_path / "s.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    result = th.notify_owner_request_human(
        reason="QR wall",
        instructions="Scan the code on your phone.",
        page_url="https://example.com/x",
        image_path=img,
        wait_for_owner=True,
        max_wait_s=30.0,
        client=client,
    )
    assert result.ok
    assert result.owner_reply == "/continue"
    assert any("sendMessage" in u for _, u in calls)
    assert any("sendPhoto" in u for _, u in calls)
    assert any("getUpdates" in u for _, u in calls)
    assert th.consume_last_owner_telegram_reply() == "/continue"


def test_owner_message_ends_wait_accepts_any_text_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DARWIN_WEB_TELEGRAM_STRICT_CONTINUE", raising=False)
    assert th._owner_message_ends_wait("I don't care")


def test_owner_message_strict_mode_requires_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_STRICT_CONTINUE", "1")
    assert not th._owner_message_ends_wait("I don't care")
    assert th._owner_message_ends_wait("/continue")


def test_coerce_max_wait_s() -> None:
    assert th.coerce_max_wait_s("12", default=100.0) == 12.0
    assert th.coerce_max_wait_s(3, default=100.0) == 5.0  # minimum 5 seconds
    assert th.coerce_max_wait_s("nope", default=90.0) == 90.0


def test_is_owner_continue_message_accepts_bot_suffix() -> None:
    assert th._is_owner_continue_message("/continue@SomeBot")
    assert th._is_owner_continue_message("/CONTINUE@test_bot")
    assert th._is_owner_continue_message("done")
    assert not th._is_owner_continue_message("still working")


def test_try_decode_qr_skipped_when_gate_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DARWIN_WEB_DECODE_QR", "0")
    p = tmp_path / "x.png"
    p.write_bytes(b"x")
    assert th.try_decode_http_qr_from_png(p) is None


def test_send_telegram_decoded_qr_sends_html_link_and_plain_url() -> None:
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and "sendMessage" in str(request.url):
            posted.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=5.0)
    err = th.send_telegram_decoded_qr_link(
        client,
        base="https://api.telegram.org/botTEST",
        chat_id="42",
        decoded_url="https://mobile-verify.example.com/path?token=abc",
    )
    assert err is None
    assert len(posted) == 2
    assert posted[0].get("parse_mode") == "HTML"
    assert "<a href=" in posted[0]["text"]
    assert "mobile-verify.example.com" in posted[0]["text"]
    assert posted[1].get("parse_mode") is None
    assert posted[1]["text"] == "https://mobile-verify.example.com/path?token=abc"
