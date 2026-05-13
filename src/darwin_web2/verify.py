"""Post-action verification: executor errors, alert text, stagnation (same fingerprint chain)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from darwin_web2.observation import Observation


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


def verify_after_step(
    *,
    obs_before: Observation,
    obs_after: Observation,
    executor_error: str | None,
    fingerprint_history: deque[str],
) -> VerifyOutcome:
    """Cheap checks after each planner action. Updates *fingerprint_history* in place (maxlen 4)."""
    msgs: list[str] = []
    if executor_error:
        msgs.append(f"last_step_executor_error: {executor_error}")

    if obs_before.url != obs_after.url:
        fingerprint_history.clear()
    fingerprint_history.append(obs_after.fingerprint)

    stagnation = False
    if len(fingerprint_history) >= 3:
        last3 = list(fingerprint_history)[-3:]
        if last3[0] == last3[1] == last3[2]:
            stagnation = True
            msgs.append(
                "stagnation: URL + interactive fingerprint unchanged for 3 consecutive steps — "
                "change strategy (different control, fix validation, wait_ms, or request_human)."
            )

    digest_raw = (obs_after.alert_digest or "").strip()
    if _digest_signals_problem(digest_raw) and not executor_error:
        if not _digest_mirrors_doc_title(digest=digest_raw, title=obs_after.title):
            msgs.append(
                f"last_step_page_alerts: {obs_after.alert_digest!r} — read and address before repeating the same action."
            )

    ok = not executor_error and not stagnation
    return VerifyOutcome(ok=ok, messages=tuple(msgs), stagnation=stagnation)
