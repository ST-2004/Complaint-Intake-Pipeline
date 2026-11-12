from types import SimpleNamespace

from complaint_intake.config import Settings
from complaint_intake.enrichment import (
    AzureLanguageEnricher,
    NullEnricher,
    aggregate_sentiment,
    clean_key_phrases,
    get_enricher,
)


def sent(label, pos, neu, neg):
    scores = SimpleNamespace(positive=pos, neutral=neu, negative=neg)
    return SimpleNamespace(is_error=False, sentiment=label, confidence_scores=scores)


class FakeClient:
    def __init__(self, sentiments, phrases, fail=None):
        self.sentiments, self.phrases, self.fail = sentiments, phrases, fail
        self.texts = []

    def analyze_sentiment(self, docs, **kw):
        if self.fail:
            raise self.fail
        self.texts.extend(docs)
        return self.sentiments[: len(docs)]

    def extract_key_phrases(self, docs, **kw):
        return [SimpleNamespace(is_error=False, key_phrases=p) for p in self.phrases[: len(docs)]]


def test_enrich_returns_signals_and_strips_tags():
    client = FakeClient(
        [sent("negative", 0.01, 0.09, 0.9)],
        [["unauthorized charges", "PERSON", "[CARD_NUMBER] statement", "Unauthorized charges"]],
    )
    signals = AzureLanguageEnricher(client).enrich("[PERSON] reports unauthorized charges.")
    assert signals.available and signals.sentiment == "negative"
    assert signals.scores["negative"] == 0.9
    assert signals.key_phrases == ("unauthorized charges",)


def test_enrichment_failure_degrades_instead_of_raising():
    client = FakeClient([], [], fail=TimeoutError("slow"))
    signals = AzureLanguageEnricher(client).enrich("some text")
    assert not signals.available and signals.error == "TimeoutError"


def test_document_error_degrades():
    client = FakeClient([SimpleNamespace(is_error=True, error=SimpleNamespace(code="Bad"))], [[]])
    signals = AzureLanguageEnricher(client).enrich("some text")
    assert not signals.available and signals.error == "doc_error:Bad"


def test_aggregate_sentiment_mixed_and_weighted():
    label, scores = aggregate_sentiment(
        [
            (100, "positive", {"positive": 0.9, "neutral": 0.1, "negative": 0.0}),
            (300, "negative", {"positive": 0.0, "neutral": 0.2, "negative": 0.8}),
        ]
    )
    assert label == "mixed"
    assert scores["negative"] == 0.6 and scores["positive"] == 0.225


def test_aggregate_same_labels_takes_max_mean():
    label, _ = aggregate_sentiment(
        [
            (10, "neutral", {"positive": 0.1, "neutral": 0.6, "negative": 0.3}),
            (10, "negative", {"positive": 0.0, "neutral": 0.3, "negative": 0.7}),
        ]
    )
    assert label == "negative"


def test_clean_key_phrases_limit():
    assert len(clean_key_phrases([f"phrase {i}" for i in range(30)], limit=5)) == 5


def test_get_enricher_without_endpoint_is_null():
    assert isinstance(get_enricher(Settings()), NullEnricher)
    assert NullEnricher().enrich("x").available is False
