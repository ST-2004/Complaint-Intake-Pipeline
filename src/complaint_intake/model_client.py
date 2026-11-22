"""Model client seam (principle P12) and the errors the classifier can raise.

`ModelClient` is the only thing that talks to the LLM. The real implementation
uses the OpenAI-compatible v1 endpoint of the Foundry deployment with an Entra ID
token; tests use a fake. The model is given no tools (P6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from complaint_intake.config import Settings


class ClassificationError(Exception):
    """Base: the case must go to a human. `reason` is a stable code for the audit log."""

    reason = "classification_failed"

    def __init__(self, detail: str = "", *, attempts: int = 0, usage: Usage | None = None):
        super().__init__(f"{self.reason}: {detail}" if detail else self.reason)
        self.detail = detail
        self.attempts = attempts
        self.usage = usage or Usage()


class SchemaError(ClassificationError):
    reason = "model_output_invalid"


class ContentFilterError(ClassificationError):
    reason = "content_filter_blocked"

    def __init__(self, detail: str = "", *, categories: tuple[str, ...] = (), **kw):
        super().__init__(detail, **kw)
        self.categories = categories


class ModelCallError(ClassificationError):
    reason = "model_call_failed"


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens


@dataclass(frozen=True)
class ModelResponse:
    content: str | None
    finish_reason: str | None
    refusal: str | None
    model: str
    usage: Usage = field(default_factory=Usage)


class ModelClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any],
        schema_name: str,
        temperature: float,
        max_tokens: int,
    ) -> ModelResponse:
        """One chat call. Raises ContentFilterError or ModelCallError; never retries schema."""
        ...


class OpenAIChatClient:
    def __init__(self, client, deployment: str) -> None:
        self._client = client
        self.deployment = deployment

    def complete(self, messages, *, json_schema, schema_name, temperature, max_tokens):
        import openai

        try:
            resp = self._client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
                },
            )
        except openai.BadRequestError as exc:
            if _is_content_filter(exc):
                raise ContentFilterError(
                    "prompt blocked", categories=_filtered_categories(exc)
                ) from None
            raise ModelCallError(f"BadRequest {getattr(exc, 'code', '')}".strip()) from None
        except openai.APIError as exc:
            # Timeouts, rate limits, 5xx (after the SDK's own retries), auth failures.
            status = getattr(exc, "status_code", None)
            raise ModelCallError(f"{type(exc).__name__}{f' {status}' if status else ''}") from None

        choice = resp.choices[0]
        usage = Usage(
            getattr(resp.usage, "prompt_tokens", 0) or 0,
            getattr(resp.usage, "completion_tokens", 0) or 0,
        )
        return ModelResponse(
            content=choice.message.content,
            finish_reason=choice.finish_reason,
            refusal=getattr(choice.message, "refusal", None),
            model=resp.model,
            usage=usage,
        )


def _is_content_filter(exc: Exception) -> bool:
    if getattr(exc, "code", None) == "content_filter":
        return True
    body = getattr(exc, "body", None)
    return isinstance(body, dict) and body.get("code") == "content_filter"


def _filtered_categories(exc: Exception) -> tuple[str, ...]:
    """Names of the content-filter categories that fired (no text), for the audit log."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return ()
    result = (body.get("innererror") or {}).get("content_filter_result") or {}
    # Harm categories report "filtered"; Prompt Shields report "detected" (M4: one
    # red-team block came back with no category because only "detected" was set).
    return tuple(
        sorted(
            name
            for name, v in result.items()
            if isinstance(v, dict) and (v.get("filtered") or v.get("detected"))
        )
    )


def make_model_client(settings: Settings, credential=None) -> OpenAIChatClient:
    from azure.identity import get_bearer_token_provider
    from openai import OpenAI

    from complaint_intake.azure_auth import get_credential
    from complaint_intake.azure_clients import ConfigError

    missing = settings.missing("azure_ai_endpoint", "model_deployment")
    if missing:
        raise ConfigError(f"not set: {', '.join(missing)}; run `python tasks.py env`")
    token_provider = get_bearer_token_provider(
        credential or get_credential(), settings.azure_token_scope
    )
    client = OpenAI(
        base_url=settings.azure_ai_endpoint,
        api_key=token_provider,
        timeout=settings.request_timeout_s,
        max_retries=2,
    )
    return OpenAIChatClient(client, settings.model_deployment)
