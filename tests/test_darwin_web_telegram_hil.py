from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from darwin_web import telegram_hil as th


def test_telegram_hil_env_enabled_respects_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "0")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "1")
    assert th.telegram_hil_env_enabled() is False

    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "1")
    assert th.telegram_hil_env_enabled() is True


def test_notify_owner_sends_messages_and_waits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_BOT_TOKEN", "TESTTOKEN")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_CHAT_ID", "99")
    monkeypatch.setenv("DARWIN_WEB_TELEGRAM_HIL", "1")
    th._LAST_UPDATE_ID = 0

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

    err = th.notify_owner_request_human(
        reason="QR wall",
        instructions="Scan the code on your phone.",
        page_url="https://example.com/x",
        image_path=img,
        wait_for_owner=True,
        max_wait_s=30.0,
        client=client,
    )
    assert err is None
    assert any("sendMessage" in u for _, u in calls)
    assert any("sendPhoto" in u for _, u in calls)
    assert any("getUpdates" in u for _, u in calls)


def test_coerce_max_wait_s() -> None:
    assert th.coerce_max_wait_s("12", default=100.0) == 12.0
    assert th.coerce_max_wait_s(3, default=100.0) == 5.0  # minimum 5 seconds
    assert th.coerce_max_wait_s("nope", default=90.0) == 90.0
