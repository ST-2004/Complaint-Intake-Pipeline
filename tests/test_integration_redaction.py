"""Real Azure AI Language calls (M1). Run after `infra-up` + `env`:  pytest -m integration"""

from pathlib import Path

import pytest

from complaint_intake.config import PiiProvider, Settings
from complaint_intake.enrichment import get_enricher
from complaint_intake.pii_check import load_samples
from complaint_intake.redaction import get_redactor
from complaint_intake.redaction.leaks import find_leaks

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def live_settings():
    mp = pytest.MonkeyPatch()
    mp.chdir(ROOT)
    s = Settings(pii_provider=PiiProvider.AZURE)
    mp.undo()
    if not s.azure_language_endpoint:
        pytest.skip("no .env; run `python tasks.py env` first")
    return s


@pytest.fixture(scope="module")
def redactor(live_settings):
    return get_redactor(live_settings)


@pytest.mark.parametrize("sample", load_samples(), ids=lambda s: s.id)
def test_azure_no_seeded_value_survives(redactor, sample):
    result = redactor.redact(sample.text)
    assert find_leaks(sample.seeded, result.text) == []


def test_azure_enrichment_on_redacted_text(live_settings, redactor):
    sample = load_samples()[0]
    signals = get_enricher(live_settings).enrich(redactor.redact(sample.text).text)
    assert signals.available, signals.error
    assert signals.sentiment in {"negative", "mixed"}
    assert signals.key_phrases
