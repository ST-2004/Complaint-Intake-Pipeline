"""OpenAIChatClient error mapping, using real openai exception types."""

from types import SimpleNamespace

import httpx2
import openai
import pytest

from complaint_intake.model_client import ContentFilterError, ModelCallError, OpenAIChatClient

REQUEST = httpx2.Request("POST", "https://example.invalid/openai/v1/chat/completions")


def bad_request(body):
    response = httpx2.Response(400, request=REQUEST)
    return openai.BadRequestError("bad request", response=response, body=body)


class FakeCompletions:
    def __init__(self, result):
        self.result, self.kwargs = result, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client_for(result):
    completions = FakeCompletions(result)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAIChatClient(sdk, "triage-model"), completions


def call(client):
    return client.complete(
        [{"role": "user", "content": "x"}],
        json_schema={"type": "object"},
        schema_name="s",
        temperature=0,
        max_tokens=10,
    )


def test_success_maps_fields_and_sends_strict_schema():
    resp = SimpleNamespace(
        model="gpt-4.1-mini-2025-04-14",
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
        choices=[
            SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content="{}", refusal=None)
            )
        ],
    )
    client, completions = client_for(resp)
    out = call(client)
    assert out.content == "{}" and out.usage.prompt_tokens == 12
    fmt = completions.kwargs["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert completions.kwargs["model"] == "triage-model"
    assert "tools" not in completions.kwargs


def test_azure_prompt_filter_becomes_content_filter_error():
    body = {
        "code": "content_filter",
        "innererror": {
            "code": "ResponsibleAIPolicyViolation",
            "content_filter_result": {
                "violence": {"filtered": True, "severity": "medium"},
                "hate": {"filtered": False, "severity": "safe"},
                "jailbreak": {"filtered": True, "detected": True},
            },
        },
    }
    client, _ = client_for(bad_request(body))
    with pytest.raises(ContentFilterError) as info:
        call(client)
    assert info.value.categories == ("jailbreak", "violence")


def test_other_bad_request_is_model_call_error():
    client, _ = client_for(bad_request({"code": "invalid_request"}))
    with pytest.raises(ModelCallError):
        call(client)


def test_timeout_is_model_call_error():
    client, _ = client_for(openai.APITimeoutError(request=REQUEST))
    with pytest.raises(ModelCallError, match="APITimeoutError"):
        call(client)
