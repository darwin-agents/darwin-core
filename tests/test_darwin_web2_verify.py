from __future__ import annotations

from collections import deque

from darwin_web2.observation import Observation
from darwin_web2.verify import verify_after_step


def _obs(url: str, fp: str, digest: str = "") -> Observation:
    return Observation(
        url=url,
        title="t",
        items=[],
        alert_digest=digest,
        fingerprint=fp,
        element_count=0,
    )


def test_verify_stagnation_after_three_identical_fingerprints() -> None:
    hist: deque[str] = deque(maxlen=4)
    o1 = _obs("https://x/a", "fp1")
    o2 = _obs("https://x/a", "fp1")
    v1 = verify_after_step(
        obs_before=o1, obs_after=o2, executor_error=None, fingerprint_history=hist
    )
    assert not v1.stagnation
    v2 = verify_after_step(
        obs_before=o2, obs_after=o2, executor_error=None, fingerprint_history=hist
    )
    assert not v2.stagnation
    v3 = verify_after_step(
        obs_before=o2, obs_after=o2, executor_error=None, fingerprint_history=hist
    )
    assert v3.stagnation
    assert not v3.ok


def test_verify_skips_page_alerts_when_digest_is_only_doc_title() -> None:
    hist: deque[str] = deque(maxlen=4)
    title = "Información básica Introduce tu fecha de nacimiento y tu género."
    o = Observation(
        url="https://accounts.example/signup",
        title=title,
        items=[],
        alert_digest=title,
        fingerprint="fp1",
        element_count=0,
    )
    vo = verify_after_step(
        obs_before=o, obs_after=o, executor_error=None, fingerprint_history=hist
    )
    assert not any("last_step_page_alerts" in m for m in vo.messages)


def test_verify_keeps_page_alerts_when_digest_differs_from_title() -> None:
    hist: deque[str] = deque(maxlen=4)
    title = "Información básica Introduce tu fecha de nacimiento y tu género."
    digest = "Introduce una fecha de nacimiento completa."
    o = Observation(
        url="https://accounts.example/signup",
        title=title,
        items=[],
        alert_digest=digest,
        fingerprint="fp1",
        element_count=0,
    )
    vo = verify_after_step(
        obs_before=o, obs_after=o, executor_error=None, fingerprint_history=hist
    )
    assert any("last_step_page_alerts" in m for m in vo.messages)
    hist = deque(maxlen=4)
    oa = _obs("https://a/", "same")
    ob = _obs("https://b/", "same")
    verify_after_step(obs_before=oa, obs_after=ob, executor_error=None, fingerprint_history=hist)
    assert len(hist) == 1
