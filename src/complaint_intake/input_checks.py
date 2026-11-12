"""Step 2: cheap checks on the raw text before anything is sent anywhere.

Runs in the raw zone but sends nothing out and stores nothing: it returns only
flags and counts. Flags raise scrutiny; they are signals, not verdicts (P5).
"""

from __future__ import annotations

from dataclasses import dataclass

from complaint_intake.rules_config import RulesConfig

EMPTY = "input_empty"
TOO_LONG = "input_too_long"
TOO_SHORT = "input_too_short"
LOW_QUALITY = "input_low_text_quality"
INJECTION = "injection_phrase"
LONG_CHUNKED = "input_chunked"
CHUNK_CHARS = 5000


@dataclass(frozen=True)
class InputCheck:
    char_count: int
    word_count: int
    flags: tuple[str, ...]

    @property
    def processable(self) -> bool:
        """False: do not call any service; a human handles it."""
        return EMPTY not in self.flags and TOO_LONG not in self.flags

    @property
    def injection_flagged(self) -> bool:
        return INJECTION in self.flags

    @property
    def unclear(self) -> bool:
        return TOO_SHORT in self.flags or LOW_QUALITY in self.flags


def check_input(text: str, config: RulesConfig) -> InputCheck:
    stripped = text.strip()
    chars, words = len(stripped), len(stripped.split())
    flags: list[str] = []
    if not stripped:
        return InputCheck(0, 0, (EMPTY,))
    if chars > config.max_chars:
        flags.append(TOO_LONG)
    elif chars > CHUNK_CHARS:
        flags.append(LONG_CHUNKED)
    if chars < config.min_chars or words < config.min_words:
        flags.append(TOO_SHORT)
    non_space = [ch for ch in stripped if not ch.isspace()]
    letters = sum(ch.isalpha() for ch in non_space)
    if non_space and letters / len(non_space) < config.min_letter_ratio:
        flags.append(LOW_QUALITY)
    if any(p.search(stripped) for p in config.injection):
        flags.append(INJECTION)
    return InputCheck(chars, words, tuple(flags))
