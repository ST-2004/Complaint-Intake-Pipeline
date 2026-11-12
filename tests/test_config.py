import pytest
from pydantic import ValidationError

from complaint_intake.config import DEFAULT_TOKEN_SCOPE, PiiProvider, Settings


def test_defaults_without_env():
    s = Settings()
    assert s.azure_language_endpoint is None
    assert s.azure_token_scope == DEFAULT_TOKEN_SCOPE
    assert s.pii_provider is PiiProvider.AZURE
    assert s.missing("azure_ai_endpoint", "model_deployment") == [
        "AZURE_AI_ENDPOINT",
        "MODEL_DEPLOYMENT",
    ]


def test_reads_dotenv_file(tmp_path):
    (tmp_path / ".env").write_text(
        "AZURE_AI_ENDPOINT=https://ai-x.openai.azure.com/openai/v1\n"
        "MODEL_DEPLOYMENT=triage-model\nPII_PROVIDER=presidio\n",  # pragma: allowlist secret
        encoding="utf-8",
    )
    s = Settings()
    assert s.azure_ai_endpoint == "https://ai-x.openai.azure.com/openai/v1/"  # slash added
    assert s.model_deployment == "triage-model"
    assert s.pii_provider is PiiProvider.PRESIDIO
    assert s.missing("azure_ai_endpoint", "model_deployment") == []


def test_rejects_plain_http(monkeypatch):
    monkeypatch.setenv("AZURE_LANGUAGE_ENDPOINT", "http://insecure.example")
    with pytest.raises(ValidationError):
        Settings()


def test_rejects_unknown_pii_provider(monkeypatch):
    monkeypatch.setenv("PII_PROVIDER", "regex")
    with pytest.raises(ValidationError):
        Settings()
