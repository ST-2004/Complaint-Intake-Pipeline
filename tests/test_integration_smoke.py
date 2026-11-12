"""Real Azure calls. Run manually after `infra-up` and `env`:  pytest -m integration"""

from pathlib import Path

import pytest

from complaint_intake import smoke
from complaint_intake.config import Settings

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def live_settings(monkeypatch):
    monkeypatch.chdir(ROOT)  # pick up the real .env
    s = Settings()
    if not s.azure_language_endpoint:
        pytest.skip("no .env; run `python tasks.py env` first")
    return s


def test_language_live(live_settings):
    result = smoke.probe_language(live_settings)
    assert result.ok, f"{result.detail} | hint: {result.hint}"


def test_model_live(live_settings):
    result = smoke.probe_model(live_settings)
    assert result.ok, f"{result.detail} | hint: {result.hint}"
