from __future__ import annotations

from darwin_web.navigator import (
    _done_summary_describes_partial_progress,
    _google_birthday_screen_hint,
    _human_wall_page_hint,
    _nav_breadcrumb,
    _password_screen_hint,
    _radio_group_with_text_username_hint,
    _signup_username_step_hint,
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


def test_google_birthday_hint_when_gender_placeholder_spanish() -> None:
    url = "https://accounts.google.com/lifecycle/steps/signup/birthdaygender?x=1"
    items = [
        {"ref": 2, "role": "combobox", "text": "Mes Enero"},
        {"ref": 4, "role": "combobox", "text": "Género"},
    ]
    h = _google_birthday_screen_hint(items, url)
    assert "pick_option" in h
    assert "Género" in h or "Mujer" in h


def test_google_birthday_hint_noop_when_not_birthday_url() -> None:
    assert _google_birthday_screen_hint([], "https://example.com/") == ""


def test_radio_group_username_hint_when_presets_and_custom_field() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "radio", "name": "usernameRadio"},
        {"ref": 2, "tag": "input", "type": "radio", "name": "usernameRadio"},
        {"ref": 4, "tag": "input", "type": "text", "name": "Username", "aria": "Create a Gmail address"},
    ]
    h = _radio_group_with_text_username_hint(items)
    assert "radio" in h.lower()
    assert "random" in h.lower()


def test_radio_group_username_hint_noop_with_single_radio() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "radio", "name": "x"},
        {"ref": 4, "tag": "input", "type": "text", "name": "Username"},
    ]
    assert _radio_group_with_text_username_hint(items) == ""


def test_radio_group_username_hint_noop_without_usernameish_text() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "radio", "name": "plan"},
        {"ref": 2, "tag": "input", "type": "radio", "name": "plan"},
        {"ref": 3, "tag": "input", "type": "text", "name": "coupon"},
    ]
    assert _radio_group_with_text_username_hint(items) == ""


def test_signup_username_step_hint_google_url() -> None:
    url = "https://accounts.google.com/lifecycle/steps/signup/username?TL=1"
    items = [{"ref": 1, "tag": "input", "type": "text", "name": "Username", "value": "youruniqueusername"}]
    h = _signup_username_step_hint(url, items)
    assert "$genhash" in h.lower()
    assert "youruniqueusername" in h


def test_signup_username_step_hint_noop_wrong_path() -> None:
    assert _signup_username_step_hint("https://example.com/profile", []) == ""


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


def test_human_wall_page_hint_verification_error_titles() -> None:
    h = _human_wall_page_hint("Please try again with a different phone number", "https://example.com/x")
    assert "instructions" in h.lower()
    assert "error" in h.lower() or "retry" in h.lower()


def test_human_wall_page_hint_verify_qr_wall() -> None:
    h = _human_wall_page_hint("Verify some info before creating an account", "")
    assert "request_human" in h.lower() or "human" in h.lower()
    a = _nav_breadcrumb("https://accounts.google.com/lifecycle/steps/signup/username?TL=abc")
    b = _nav_breadcrumb("https://accounts.google.com/lifecycle/steps/signup/username?TL=xyz")
    assert a == b
    assert "signup/username" in a


def test_done_summary_partial_progress_heuristic() -> None:
    assert _done_summary_describes_partial_progress("Completed signup up to the password step.")
    assert _done_summary_describes_partial_progress("Partially finished checkout.")
    assert not _done_summary_describes_partial_progress("Opened inbox and sent the email.")
