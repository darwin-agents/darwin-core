"""Filter and sanitize steps before appending to a v2 playbook (replay-safe recipes)."""

from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

from darwin_core.agents.web.playbook.playbook import PlaybookStep
from darwin_core.agents.web.integrations.email_providers import EmailProvider, _host_matches_provider
from darwin_core.agents.web.security.redact import _looks_like_expanded_password

_GENHASH_LOCAL_RE = re.compile(r"^[a-z0-9]{8,12}$")


def _describe(action: dict[str, Any]) -> str:
    return str(action.get("describe") or "").strip().lower()


def _goto_host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:  # noqa: BLE001
        return ""


def should_record_playbook_step(
    *,
    action: dict[str, Any],
    tag: str,
    executor_error: str | None,
    stagnation: bool,
    locked_provider: EmailProvider | None,
    recorded: list[PlaybookStep],
) -> bool:
    """Whether this executed step belongs in a human replay recipe."""
    if executor_error or stagnation:
        return False
    if tag in ("scripted", "reflect"):
        return False

    op = action.get("op")
    desc = _describe(action)

    if op == "request_human":
        return False
    if desc.startswith("auto-advance:") or desc.startswith("unstick:") or "fast-path:" in desc:
        return False

    if op == "goto":
        url = str(action.get("url") or "").strip()
        if not url:
            return False
        host = _goto_host(url)
        if locked_provider is not None and not _host_matches_provider(host, locked_provider):
            return False
        if recorded:
            for prev in reversed(recorded):
                if prev.op == "goto" and _goto_host(str(prev.url or "")) == host:
                    return False
                if prev.op in ("fill", "click", "select_option", "pick_option"):
                    break
        return True

    return True


def _fill_sentinel(dom: dict[str, Any] | None, raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    val = raw_value.strip()
    if not val:
        return val
    typ = str((dom or {}).get("type", "")).lower()
    name = str((dom or {}).get("name", "")).lower()
    placeholder = str((dom or {}).get("placeholder", "")).lower()
    aria = str((dom or {}).get("aria_label", "")).lower()
    blob = f"{name} {placeholder} {aria}"

    if typ == "password" or "password" in name or "contraseña" in placeholder:
        return "$GENHASH_PW"
    if name in ("login", "username") or "usuario" in blob or "username" in blob:
        return "$GENHASH"
    if _GENHASH_LOCAL_RE.match(val):
        return "$GENHASH"
    if _looks_like_expanded_password(val):
        return "$GENHASH_PW"
    return raw_value


def sanitize_playbook_step(step: PlaybookStep, *, action: dict[str, Any]) -> PlaybookStep:
    """Replace ephemeral generated secrets with planner sentinels for replay."""
    dom = copy.deepcopy(step.dom) if step.dom else None
    value = step.value

    if step.op == "fill":
        value = _fill_sentinel(dom, value)
        if dom is not None:
            if value in ("$GENHASH", "$GENHASH_PW"):
                dom["entered_text"] = value
            elif dom.get("type", "").lower() == "password":
                dom["entered_text"] = "$GENHASH_PW"

    return replace(step, dom=dom, value=value)


def is_duplicate_playbook_step(prev: PlaybookStep | None, step: PlaybookStep) -> bool:
    if prev is None:
        return False
    return (
        prev.op == step.op
        and (prev.selector or "") == (step.selector or "")
        and (prev.url or "") == (step.url or "")
        and (prev.value or "") == (step.value or "")
        and (prev.key or "") == (step.key or "")
    )
