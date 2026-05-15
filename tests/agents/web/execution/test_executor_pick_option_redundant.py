from __future__ import annotations

from darwin_core.agents.web.execution.executor import (
    _pick_option_redundant_vs_combobox_blobs,
    _word_tokens,
)


def test_word_tokens_spanish_month() -> None:
    assert _word_tokens("Mes Enero") == {"mes", "enero"}


def test_pick_option_not_redundant_spanish_month_label_noise() -> None:
    # "Mes" is a known UI label noise word — "Mes Enero" does NOT prove Enero is already selected.
    # This was the core bug: the agent was stuck because pick_option("Enero") returned no-error
    # even though no role=option row was actually clicked.
    assert _pick_option_redundant_vs_combobox_blobs("Enero", ["Mes Enero", "Género Mujer"]) is False


def test_pick_option_redundant_when_non_noise_context() -> None:
    # Non-noise extra tokens ("nacimiento", "de") make it genuinely redundant.
    assert _pick_option_redundant_vs_combobox_blobs("Enero", ["Mes de nacimiento Enero"]) is True


def test_pick_option_redundant_spanish_gender() -> None:
    assert _pick_option_redundant_vs_combobox_blobs("Hombre", ["Mes Enero", "Género Hombre"]) is True


def test_pick_option_not_redundant_when_value_differs() -> None:
    assert _pick_option_redundant_vs_combobox_blobs("Hombre", ["Mes Enero", "Género Mujer"]) is False


def test_pick_option_not_redundant_placeholder_género() -> None:
    assert _pick_option_redundant_vs_combobox_blobs("Género", ["Mes", "Género"]) is False


def test_pick_option_not_redundant_single_token_equals_blob() -> None:
    """Closed combobox shows only ``Enero`` — not a strict superset, so do not treat as redundant."""
    assert _pick_option_redundant_vs_combobox_blobs("Enero", ["Enero"]) is False
