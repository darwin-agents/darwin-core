from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def normalize_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        return domain[4:]
    return domain


def signal_match(signals: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    url = str(snapshot.get("url", "")).lower()
    title = str(snapshot.get("title", "")).lower()
    body = str(snapshot.get("body_text_excerpt", "")).lower()
    predicates = [
        ("url_contains", url),
        ("title_contains", title),
        ("body_contains", body),
    ]
    for key, haystack in predicates:
        needles = signals.get(key) if isinstance(signals, dict) else []
        if isinstance(needles, list) and needles:
            if not any(isinstance(needle, str) and needle.lower() in haystack for needle in needles):
                return False
    return True


def recipe_considered_success(recipe: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    success_signals = recipe.get("success_signals", {})
    failure_signals = recipe.get("failure_signals", {})
    if signal_match(failure_signals, snapshot):
        has_failure_rules = any(
            isinstance(failure_signals.get(key), list) and failure_signals.get(key)
            for key in ("url_contains", "title_contains", "body_contains")
        )
        if has_failure_rules:
            return False

    has_success_rules = any(
        isinstance(success_signals.get(key), list) and success_signals.get(key)
        for key in ("url_contains", "title_contains", "body_contains")
    )
    if not has_success_rules:
        return True
    return signal_match(success_signals, snapshot)

