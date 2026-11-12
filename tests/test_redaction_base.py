import pytest

from complaint_intake.redaction.base import (
    PERSON,
    PHONE_NUMBER,
    Span,
    apply_spans,
    chunk_text,
    merge_spans,
    propagate_names,
)


def test_merge_spans_sorts_merges_and_keeps_first_tag():
    spans = [Span(10, 15, PHONE_NUMBER), Span(0, 4, PERSON), Span(2, 6, "PII"), Span(5, 5, "X")]
    assert merge_spans(spans) == [Span(0, 6, PERSON), Span(10, 15, PHONE_NUMBER)]


def test_merge_keeps_adjacent_spans_separate():
    assert merge_spans([Span(0, 3, "A"), Span(3, 6, "B")]) == [Span(0, 3, "A"), Span(3, 6, "B")]


def test_apply_spans_replaces_with_tags():
    text = "Call Ana Diaz at 555-0100 now"
    spans = [Span(5, 13, PERSON), Span(17, 25, PHONE_NUMBER)]
    assert apply_spans(text, spans) == "Call [PERSON] at [PHONE_NUMBER] now"


@pytest.mark.parametrize("size", [1, 7, 40, 200])
def test_chunks_cover_text_exactly_and_respect_limit(size):
    text = "First sentence here. Second one is a bit longer!\n\nNew paragraph, with commas. " * 5
    chunks = chunk_text(text, size)
    assert "".join(c for _, c in chunks) == text
    assert all(len(c) <= size for _, c in chunks)
    offset = 0
    for start, chunk in chunks:
        assert start == offset
        offset += len(chunk)


def test_chunks_prefer_sentence_boundaries():
    text = "Alpha beta gamma. " * 10
    chunks = chunk_text(text, 50)
    assert all(c.endswith(". ") for _, c in chunks[:-1])


def test_chunk_hard_cut_without_boundaries():
    assert [c for _, c in chunk_text("x" * 25, 10)] == ["x" * 10, "x" * 10, "x" * 5]


def test_empty_text_is_one_empty_chunk():
    assert chunk_text("", 10) == [(0, "")]


def test_propagate_names_catches_repeat_and_first_name():
    text = "My husband Tobias Becker and I (Helena Becker) were locked out."
    detected = [Span(11, 24, PERSON)]  # only "Tobias Becker"
    result = apply_spans(text, detected + propagate_names(text, detected))
    assert result == "My husband [PERSON] and I ([PERSON]) were locked out."


def test_propagate_names_skips_titles_and_pronouns():
    text = "Ms Becker called. I said Becker was right."
    detected = [Span(3, 9, PERSON)]
    extra = propagate_names(text, detected)
    assert [text[s.start : s.end] for s in extra] == ["Becker"]  # "said" is lowercase, kept


def test_propagate_names_noop_without_person_spans():
    assert propagate_names("Call 555-0100", [Span(5, 13, PHONE_NUMBER)]) == []
