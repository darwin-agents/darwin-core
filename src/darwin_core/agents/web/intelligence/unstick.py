"""Deterministic recovery on signup registration pages (no LLM)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_SUBMIT_TEXT_TOKENS = (
    "registr",
    "sign up",
    "signup",
    "create account",
    "crear cuenta",
    "submit",
    "continuar",
    "siguiente",
    "next",
    "weiter",
    "suivant",
)


def is_registration_url(url: str) -> bool:
    ul = (url or "").lower()
    path = urlparse(ul).path.lower()
    if any(k in path for k in ("registration", "signup", "sign-up", "register", "registr")):
        return True
    return any(k in ul for k in ("registration", "signup", "sign-up", "/register"))


def _checkbox_unchecked(it: dict[str, Any]) -> bool:
    if str(it.get("type", "")).lower() != "checkbox":
        return False
    return str(it.get("checked", "")).lower() not in ("true", "1", "yes")


def _is_submit_like(it: dict[str, Any]) -> bool:
    tag = str(it.get("tag", "")).lower()
    typ = str(it.get("type", "")).lower()
    role = str(it.get("role", "")).lower()
    blob = f"{it.get('text', '')} {it.get('aria', '')} {it.get('placeholder', '')}".lower()
    if typ == "submit":
        return True
    if tag == "button" and role != "combobox" and any(tok in blob for tok in _SUBMIT_TEXT_TOKENS):
        return True
    if tag in ("a", "button") and any(tok in blob for tok in _SUBMIT_TEXT_TOKENS):
        cls = str(it.get("class", "") or "").lower()
        if tag == "a" and ("btn" in cls or "button" in role):
            return True
        if tag == "a" and any(tok in blob for tok in ("registr", "sign up", "signup", "submit")):
            return True
    return False


def build_signup_unstick_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scripted sequence: check every unchecked checkbox, then click first submit-like control."""
    actions: list[dict[str, Any]] = []
    for it in items:
        if not _checkbox_unchecked(it):
            continue
        ref = it.get("ref")
        if ref is None:
            continue
        actions.append(
            {
                "op": "click",
                "ref": int(ref),
                "describe": f"unstick: check consent checkbox ref {ref}",
            }
        )
    for it in items:
        if not _is_submit_like(it):
            continue
        ref = it.get("ref")
        if ref is None:
            continue
        actions.append(
            {
                "op": "click",
                "ref": int(ref),
                "describe": "unstick: click submit/primary control",
            }
        )
        break
    return actions
