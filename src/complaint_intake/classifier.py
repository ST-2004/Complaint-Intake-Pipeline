"""LLM classification: build prompt, call the model, validate, retry once.

Input is REDACTED text only. Output is a validated `ModelTriage` plus the
metadata the audit log and evaluation need (versions, attempts, latency,
tokens, cost). Any failure raises a `ClassificationError` subclass, and the
pipeline (M3) routes the case to a human with that reason (rule R7).
Nothing here logs complaint text.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from complaint_intake.config import Settings
from complaint_intake.enrichment import Signals
from complaint_intake.model_client import (
    ClassificationError,
    ContentFilterError,
    ModelCallError,
    ModelClient,
    SchemaError,
    Usage,
)
from complaint_intake.prompts import Prompt, build_messages, load_prompt
from complaint_intake.schemas import ModelTriage, model_output_json_schema

log = logging.getLogger(__name__)

SCHEMA_NAME = "complaint_triage"
MAX_ATTEMPTS = 2  # first try + one retry (principle P4)


@dataclass(frozen=True)
class ClassificationOutcome:
    triage: ModelTriage
    attempts: int
    latency_ms: float
    usage: Usage
    cost_usd: float
    prompt_version: str
    prompt_sha256: str
    model_deployment: str
    model_name: str
    delimiter_tampering: bool

    @property
    def first_attempt_valid(self) -> bool:
        return self.attempts == 1


class Classifier:
    def __init__(
        self,
        client: ModelClient,
        *,
        deployment: str,
        prompt: Prompt,
        temperature: float = 0.0,
        max_tokens: int = 400,
        price_in_per_1m: float = 0.0,
        price_out_per_1m: float = 0.0,
    ) -> None:
        self._client = client
        self._deployment = deployment
        self._prompt = prompt
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._price_in = price_in_per_1m
        self._price_out = price_out_per_1m
        self._schema = model_output_json_schema()

    @property
    def prompt(self) -> Prompt:
        return self._prompt

    def cost(self, usage: Usage) -> float:
        return (
            usage.prompt_tokens * self._price_in + usage.completion_tokens * self._price_out
        ) / 1_000_000

    def classify(
        self, redacted_text: str, signals: Signals | None = None, *, flags: tuple[str, ...] = ()
    ) -> ClassificationOutcome:
        built = build_messages(
            self._prompt,
            redacted_text,
            sentiment=signals.sentiment if signals and signals.available else None,
            key_phrases=signals.key_phrases if signals and signals.available else (),
            flags=flags,
        )
        messages = list(built.messages)
        usage = Usage()
        start = time.perf_counter()
        last_error = ""
        model_name = self._deployment

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = self._client.complete(
                    messages,
                    json_schema=self._schema,
                    schema_name=SCHEMA_NAME,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                )
            except ClassificationError as exc:
                exc.attempts, exc.usage = attempt, usage
                self._log("error", attempt, start, usage, reason=exc.reason)
                raise
            usage.add(resp.usage)
            model_name = resp.model or model_name

            if resp.finish_reason == "content_filter":
                self._log("error", attempt, start, usage, reason="content_filter_output")
                raise ContentFilterError("output blocked", attempts=attempt, usage=usage)
            if resp.refusal:
                self._log("error", attempt, start, usage, reason="refusal")
                raise ContentFilterError("model refused", attempts=attempt, usage=usage)

            try:
                triage = _parse(resp.content, resp.finish_reason)
            except _InvalidOutput as exc:
                last_error = str(exc)
                if attempt < MAX_ATTEMPTS:
                    # Retry once, telling the model what was wrong. The bad output
                    # contains only redacted text, so echoing it back is safe.
                    messages = [
                        *built.messages,
                        {"role": "assistant", "content": resp.content or ""},
                        {
                            "role": "user",
                            "content": "Your previous reply was not valid for the schema: "
                            f"{last_error}. Reply again with only the corrected JSON.",
                        },
                    ]
                    continue
                self._log("invalid", attempt, start, usage, reason=last_error)
                raise SchemaError(last_error, attempts=attempt, usage=usage) from None

            latency = (time.perf_counter() - start) * 1000
            self._log("ok", attempt, start, usage)
            return ClassificationOutcome(
                triage=triage,
                attempts=attempt,
                latency_ms=latency,
                usage=usage,
                cost_usd=self.cost(usage),
                prompt_version=self._prompt.version,
                prompt_sha256=self._prompt.sha256,
                model_deployment=self._deployment,
                model_name=model_name,
                delimiter_tampering=built.delimiter_tampering,
            )

        raise SchemaError(last_error, attempts=MAX_ATTEMPTS, usage=usage)  # pragma: no cover

    def _log(self, outcome: str, attempt: int, start: float, usage: Usage, reason: str = ""):
        # Metadata only: never the complaint, the summary or the raw model output.
        log.info(
            "classify outcome=%s attempts=%d latency_ms=%.0f tokens_in=%d tokens_out=%d "
            "prompt=%s reason=%s",
            outcome,
            attempt,
            (time.perf_counter() - start) * 1000,
            usage.prompt_tokens,
            usage.completion_tokens,
            self._prompt.version,
            reason,
        )


class _InvalidOutput(Exception):
    pass


def _parse(content: str | None, finish_reason: str | None) -> ModelTriage:
    if finish_reason == "length":
        raise _InvalidOutput("output truncated (max tokens reached)")
    if not content:
        raise _InvalidOutput("empty response")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise _InvalidOutput(f"not JSON ({exc.msg})") from None
    try:
        return ModelTriage.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        raise _InvalidOutput(problems) from None


def get_classifier(settings: Settings, *, client: ModelClient | None = None) -> Classifier:
    if client is None:
        from complaint_intake.model_client import make_model_client

        client = make_model_client(settings)
    return Classifier(
        client,
        deployment=settings.model_deployment or "unknown",
        prompt=load_prompt(settings.prompt_version),
        temperature=settings.model_temperature,
        max_tokens=settings.model_max_output_tokens,
        price_in_per_1m=settings.model_price_in_per_1m,
        price_out_per_1m=settings.model_price_out_per_1m,
    )


__all__ = [
    "ClassificationError",
    "ClassificationOutcome",
    "Classifier",
    "ContentFilterError",
    "ModelCallError",
    "SchemaError",
    "get_classifier",
]
