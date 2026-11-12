"""PII redaction with Azure AI Language (primary provider)."""

from __future__ import annotations

import logging
from itertools import batched

from complaint_intake.redaction.base import (
    ACCOUNT_NUMBER,
    ADDRESS,
    CARD_NUMBER,
    EMAIL,
    GOVERNMENT_ID,
    IP_ADDRESS,
    OTHER_PII,
    PERSON,
    PHONE_NUMBER,
    RedactionError,
    RedactionResult,
    Span,
    apply_spans,
    chunk_text,
    merge_spans,
    propagate_names,
)

# Category filter: only these Azure categories are requested and redacted.
# Deliberately NOT redacted, because triage needs them and they rarely identify a
# person on their own: Organization (the bank, merchants), Date, Age, Quantity
# (amounts), URL. This is a documented trade-off: a date of birth will survive.
AZURE_CATEGORY_TAGS: dict[str, str] = {
    "Person": PERSON,
    "PhoneNumber": PHONE_NUMBER,
    "Email": EMAIL,
    "Address": ADDRESS,
    "IPAddress": IP_ADDRESS,
    "CreditCardNumber": CARD_NUMBER,
    "USBankAccountNumber": ACCOUNT_NUMBER,
    "CABankAccountNumber": ACCOUNT_NUMBER,
    "InternationalBankingAccountNumber": ACCOUNT_NUMBER,
    "ABARoutingNumber": ACCOUNT_NUMBER,
    "SWIFTCode": ACCOUNT_NUMBER,
    "USSocialSecurityNumber": GOVERNMENT_ID,
    "USIndividualTaxpayerIdentification": GOVERNMENT_ID,
    "USDriversLicenseNumber": GOVERNMENT_ID,
    "USUKPassportNumber": GOVERNMENT_ID,
    "CASocialInsuranceNumber": GOVERNMENT_ID,
    "CADriversLicenseNumber": GOVERNMENT_ID,
    "CAPassportNumber": GOVERNMENT_ID,
    "CAHealthServiceNumber": GOVERNMENT_ID,
    "CAPersonalHealthIdentification": GOVERNMENT_ID,
}

# The PII call carries RAW text. azure-core's HTTP logging can include request
# details at DEBUG, so keep these loggers at WARNING regardless of app log level (P2).
for _name in ("azure.core.pipeline.policies.http_logging_policy", "azure.ai.textanalytics"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# Service limits for synchronous PII calls (verify on the current Language docs):
# 5,120 characters per document, 5 documents per request.
MAX_CHARS = 5000
MAX_DOCS_PER_REQUEST = 5


class AzureLanguageRedactor:
    name = "azure_language"

    def __init__(
        self,
        client,
        *,
        language: str = "en",
        max_chars: int = MAX_CHARS,
        batch_size: int = MAX_DOCS_PER_REQUEST,
    ) -> None:
        self._client = client
        self._language = language
        self._max_chars = max_chars
        self._batch_size = batch_size

    def redact(self, text: str) -> RedactionResult:
        if not text.strip():
            return RedactionResult(text, (), 0, self.name, chunks=0)

        chunks = chunk_text(text, self._max_chars)
        spans: list[Span] = []
        try:
            for batch in batched(chunks, self._batch_size):
                results = self._client.recognize_pii_entities(
                    [chunk for _, chunk in batch],
                    language=self._language,
                    categories_filter=list(AZURE_CATEGORY_TAGS),
                    disable_service_logs=True,
                )
                if len(results) != len(batch):
                    raise RedactionError("azure_language: result count mismatch")
                for (offset, chunk), doc in zip(batch, results, strict=True):
                    if doc.is_error:
                        raise RedactionError(f"azure_language: document error {doc.error.code}")
                    for entity in doc.entities:
                        start = offset + entity.offset
                        tag = AZURE_CATEGORY_TAGS.get(entity.category, OTHER_PII)
                        spans.append(Span(start, start + entity.length, tag))
                    spans.extend(_masked_spans(chunk, doc.redacted_text, offset))
        except RedactionError:
            raise
        except Exception as exc:
            # `from None`: SDK exceptions are not expected to echo request text, but
            # we do not chain them, so nothing from the call can reach a log.
            raise RedactionError(f"azure_language: {type(exc).__name__}") from None

        merged = merge_spans(spans + propagate_names(text, spans))
        return RedactionResult(
            text=apply_spans(text, merged),
            categories=tuple(sorted({s.tag for s in merged})),
            entity_count=len(merged),
            provider=self.name,
            chunks=len(chunks),
        )


def _masked_spans(chunk: str, redacted: str | None, offset: int) -> list[Span]:
    """Belt and braces: any run the service masked with '*' must be redacted too,
    even if an entity offset were wrong. Skipped if lengths differ."""
    if not redacted or len(redacted) != len(chunk):
        return []
    spans: list[Span] = []
    run_start: int | None = None
    for i, (orig, red) in enumerate(zip(chunk, redacted, strict=True)):
        masked = red == "*" and orig != "*"
        if masked and run_start is None:
            run_start = i
        elif not masked and run_start is not None:
            spans.append(Span(offset + run_start, offset + i, OTHER_PII))
            run_start = None
    if run_start is not None:
        spans.append(Span(offset + run_start, offset + len(chunk), OTHER_PII))
    return spans
