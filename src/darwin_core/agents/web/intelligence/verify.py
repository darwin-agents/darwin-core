"""Post-action verification: executor errors, alert text, stagnation (same fingerprint chain)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from darwin_core.agents.web.browser.observation import Observation


@dataclass(frozen=True)
class VerifyOutcome:
    """Result of comparing state before/after one executed step."""

    ok: bool
    messages: tuple[str, ...]
    stagnation: bool


def _digest_signals_problem(digest: str) -> bool:
    """Heuristic: non-empty digest after an action often means validation still complaining."""
    if not digest.strip():
        return False
    # Length-only heuristic avoids locale-specific keywords.
    return len(digest.strip()) >= 12


def _digest_mirrors_doc_title(*, digest: str, title: str) -> bool:
    """True when the digest is only the step heading/title repeated in a live region (not an error).

    Some sign-up flows (e.g. Google) expose the main instruction string via ``role=alert`` or
    ``aria-live``; treating it as ``page_alerts`` makes the planner loop on ``click``/``fill``
    trying to \"address\" text that is not a validation failure.
    """
    d = " ".join(digest.split()).strip().lower()
    t = " ".join((title or "").split()).strip().lower()
    if len(d) < 12 or not t:
        return False
    if d == t:
        return True
    # One string largely contains the other (title may add a suffix, or digest a prefix).
    if len(d) >= 24 and len(t) >= 24 and (d in t or t in d):
        return True
    return False


def _field_values_progress(obs_before: Observation, obs_after: Observation) -> bool:
    """True when a text field gained a value or a checkbox/radio toggled (layout hash ignores these)."""
    after_by_ref: dict[Any, dict[str, Any]] = {}
    for it in obs_after.items:
        r = it.get("ref")
        if r is not None:
            after_by_ref[r] = it
    for it in obs_before.items:
        r = it.get("ref")
        if r is None or r not in after_by_ref:
            continue
        other = after_by_ref[r]
        typ = str(it.get("type", "")).lower()
        if typ in ("checkbox", "radio"):
            if str(it.get("checked", "")).lower() != str(other.get("checked", "")).lower():
                return True
            continue
        b_val = str(it.get("value", "")).strip()
        a_val = str(other.get("value", "")).strip()
        if not b_val and a_val:
            return True
    return False


def _repeated_action_pattern(
    recent_actions: deque[tuple[str, int | None, str | None]] | None,
    *,
    min_count: int = 3,
) -> tuple[str, int] | None:
    """Return (op, ref) when the last *min_count* steps used the same op+ref."""
    if recent_actions is None or len(recent_actions) < min_count:
        return None
    tail = list(recent_actions)[-min_count:]
    op0, ref0, _d0 = tail[0]
    if ref0 is None or not op0:
        return None
    for op, ref, _d in tail[1:]:
        if op != op0 or ref != ref0:
            return None
    return op0, ref0


def verify_after_step(
    *,
    obs_before: Observation,
    obs_after: Observation,
    executor_error: str | None,
    fingerprint_history: deque[str],
    recent_actions: deque[tuple[str, int | None, str | None]] | None = None,
) -> VerifyOutcome:
    """Cheap checks after each planner action. Updates *fingerprint_history* in place (maxlen 4)."""
    msgs: list[str] = []
    if executor_error:
        msgs.append(f"last_step_executor_error: {executor_error}")

    if obs_before.url != obs_after.url:
        fingerprint_history.clear()
    made_field_progress = _field_values_progress(obs_before, obs_after)
    if made_field_progress and fingerprint_history:
        fingerprint_history.clear()
    fingerprint_history.append(obs_after.layout_fingerprint)

    stagnation = False
    if len(fingerprint_history) >= 3:
        last3 = list(fingerprint_history)[-3:]
        if last3[0] == last3[1] == last3[2] and not made_field_progress:
            stagnation = True
            msgs.append(
                "stagnation: URL + page layout unchanged for 3 consecutive steps — "
                "change strategy (submit/primary button, different control, fix validation, "
                "wait_ms, or request_human)."
            )

    repeat = _repeated_action_pattern(recent_actions)
    if repeat is not None:
        op_name, ref_n = repeat
        stagnation = True
        msgs.append(
            f"stagnation: repeated {op_name} on ref {ref_n} three times without progress — "
            "use a different op or ref (e.g. click submit when fields look complete)."
        )

    digest_raw = (obs_after.alert_digest or "").strip()
    if _digest_signals_problem(digest_raw) and not executor_error:
        if not _digest_mirrors_doc_title(digest=digest_raw, title=obs_after.title):
            msgs.append(
                f"last_step_page_alerts: {obs_after.alert_digest!r} — read and address before repeating the same action."
            )

    ok = not executor_error and not stagnation
    return VerifyOutcome(ok=ok, messages=tuple(msgs), stagnation=stagnation)
