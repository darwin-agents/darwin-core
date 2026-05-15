from __future__ import annotations


from darwin_core.agents.web.integrations.email_providers import EmailProvider, next_provider_goto_url, provider_index_for_url


def test_next_provider_after_mailfence() -> None:
    providers = [
        EmailProvider("Mailfence", "BE", "https://mailfence.com", "Low", ""),
        EmailProvider("Inbox", "LV", "https://www.inbox.lv", "Low", ""),
    ]
    nxt = next_provider_goto_url(
        current_url="https://mailfence.com/registration/",
        goal="create a new email account",
        providers=providers,
    )
    assert nxt == "https://www.inbox.lv"
    assert provider_index_for_url("https://mailfence.com/reg", providers) == 0
