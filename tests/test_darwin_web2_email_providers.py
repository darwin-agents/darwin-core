from __future__ import annotations

import json
from pathlib import Path

import pytest

from darwin_web2.email_providers import (
    build_email_providers_prompt_block,
    goal_wants_email_creation,
    load_email_providers,
    select_providers_for_goal,
)


@pytest.fixture
def sample_providers(tmp_path: Path) -> Path:
    data = [
        {
            "provider": "Mailfence",
            "country": "Belgium",
            "url": "https://mailfence.com",
            "bot_difficulty": "Low",
            "notes": "Easy.[cite: 1]",
        },
        {
            "provider": "Gmail",
            "country": "US",
            "url": "https://mail.google.com",
            "bot_difficulty": "Very High",
            "notes": "Hard.",
        },
        {
            "provider": "Outlook",
            "country": "US",
            "url": "https://signup.live.com",
            "bot_difficulty": "Very High",
            "notes": "CAPTCHA.",
        },
    ]
    p = tmp_path / "emails.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_strips_cite_markers(sample_providers: Path) -> None:
    providers = load_email_providers(sample_providers)
    assert providers[0].notes == "Easy."


def test_goal_wants_email_creation() -> None:
    assert goal_wants_email_creation("open an email account but not in gmail")
    assert not goal_wants_email_creation("search weather in Madrid")


def test_select_excludes_gmail(sample_providers: Path) -> None:
    providers = load_email_providers(sample_providers)
    chosen = select_providers_for_goal("open an email account but not in gmail", providers)
    names = [p.provider for p in chosen]
    assert names[0] == "Mailfence"
    assert "Gmail" not in names


def test_select_explicit_gmail_only(sample_providers: Path) -> None:
    providers = load_email_providers(sample_providers)
    chosen = select_providers_for_goal("open a gmail account", providers)
    assert len(chosen) == 1
    assert chosen[0].provider == "Gmail"


def test_prompt_block_lists_order_and_start_url(sample_providers: Path) -> None:
    providers = load_email_providers(sample_providers)
    block = build_email_providers_prompt_block(
        "create a new email mailbox", providers
    )
    assert "EMAIL_PROVIDER_RANKING" in block
    assert "1. Mailfence" in block
    assert "https://mailfence.com" in block
    assert "Preferred start" in block
