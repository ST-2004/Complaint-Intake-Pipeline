"""PII redaction with Microsoft Presidio (local fallback, no cloud calls).

Used when Azure AI Language is unavailable in a subscription (PII_PROVIDER=presidio).
Presidio ships no Canadian recognizers, so this module adds SIN, postal code,
street address and account-number patterns. NER for names and places comes from
a spaCy model; the small model is the default and is weaker than Azure.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from complaint_intake.redaction.base import (
    ACCOUNT_NUMBER,
    ADDRESS,
    CARD_NUMBER,
    EMAIL,
    GOVERNMENT_ID,
    IP_ADDRESS,
    PERSON,
    PHONE_NUMBER,
    RedactionError,
    RedactionResult,
    Span,
    apply_spans,
    merge_spans,
    propagate_names,
)

PRESIDIO_ENTITY_TAGS: dict[str, str] = {
    "PERSON": PERSON,
    "PHONE_NUMBER": PHONE_NUMBER,
    "EMAIL_ADDRESS": EMAIL,
    "LOCATION": ADDRESS,
    "CA_POSTAL_CODE": ADDRESS,
    "STREET_ADDRESS": ADDRESS,
    "IP_ADDRESS": IP_ADDRESS,
    "CREDIT_CARD": CARD_NUMBER,
    "IBAN_CODE": ACCOUNT_NUMBER,
    "US_BANK_NUMBER": ACCOUNT_NUMBER,
    "BANK_ACCOUNT": ACCOUNT_NUMBER,
    "CA_SIN": GOVERNMENT_ID,
    "US_SSN": GOVERNMENT_ID,
    "US_ITIN": GOVERNMENT_ID,
    "US_DRIVER_LICENSE": GOVERNMENT_ID,
    "US_PASSPORT": GOVERNMENT_ID,
    "UK_NHS": GOVERNMENT_ID,
}

DEFAULT_SCORE_THRESHOLD = 0.3

# Presidio's DEBUG logs print the words around each match ("Context list is: ...
# s.gallagher@example.net email"), i.e. raw PII. Found by the M3 no-PII-in-logs
# test. Pin its logger to WARNING so app-level DEBUG logging cannot leak it (P2).
logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or len(digits) < 2:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _custom_recognizers():
    from presidio_analyzer import Pattern, PatternRecognizer

    class CaSinRecognizer(PatternRecognizer):
        """Canadian Social Insurance Number: 9 digits, Luhn checksum."""

        def validate_result(self, pattern_text: str) -> bool:
            return luhn_valid("".join(ch for ch in pattern_text if ch.isdigit()))

    return [
        CaSinRecognizer(
            supported_entity="CA_SIN",
            patterns=[Pattern("ca_sin", r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b", 0.5)],
            context=["sin", "social insurance"],
        ),
        PatternRecognizer(
            supported_entity="CA_POSTAL_CODE",
            patterns=[Pattern("ca_postal", r"\b[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d\b", 0.6)],
        ),
        PatternRecognizer(
            supported_entity="STREET_ADDRESS",
            patterns=[
                Pattern(
                    "street",
                    r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s+){1,3}"
                    r"(?:Street|St|Avenue|Ave|Road|Rd|Crescent|Cres|Drive|Dr|Boulevard|Blvd"
                    r"|Lane|Ln|Court|Ct|Way|Place|Pl|Terrace|Trail|Parkway)\b\.?",
                    0.6,
                )
            ],
        ),
        PatternRecognizer(
            supported_entity="BANK_ACCOUNT",
            # Long digit runs, optionally grouped. Low base score; context words
            # ("account", "chequing") raise it above the threshold.
            patterns=[Pattern("account", r"\b\d{3,6}(?:[ -]?\d{2,6}){1,3}\b", 0.1)],
            context=["account", "acct", "chequing", "checking", "savings", "transit"],
        ),
    ]


@lru_cache(maxsize=2)
def build_analyzer(model: str = "en_core_web_sm"):
    """Build (once per model) a Presidio analyzer with the custom recognizers."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": model}],
        }
    ).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    for recognizer in _custom_recognizers():
        analyzer.registry.add_recognizer(recognizer)
    return analyzer


class PresidioRedactor:
    name = "presidio"

    def __init__(
        self,
        analyzer=None,
        *,
        model: str = "en_core_web_sm",
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        self._analyzer = analyzer
        self._model = model
        self._threshold = score_threshold

    def redact(self, text: str) -> RedactionResult:
        if not text.strip():
            return RedactionResult(text, (), 0, self.name, chunks=0)
        try:
            analyzer = self._analyzer or build_analyzer(self._model)
            results = analyzer.analyze(
                text=text,
                language="en",
                entities=list(PRESIDIO_ENTITY_TAGS),
                score_threshold=self._threshold,
            )
        except Exception as exc:
            raise RedactionError(f"presidio: {type(exc).__name__}") from None

        spans = [
            Span(r.start, r.end, PRESIDIO_ENTITY_TAGS.get(r.entity_type, "PII")) for r in results
        ]
        merged = merge_spans(spans + propagate_names(text, spans))
        return RedactionResult(
            text=apply_spans(text, merged),
            categories=tuple(sorted({s.tag for s in merged})),
            entity_count=len(merged),
            provider=self.name,
        )
