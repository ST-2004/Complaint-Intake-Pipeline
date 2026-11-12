"""One call to each Azure service with Entra ID auth. Proves the environment works.

The PII probe uses an obviously synthetic sentence. Only entity *categories* and
the redacted text are printed, never the detected values (principle P2).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from complaint_intake.azure_auth import get_credential, hint_for
from complaint_intake.config import Settings
from complaint_intake.redaction.leaks import SeededValue, find_leaks

# Synthetic probe. 555-01xx numbers are reserved for fiction. The name must look like
# a real name: an obviously invented surname ("Fakename") is NOT detected as a Person
# and leaks, which the first live run showed. Each seeded *token* is checked.
PII_PROBE = "Hello, my name is Jordan Mitchell and you can call me at 555-0142."
PII_PROBE_SEEDED = [
    SeededValue("Person", "Jordan Mitchell"),
    SeededValue("PhoneNumber", "555-0142"),
]


@dataclass
class ProbeResult:
    service: str
    ok: bool
    detail: str
    hint: str | None = None


def probe_language(settings: Settings, credential=None) -> ProbeResult:
    from azure.ai.textanalytics import TextAnalyticsClient

    if not settings.azure_language_endpoint:
        return ProbeResult("language", False, "AZURE_LANGUAGE_ENDPOINT is not set")
    try:
        client = TextAnalyticsClient(
            endpoint=settings.azure_language_endpoint,
            credential=credential or get_credential(),
        )
        start = time.perf_counter()
        doc = client.recognize_pii_entities([PII_PROBE], language="en")[0]
        ms = (time.perf_counter() - start) * 1000
    except Exception as exc:  # noqa: BLE001 - surface any SDK/auth failure with a hint
        return ProbeResult(
            "language", False, type(exc).__name__ + ": " + str(exc)[:300], hint_for(exc)
        )
    if doc.is_error:
        return ProbeResult("language", False, f"{doc.error.code}: {doc.error.message}")

    leaked = find_leaks(PII_PROBE_SEEDED, doc.redacted_text)
    categories = sorted({e.category for e in doc.entities})
    detail = f"{ms:.0f} ms, categories={categories}, redacted={doc.redacted_text!r}"
    if leaked:
        return ProbeResult("language", False, f"{len(leaked)} seeded value(s) survived; {detail}")
    return ProbeResult("language", True, detail)


def probe_model(settings: Settings, credential=None) -> ProbeResult:
    from azure.identity import get_bearer_token_provider
    from openai import OpenAI

    missing = settings.missing("azure_ai_endpoint", "model_deployment")
    if missing:
        return ProbeResult("model", False, f"not set: {', '.join(missing)}")
    try:
        token_provider = get_bearer_token_provider(
            credential or get_credential(), settings.azure_token_scope
        )
        client = OpenAI(
            base_url=settings.azure_ai_endpoint,
            api_key=token_provider,
            timeout=settings.request_timeout_s,
            max_retries=1,
        )
        start = time.perf_counter()
        resp = client.chat.completions.create(
            model=settings.model_deployment,
            messages=[{"role": "user", "content": "Reply with exactly the word: OK"}],
            temperature=0,
            max_completion_tokens=5,
        )
        ms = (time.perf_counter() - start) * 1000
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(
            "model", False, type(exc).__name__ + ": " + str(exc)[:300], hint_for(exc)
        )
    text = (resp.choices[0].message.content or "").strip()
    usage = resp.usage
    tokens = f"{usage.prompt_tokens}+{usage.completion_tokens} tokens" if usage else "tokens n/a"
    return ProbeResult("model", True, f"{ms:.0f} ms, {tokens}, reply={text!r}, model={resp.model}")


def main() -> int:
    settings = Settings()
    credential = get_credential()
    results = [probe_language(settings, credential), probe_model(settings, credential)]
    for r in results:
        print(f"[{'PASS' if r.ok else 'FAIL'}] {r.service:8} {r.detail}")
        if r.hint:
            print(f"         hint: {r.hint}")
    ok = all(r.ok for r in results)
    print("\nSMOKE TEST " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
