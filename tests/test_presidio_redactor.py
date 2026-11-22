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


@pytest.mark.parametrize(
    "text,must_survive",
    [
        ("You charged me a $15.95 monthly fee I never agreed to.", "monthly fee"),
        ("I am trying to open a chequing account at the branch.", "trying to open"),
        ("This is the third month in a row.", "the third month"),
    ],
)
def test_case_sensitive_patterns_do_not_eat_ordinary_words(redactor, text, must_survive):
    # Regression: Presidio compiles with IGNORECASE by default, which made
    # "[A-Z][a-z]+" match any word ("$15.95 monthly fee" became an ADDRESS).
    assert must_survive in redactor.redact(text).text


@pytest.mark.parametrize(
    "text,name",
    [
        ("I've called five times. Aayush Stone", "Aayush Stone"),
        ("The deposit is missing. Renée Boily, 416-555-0101", "Renée Boily"),
        ("My name is Ekiya Gravel and my card was declined.", "Ekiya Gravel"),
    ],
)
def test_sign_off_and_introduction_names(redactor, text, name):
    assert name.split()[-1] not in redactor.redact(text).text


@pytest.mark.parametrize("street", ["464 Amanda Crossroad", "2328 Figueroa Skyway Apt. 290"])
def test_structural_street_addresses(redactor, street):
    assert street.split()[1] not in redactor.redact(f"I moved to {street} last year.").text


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
