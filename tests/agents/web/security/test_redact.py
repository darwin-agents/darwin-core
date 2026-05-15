from __future__ import annotations

from darwin_core.agents.web.security.redact import redact_dom_artifact, redact_secrets_text, redact_turn_artifact_doc


def test_redact_genhash_pw_token() -> None:
    assert "***REDACTED***" in redact_secrets_text('fill value: "$GENHASH_PW"')


def test_redact_password_field_in_dom_artifact() -> None:
    doc = {
        "interactive_elements": [
            {"ref": 1, "type": "password", "value": "SecretPass123!"},
            {"ref": 2, "type": "text", "value": "hello"},
        ]
    }
    out = redact_dom_artifact(doc)
    assert out["interactive_elements"][0]["value"] == "***REDACTED***"
    assert out["interactive_elements"][1]["value"] == "hello"


def test_redact_turn_artifact_user_prompt() -> None:
    doc = {
        "prompt": {"user_text": "password: Abcdef12!@#xyz"},
        "planner": {"action": {"op": "fill", "value": "$GENHASH_PW"}},
    }
    out = redact_turn_artifact_doc(doc)
    assert "$GENHASH_PW" not in str(out)
    assert "***REDACTED***" in str(out)
