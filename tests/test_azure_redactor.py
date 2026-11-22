"""AzureLanguageRedactor against a fake client that returns realistic SDK shapes."""

import re
from types import SimpleNamespace

import pytest

from complaint_intake.redaction.azure_language import AZURE_CATEGORY_TAGS, AzureLanguageRedactor
from complaint_intake.redaction.base import RedactionError

# Fake detector: the "service" finds these exact strings.
KNOWN = {
    "Priya Raman": "Person",
    "416-555-0187": "PhoneNumber",
    "4111 1111 1111 1111": "CreditCardNumber",
}


def entity(category, offset, length):
    return SimpleNamespace(category=category, offset=offset, length=length, confidence_score=0.9)


class FakeClient:
    def __init__(self, *, fail=None, doc_error=False, drop_entities=False):
        self.calls = []
        self.fail = fail
        self.doc_error = doc_error
        self.drop_entities = drop_entities

    def recognize_pii_entities(self, docs, **kwargs):
        self.calls.append((list(docs), kwargs))
        if self.fail:
            raise self.fail
        out = []
        for doc in docs:
            if self.doc_error:
                out.append(
                    SimpleNamespace(is_error=True, error=SimpleNamespace(code="InvalidDocument"))
                )
                continue
            ents, redacted = [], doc
            for value, cat in KNOWN.items():
                for m in re.finditer(re.escape(value), doc):
                    ents.append(entity(cat, m.start(), len(value)))
                    redacted = redacted[: m.start()] + "*" * len(value) + redacted[m.end() :]
            out.append(
                SimpleNamespace(
                    is_error=False,
                    entities=[] if self.drop_entities else ents,
                    redacted_text=redacted,
                )
            )
        return out


TEXT = "I am Priya Raman, card 4111 1111 1111 1111 was charged. Call 416-555-0187."


def test_redacts_with_tags_and_reports_categories_only():
    client = FakeClient()
    result = AzureLanguageRedactor(client).redact(TEXT)
    assert result.text == "I am [PERSON], card [CARD_NUMBER] was charged. Call [PHONE_NUMBER]."
    assert result.categories == ("CARD_NUMBER", "PERSON", "PHONE_NUMBER")
    assert result.entity_count == 3
    for value in KNOWN:
        assert value not in repr(result)


def test_sends_category_filter_and_disables_service_logs():
    client = FakeClient()
    AzureLanguageRedactor(client).redact(TEXT)
    _, kwargs = client.calls[0]
    assert kwargs["disable_service_logs"] is True
    assert set(kwargs["categories_filter"]) == set(AZURE_CATEGORY_TAGS)
    assert "Organization" not in kwargs["categories_filter"]


def test_long_text_is_chunked_batched_and_offsets_mapped():
    text = ("Filler sentence about a fee. " * 12) + "Priya Raman wrote this."
    client = FakeClient()
    result = AzureLanguageRedactor(client, max_chars=60, batch_size=2).redact(text)
    assert result.chunks > 2
    assert all(len(docs) <= 2 for docs, _ in client.calls)
    assert result.text.endswith("[PERSON] wrote this.")
    assert "Priya" not in result.text


def test_masked_text_is_redacted_even_without_entities():
    result = AzureLanguageRedactor(FakeClient(drop_entities=True)).redact(TEXT)
    for value in KNOWN:
        assert value not in result.text
    assert "[PII]" in result.text


@pytest.mark.parametrize(
    "client",
    [FakeClient(fail=TimeoutError("read timed out")), FakeClient(doc_error=True)],
    ids=["exception", "document-error"],
)
def test_fails_closed_without_echoing_text(client):
    with pytest.raises(RedactionError) as info:
        AzureLanguageRedactor(client).redact(TEXT)
    message = str(info.value)
    assert "Priya" not in message and "4111" not in message
    assert info.value.__cause__ is None


def test_signoff_name_missed_by_the_service_is_still_redacted():
    # M4 baseline: Azure left "Please investigate. Owen Mand" unredacted.
    text = "Someone opened a card in my name. Please investigate. Owen Mand"
    result = AzureLanguageRedactor(FakeClient()).redact(text)  # fake finds no name here
    assert "Owen" not in result.text and "Mand" not in result.text
    assert "PERSON" in result.categories


def test_empty_text_skips_the_service():
    client = FakeClient()
    result = AzureLanguageRedactor(client).redact("   ")
    assert client.calls == [] and result.entity_count == 0
