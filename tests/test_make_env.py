import pytest

from make_env import build_env, parse_env, render_env

OUTPUTS = {
    "language_endpoint": {"value": "https://lang-x.cognitiveservices.azure.com/"},
    "openai_v1_endpoint": {"value": "https://ai-x.openai.azure.com/openai/v1/"},
    "model_deployment": {"value": "triage-model"},
    "resource_group": {"value": "rg-x"},
}


def test_build_env_sets_managed_keys_and_defaults():
    env = build_env(OUTPUTS, {})
    assert env["AZURE_LANGUAGE_ENDPOINT"] == "https://lang-x.cognitiveservices.azure.com/"
    assert env["AZURE_AI_ENDPOINT"] == "https://ai-x.openai.azure.com/openai/v1/"
    assert env["MODEL_DEPLOYMENT"] == "triage-model"
    assert env["PII_PROVIDER"] == "azure"
    assert env["DB_PATH"] == "./triage.db"


def test_build_env_keeps_user_choices_but_refreshes_endpoints():
    existing = {
        "PII_PROVIDER": "presidio",
        "AZURE_TOKEN_SCOPE": "https://ai.azure.com/.default",
        "AZURE_AI_ENDPOINT": "https://stale.example/",
        "CUSTOM": "1",
    }
    env = build_env(OUTPUTS, existing)
    assert env["PII_PROVIDER"] == "presidio"
    assert env["AZURE_TOKEN_SCOPE"] == "https://ai.azure.com/.default"
    assert env["CUSTOM"] == "1"
    assert env["AZURE_AI_ENDPOINT"] == "https://ai-x.openai.azure.com/openai/v1/"


def test_build_env_explains_missing_output():
    with pytest.raises(KeyError, match="terraform apply"):
        build_env({"language_endpoint": {"value": "https://x/"}}, {})


def test_render_parse_round_trip():
    env = build_env(OUTPUTS, {})
    assert parse_env(render_env(env)) == env


def test_rendered_env_holds_no_keys_or_tokens():
    text = render_env(build_env(OUTPUTS, {})).lower()
    assert "api_key" not in text and "secret" not in text.replace("no secrets", "")
