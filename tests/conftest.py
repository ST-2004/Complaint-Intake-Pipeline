import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Unit tests never read the developer's real .env or Azure settings."""
    for key in (
        "AZURE_LANGUAGE_ENDPOINT",
        "AZURE_AI_ENDPOINT",
        "MODEL_DEPLOYMENT",
        "AZURE_TOKEN_SCOPE",
        "PII_PROVIDER",
        "DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
