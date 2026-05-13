from __future__ import annotations

from darwin_web.navigator import (
    _gmail_username_screen_hint,
    _google_birthday_screen_hint,
    _google_create_email_choice_hint,
    _nav_breadcrumb,
    _password_screen_hint,
)


def test_google_birthday_hint_when_gender_placeholder() -> None:
    url = "https://accounts.google.com/lifecycle/steps/signup/birthdaygender?x=1"
    items = [
        {"ref": 1, "role": "combobox", "text": "Month January"},
        {"ref": 4, "role": "combobox", "text": "Gender"},
    ]
    h = _google_birthday_screen_hint(items, url)
    assert "pick_option" in h
    assert "Gender" in h


def test_google_birthday_hint_noop_when_not_birthday_url() -> None:
    assert _google_birthday_screen_hint([], "https://example.com/") == ""


def test_password_screen_hint_after_password_fill() -> None:
    url = "https://accounts.google.com/lifecycle/steps/signup/password?TL=1"
    title = "Create a strong password"
    items = [
        {"ref": 1, "tag": "input", "type": "password", "aria": "Password", "value": ""},
        {"ref": 2, "tag": "input", "type": "password", "aria": "Confirm", "value": ""},
    ]
    last = {"op": "fill", "ref": 1, "value": "Secret123!", "describe": "x"}
    h = _password_screen_hint(items, title, url, last)
    assert "ref 2" in h
    assert "Confirm" in h


def test_password_screen_hint_when_confirm_visible_in_yaml() -> None:
    url = "https://example.com/password"
    title = "Password"
    items = [
        {"ref": 1, "tag": "input", "type": "password", "aria": "Password", "value": "abc"},
        {"ref": 2, "tag": "input", "type": "password", "aria": "Confirm", "value": ""},
    ]
    h = _password_screen_hint(items, title, url, None)
    assert "ref 2" in h


def test_gmail_username_screen_hint() -> None:
    h = _gmail_username_screen_hint("How you'll sign in", "https://accounts.google.com/lifecycle/steps/signup/username?x=1")
    assert "unique" in h.lower() or "Unique" in h


def test_nav_breadcrumb_strips_query() -> None:
    a = _nav_breadcrumb("https://accounts.google.com/lifecycle/steps/signup/username?TL=abc")
    b = _nav_breadcrumb("https://accounts.google.com/lifecycle/steps/signup/username?TL=xyz")
    assert a == b
    assert "signup/username" in a


def test_google_create_email_choice_hint() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "radio", "name": "usernameRadio", "value": "jd"},
        {"ref": 4, "tag": "input", "type": "text", "name": "Username"},
    ]
    h = _google_create_email_choice_hint(
        "Create an email address",
        "https://accounts.google.com/lifecycle/steps/signup/username?x=1",
        items,
    )
    assert "radio" in h.lower()
    assert "click" in h.lower()
