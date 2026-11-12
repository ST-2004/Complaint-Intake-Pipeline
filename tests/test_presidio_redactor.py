"""Presidio runs locally, so these are real (offline) redaction tests."""

import pytest

from complaint_intake.pii_check import load_samples
from complaint_intake.redaction.base import RedactionError
from complaint_intake.redaction.leaks import find_leaks

pytest.importorskip("presidio_analyzer")
pytest.importorskip("en_core_web_sm")

from complaint_intake.redaction.presidio import PresidioRedactor, luhn_valid  # noqa: E402


@pytest.fixture(scope="module")
def redactor():
    return PresidioRedactor()


@pytest.mark.parametrize("sample", load_samples(), ids=lambda s: s.id)
def test_no_seeded_value_survives(redactor, sample):
    result = redactor.redact(sample.text)
    assert find_leaks(sample.seeded, result.text) == []


def test_canadian_recognizers(redactor):
    text = "SIN 046 454 286, postal code M5V 2T6, 77 Queen Street West"
    result = redactor.redact(text)
    assert "046 454 286" not in result.text
    assert "M5V 2T6" not in result.text
    assert "77 Queen Street" not in result.text


def test_invalid_sin_checksum_is_not_tagged_as_government_id(redactor):
    assert "GOVERNMENT_ID" not in redactor.redact("reference 123 456 789").categories


def test_luhn():
    assert luhn_valid("4111111111111111") and luhn_valid("046454286")
    assert not luhn_valid("4111111111111112") and not luhn_valid("12a")


def test_analyzer_failure_fails_closed():
    class Broken:
        def analyze(self, **_):
            raise RuntimeError("model missing")

    with pytest.raises(RedactionError, match="presidio: RuntimeError"):
        PresidioRedactor(analyzer=Broken()).redact("Priya Raman")
