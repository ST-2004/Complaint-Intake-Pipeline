"""Smoke-probe logic with fake SDK clients (no network)."""

from types import SimpleNamespace

import azure.ai.textanalytics as ta

from complaint_intake import smoke
from complaint_intake.azure_auth import hint_for
from complaint_intake.config import Settings


class FakeTextAnalytics:
    redacted = "Hello, my name is *************** and you can call me at ********."

    def __init__(self, endpoint, credential):
        self.endpoint = endpoint

    def recognize_pii_entities(self, docs, language):
        return [
            SimpleNamespace(
                is_error=False,
                redacted_text=self.redacted,
                entities=[
                    SimpleNamespace(category="Person"),
                    SimpleNamespace(category="PhoneNumber"),
                ],
            )
        ]


def settings(**kw):
    base = {"azure_language_endpoint": "https://lang-x.cognitiveservices.azure.com/"}
    return Settings(**{**base, **kw})


def test_language_probe_passes_and_never_prints_raw_values(monkeypatch):
    monkeypatch.setattr(ta, "TextAnalyticsClient", FakeTextAnalytics)
    result = smoke.probe_language(settings(), credential=object())
    assert result.ok
    assert "Person" in result.detail and "PhoneNumber" in result.detail
    for seeded in smoke.PII_PROBE_SEEDED:
        assert seeded.value not in result.detail


def test_language_probe_fails_when_seeded_value_survives(monkeypatch):
    class Leaky(FakeTextAnalytics):
        redacted = smoke.PII_PROBE  # nothing redacted

    monkeypatch.setattr(ta, "TextAnalyticsClient", Leaky)
    result = smoke.probe_language(settings(), credential=object())
    assert not result.ok and "survived" in result.detail


def test_partial_name_leak_is_caught(monkeypatch):
    # Regression from the first live run: only the first name was redacted.
    class HalfRedacted(FakeTextAnalytics):
        redacted = "Hello, my name is ****** Mitchell and you can call me at ********."

    monkeypatch.setattr(ta, "TextAnalyticsClient", HalfRedacted)
    result = smoke.probe_language(settings(), credential=object())
    assert not result.ok and "survived" in result.detail


def test_language_probe_reports_missing_endpoint():
    result = smoke.probe_language(Settings(), credential=object())
    assert not result.ok and "AZURE_LANGUAGE_ENDPOINT" in result.detail


def test_model_probe_reports_missing_settings():
    result = smoke.probe_model(Settings(), credential=object())
    assert not result.ok
    assert "AZURE_AI_ENDPOINT" in result.detail and "MODEL_DEPLOYMENT" in result.detail


def test_auth_hints():
    assert "device-code" in hint_for("ERROR: AADSTS70043: The refresh token has expired")
    assert "propagat" in hint_for("Error code: 403 - PermissionDenied")
    assert hint_for("something unrelated") is None
