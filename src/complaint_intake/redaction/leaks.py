"""Mechanical leak check: did any seeded PII value survive redaction?

Used by the smoke test, the unit/integration tests and (in M4) the evaluation
harness. Matching is deliberately strict so partial leaks count:
  - names: every word of the name is checked on its own ("Jordan Mitchell"
    leaks if "Mitchell" survives)
  - values with 4+ digits: compared with spaces, dashes, dots and brackets
    removed ("4111 1111 1111 1111" leaks as "4111-1111-1111-1111" too)
  - anything else: case-insensitive substring
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEPARATORS = re.compile(r"[\s\-().]")


@dataclass(frozen=True)
class SeededValue:
    type: str  # e.g. "Person", "PhoneNumber", "CreditCardNumber"
    value: str


@dataclass(frozen=True)
class Leak:
    """One seeded value that (at least partly) survived. Counted once per value."""

    type: str
    fragments: tuple[str, ...]  # surviving pieces (synthetic data, so safe to report)


def find_leaks(seeded: list[SeededValue], redacted_text: str) -> list[Leak]:
    leaks: list[Leak] = []
    lowered = redacted_text.lower()
    compact = _SEPARATORS.sub("", redacted_text).lower()
    for item in seeded:
        value = item.value.strip()
        if not value:
            continue
        if item.type == "Person":
            fragments = tuple(
                word
                for word in re.findall(r"[A-Za-z][A-Za-z'\-]+", value)
                if re.search(rf"(?<![A-Za-z]){re.escape(word.lower())}(?![A-Za-z])", lowered)
            )
        elif sum(ch.isdigit() for ch in value) >= 4:
            fragments = (value,) if _SEPARATORS.sub("", value).lower() in compact else ()
        else:
            fragments = (value,) if value.lower() in lowered else ()
        if fragments:
            leaks.append(Leak(item.type, fragments))
    return leaks
