from __future__ import annotations

import string

import pytest

from darwin_core.agents.web.integrations.genhash import (
    expand_fill_value,
    genhash,
    reserved_email_domain_error,
    reset_pw_cache,
    try_expand_fill,
    username_genhash_length,
)


def test_genhash_username_charset_and_length() -> None:
    s = genhash(14)
    assert len(s) == 14
    assert all(c in string.ascii_lowercase + string.digits for c in s)


def test_genhash_password_charset() -> None:
    s = genhash(50, password=True)
    allowed = set(string.ascii_letters + string.digits + "!@%^_+-=")
    assert set(s) <= allowed
    assert len(s) == 50


def test_expand_fill_username_clears_password_cache() -> None:
    reset_pw_cache()
    a = expand_fill_value("$GENHASH_PW")
    b = expand_fill_value("$GENHASH_PW")
    assert a == b
    expand_fill_value("$GENHASH")
    c = expand_fill_value("$GENHASH_PW")
    assert c != a


def test_expand_fill_preserves_normal_strings() -> None:
    assert expand_fill_value(" hello ") == " hello "


def test_genhash_length_clamped() -> None:
    assert len(genhash(4)) == 8
    assert len(genhash(200)) == 128


def test_try_expand_fill_blocks_genhash_on_first_name_dom() -> None:
    dom = {"name": "firstName", "aria_label": "First name"}
    raw, err = try_expand_fill("$GENHASH", dom=dom)
    assert err is not None
    assert raw == "$GENHASH"
    _raw2, err2 = try_expand_fill("$GENHASH_PW", dom=dom)
    assert err2 is not None


def test_username_genhash_length_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DARWIN_WEB_GENHASH_USERNAME_LENGTH", raising=False)
    assert username_genhash_length() == 10


def test_username_genhash_length_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARWIN_WEB_GENHASH_USERNAME_LENGTH", "99")
    assert username_genhash_length() == 12
    monkeypatch.setenv("DARWIN_WEB_GENHASH_USERNAME_LENGTH", "3")
    assert username_genhash_length() == 8


def test_try_expand_fill_allows_genhash_on_username_dom() -> None:
    dom = {"name": "Username", "aria_label": "Username"}
    out, err = try_expand_fill("$GENHASH", dom=dom)
    assert err is None
    assert len(out) == username_genhash_length()


def test_try_expand_fill_genhash_digit_suffix_and_email_local() -> None:
    reset_pw_cache()
    out, err = try_expand_fill("$GENHASH2", dom=None)
    assert err is None
    assert len(out) == username_genhash_length()
    assert "$" not in out
    mail, err2 = try_expand_fill("$GENHASH2@gmail.com", dom=None)
    assert err2 is None
    assert mail.endswith("@gmail.com")
    assert "$" not in mail
    local = mail.split("@", 1)[0]
    assert len(local) == username_genhash_length()


def test_try_expand_fill_rejects_reserved_mail_host() -> None:
    raw, err = try_expand_fill("$GENHASH@example.com", dom=None)
    assert err is not None
    assert raw == "$GENHASH@example.com"
    assert reserved_email_domain_error("user@example.com") is not None


def test_try_expand_fill_blocks_genhash2_email_on_first_name() -> None:
    dom = {"name": "firstName", "aria_label": "First name"}
    raw, err = try_expand_fill("$GENHASH2@gmail.com", dom=dom)
    assert err is not None
    assert raw == "$GENHASH2@gmail.com"
