from __future__ import annotations

from darwin_core.agents.web.intelligence.hints import owner_profile_field_mapping_hint, signup_consent_and_submit_hint


def test_signup_hint_unchecked_checkboxes() -> None:
    items = [
        {"ref": 8, "tag": "input", "type": "checkbox", "checked": "false", "value": "on"},
        {"ref": 11, "tag": "input", "type": "checkbox", "checked": "false", "value": "on"},
        {"ref": 12, "tag": "a", "type": "", "text": "Registrarse", "checked": ""},
    ]
    hint = signup_consent_and_submit_hint(items, page_url="https://mailfence.com/registration/")
    assert "unchecked" in hint.lower()
    assert "ref 8" in hint


def test_signup_hint_submit_when_boxes_checked() -> None:
    items = [
        {"ref": 8, "tag": "input", "type": "checkbox", "checked": "true", "value": "on"},
        {"ref": 11, "tag": "input", "type": "checkbox", "checked": "true", "value": "on"},
        {"ref": 12, "tag": "a", "type": "", "text": "Registrarse", "checked": ""},
    ]
    hint = signup_consent_and_submit_hint(items, page_url="https://mailfence.com/registration/")
    assert "ref 12" in hint
    assert "Registrarse" in hint


def test_owner_profile_apellido_nombre_hint() -> None:
    items = [
        {"ref": 1, "tag": "input", "type": "text", "placeholder": "Apellido"},
        {"ref": 2, "tag": "input", "type": "text", "aria": "Nombre"},
    ]
    hint = owner_profile_field_mapping_hint(
        items,
        {"last_name": "Rivera", "first_name": "Alex"},
    )
    assert "last_name" in hint
    assert "first_name" in hint
    assert "Rivera" in hint
