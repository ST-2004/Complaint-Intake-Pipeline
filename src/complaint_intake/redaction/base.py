"""Redactor interface and the text utilities both providers share.

Only a redactor ever sees raw complaint text (principle P2). What comes out,
`RedactionResult`, holds the redacted text and the *categories* found, never the
detected values, so it is safe to log, store and send to the model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

# The tag vocabulary is provider-independent: swapping Azure for Presidio must not
# change what the model sees or what the audit log records.
PERSON = "PERSON"
PHONE_NUMBER = "PHONE_NUMBER"
EMAIL = "EMAIL"
ADDRESS = "ADDRESS"
CARD_NUMBER = "CARD_NUMBER"
ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
GOVERNMENT_ID = "GOVERNMENT_ID"
IP_ADDRESS = "IP_ADDRESS"
OTHER_PII = "PII"  # masked by the service but not mapped to a known category

TAGS = frozenset(
    {
        PERSON,
        PHONE_NUMBER,
        EMAIL,
        ADDRESS,
        CARD_NUMBER,
        ACCOUNT_NUMBER,
        GOVERNMENT_ID,
        IP_ADDRESS,
        OTHER_PII,
    }
)


class RedactionError(RuntimeError):
    """Redaction failed. Callers must fail closed: never send the text onward.

    Messages carry only an error type or code, never complaint text.
    """


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    tag: str


@dataclass(frozen=True)
class RedactionResult:
    text: str  # redacted text: the only form of the complaint allowed past this point
    categories: tuple[str, ...]  # sorted unique tags found, e.g. ("CARD_NUMBER", "PERSON")
    entity_count: int
    provider: str
    chunks: int = 1


class Redactor(Protocol):
    name: str

    def redact(self, text: str) -> RedactionResult:
        """Return redacted text, or raise RedactionError. Never return raw values."""
        ...


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    """Sort and merge overlapping spans. The earliest (then longest) span's tag wins."""
    merged: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, -s.end)):
        if span.end <= span.start:
            continue
        if merged and span.start < merged[-1].end:
            last = merged[-1]
            merged[-1] = Span(last.start, max(last.end, span.end), last.tag)
        else:
            merged.append(span)
    return merged


def apply_spans(text: str, spans: Iterable[Span]) -> str:
    """Replace each span with `[TAG]`."""
    out: list[str] = []
    pos = 0
    for span in merge_spans(spans):
        out.append(text[pos : span.start])
        out.append(f"[{span.tag}]")
        pos = span.end
    out.append(text[pos:])
    return "".join(out)


# One to three capitalised words; accented letters allowed (Renée, Núñez).
_NAME = (
    r"[A-ZÀ-Þ][a-zß-ÿ'\-]+"
    r"(?:\s[A-ZÀ-Þ][a-zß-ÿ'\-]+){1,2}"
)
_LEADS = (
    "name is ",
    "Name is ",
    "I'm ",
    "I am ",
    "This is ",
    "this is ",
    "Name ",
    "daughter ",
    "son ",
    "husband ",
    "wife ",
    "Regards, ",
    "Thanks, ",
    "Sincerely, ",
)
_SIGNOFF_PATTERNS = (
    # After a sentence end or line break, standing alone at the end or before a comma:
    # "... called five times. Aayush Stone" / "... ombudsman. Pratyush Guay, 416-..."
    re.compile(rf"(?<=[.!?] ){_NAME}(?=\s*(?:,|$))"),
    re.compile(rf"(?<=\n){_NAME}(?=\s*(?:,|$))"),
    re.compile(rf"^{_NAME}(?=\s*,)"),
    *(re.compile(rf"(?<={re.escape(lead)}){_NAME}") for lead in _LEADS),
)
_SIGNOFF_STOP = frozenset(
    {
        "thank you",
        "thanks again",
        "best regards",
        "kind regards",
        "maple harbour bank",
        "please help",
        "please advise",
    }
)


def signoff_name_spans(text: str) -> list[Span]:
    """PERSON spans for names that NER models miss because nothing marks them as names.

    Found in the M4 baseline: Azure AI Language left a bare sign-off ("Please
    investigate. Owen Mand") unredacted in 3 of 55 seeded names; spaCy did the same.
    Case-sensitive on purpose. Errs towards over-redaction (the safe direction).
    """
    spans: list[Span] = []
    for pattern in _SIGNOFF_PATTERNS:
        for m in pattern.finditer(text):
            if m.group().lower() not in _SIGNOFF_STOP:
                spans.append(Span(m.start(), m.end(), PERSON))
    return spans


_WORD = re.compile(r"[^\W\d_][\w'\-]*")
_NOT_NAMES = frozenset(
    {
        "i",
        "im",
        "my",
        "me",
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "mr",
        "mrs",
        "ms",
        "dr",
        "dear",
        "hi",
        "hello",
    }
)


def propagate_names(text: str, spans: list[Span]) -> list[Span]:
    """Extra PERSON spans for names a detector found once but missed elsewhere.

    1. Every word of a detected PERSON span is redacted wherever else it occurs
       ("Becker" found once -> every "Becker").
    2. A capitalised word directly before a propagated occurrence is treated as a
       first name ("Helena Becker" when only "Tobias Becker" was detected).
    Errs towards over-redaction, which is the safe direction for privacy.
    """
    covered = merge_spans(spans)
    names = {
        m.group().lower()
        for s in covered
        if s.tag == PERSON
        for m in _WORD.finditer(text[s.start : s.end])
        if len(m.group()) > 1 and m.group().lower() not in _NOT_NAMES
    }
    if not names:
        return []

    def inside(start: int, end: int) -> bool:
        return any(s.start <= start and end <= s.end for s in covered)

    extra: list[Span] = []
    for m in _WORD.finditer(text):
        if m.group().lower() not in names or inside(m.start(), m.end()):
            continue
        start = m.start()
        window_start = max(0, m.start() - 60)  # bounded look-behind keeps this linear
        before = re.search(r"([^\W\d_][\w'\-]*)\s+$", text[window_start : m.start()])
        if before:
            b_start, b_end = window_start + before.start(1), window_start + before.end(1)
            word = before.group(1)
            if word[0].isupper() and word.lower() not in _NOT_NAMES and not inside(b_start, b_end):
                start = b_start
        extra.append(Span(start, m.end(), PERSON))
    return extra


_CUT_PREFERENCE = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


def chunk_text(text: str, max_chars: int) -> list[tuple[int, str]]:
    """Split text into contiguous chunks of at most `max_chars`.

    Returns (offset, chunk) pairs that cover the text exactly. Cuts prefer
    paragraph, then sentence, then word boundaries so an entity is unlikely to
    be split across chunks (a split entity could escape detection).
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    chunks: list[tuple[int, str]] = []
    start = 0
    while len(text) - start > max_chars:
        window = text[start : start + max_chars]
        cut = _best_cut(window)
        chunks.append((start, window[:cut]))
        start += cut
    chunks.append((start, text[start:]))
    return chunks


def _best_cut(window: str) -> int:
    for sep in _CUT_PREFERENCE:
        idx = window.rfind(sep)
        if idx >= len(window) // 2:
            return idx + len(sep)
    return len(window)  # no boundary in the second half: hard cut
