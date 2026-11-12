"""Sentiment and key phrases, computed on REDACTED text only.

Enrichment produces signals for the rules (M3) and for reviewers. Unlike
redaction it does not fail closed: if it breaks, it returns
`Signals(available=False)` and the pipeline carries on, because the signals
only ever *add* scrutiny. The rules treat "unavailable" as a reason to look
harder, never as "all clear".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import batched
from typing import Protocol

from complaint_intake.config import Settings
from complaint_intake.redaction.base import TAGS, chunk_text

MAX_CHARS = 5000
MAX_DOCS_PER_REQUEST = 5
MAX_KEY_PHRASES = 20
_LABELS = ("positive", "neutral", "negative")


@dataclass(frozen=True)
class Signals:
    available: bool
    sentiment: str | None = None  # positive | neutral | negative | mixed
    scores: dict[str, float] = field(default_factory=dict)
    key_phrases: tuple[str, ...] = ()
    error: str | None = None


class Enricher(Protocol):
    def enrich(self, redacted_text: str) -> Signals: ...


class NullEnricher:
    """Used when no Language endpoint is configured (e.g. Presidio-only setups)."""

    def enrich(self, redacted_text: str) -> Signals:
        return Signals(available=False, error="enrichment_disabled")


class AzureLanguageEnricher:
    def __init__(
        self,
        client,
        *,
        language: str = "en",
        max_chars: int = MAX_CHARS,
        batch_size: int = MAX_DOCS_PER_REQUEST,
        max_phrases: int = MAX_KEY_PHRASES,
    ) -> None:
        self._client = client
        self._language = language
        self._max_chars = max_chars
        self._batch_size = batch_size
        self._max_phrases = max_phrases

    def enrich(self, redacted_text: str) -> Signals:
        if not redacted_text.strip():
            return Signals(available=False, error="empty_text")
        chunks = [chunk for _, chunk in chunk_text(redacted_text, self._max_chars)]
        sentiments: list[tuple[int, str, dict[str, float]]] = []
        phrases: list[str] = []
        try:
            for batch in batched(chunks, self._batch_size):
                docs = list(batch)
                kwargs = {"language": self._language, "disable_service_logs": True}
                sent = self._client.analyze_sentiment(docs, **kwargs)
                keys = self._client.extract_key_phrases(docs, **kwargs)
                for chunk, s, k in zip(docs, sent, keys, strict=True):
                    for result in (s, k):
                        if result.is_error:
                            return Signals(available=False, error=f"doc_error:{result.error.code}")
                    scores = {
                        label: float(getattr(s.confidence_scores, label)) for label in _LABELS
                    }
                    sentiments.append((len(chunk), s.sentiment, scores))
                    phrases.extend(k.key_phrases)
        except Exception as exc:
            return Signals(available=False, error=type(exc).__name__)

        label, scores = aggregate_sentiment(sentiments)
        return Signals(
            available=True,
            sentiment=label,
            scores=scores,
            key_phrases=clean_key_phrases(phrases, self._max_phrases),
        )


def aggregate_sentiment(
    parts: list[tuple[int, str, dict[str, float]]],
) -> tuple[str, dict[str, float]]:
    """Length-weighted mean of chunk scores. Opposite chunk labels make it 'mixed'."""
    if len(parts) == 1:
        _, label, scores = parts[0]
        return label, {k: round(v, 3) for k, v in scores.items()}
    total = sum(weight for weight, _, _ in parts) or 1
    scores = {lab: round(sum(w * s[lab] for w, _, s in parts) / total, 3) for lab in _LABELS}
    labels = {label for _, label, _ in parts}
    if "mixed" in labels or {"positive", "negative"} <= labels:
        return "mixed", scores
    return max(scores, key=scores.get), scores


_TAG_WORD = re.compile(r"\[?([A-Z_]+)\]?")


def clean_key_phrases(phrases: list[str], limit: int = MAX_KEY_PHRASES) -> tuple[str, ...]:
    """Drop redaction tags (e.g. 'PERSON') and duplicates; keep service order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for phrase in phrases:
        phrase = phrase.strip()
        words = phrase.split()
        if not words or any((m := _TAG_WORD.fullmatch(w)) and m.group(1) in TAGS for w in words):
            continue
        key = phrase.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(phrase)
    return tuple(cleaned[:limit])


def get_enricher(settings: Settings, *, credential=None) -> Enricher:
    if not settings.azure_language_endpoint:
        return NullEnricher()
    from complaint_intake.azure_clients import make_language_client

    return AzureLanguageEnricher(make_language_client(settings, credential))
