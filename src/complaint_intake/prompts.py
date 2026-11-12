"""Versioned prompts and the message builder.

The complaint is untrusted (principle P5). It goes in the user message between
<complaint> tags, after the fixed instructions in the system message. If the text
itself contains our delimiter tags, they are neutralised so the customer cannot
"close" the data block and write instructions after it (spotlighting).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_DELIMITER = re.compile(r"<\s*/?\s*(complaint|signals)\b[^>]*>", re.IGNORECASE)
NEUTRALISED = "[removed-tag]"


@dataclass(frozen=True)
class Prompt:
    version: str  # file stem, e.g. "classify_v1"
    text: str
    sha256: str  # first 12 hex chars; changes if the file is edited without a new version

    @classmethod
    def from_text(cls, version: str, text: str) -> Prompt:
        return cls(version, text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])


@lru_cache(maxsize=8)
def load_prompt(version: str, directory: Path = PROMPTS_DIR) -> Prompt:
    path = directory / f"{version}.md"
    if not re.fullmatch(r"[a-z0-9_]+", version) or not path.is_file():
        raise FileNotFoundError(f"prompt '{version}' not found in {directory}")
    return Prompt.from_text(version, path.read_text(encoding="utf-8").strip())


def neutralise_delimiters(text: str) -> tuple[str, bool]:
    """Replace any <complaint>/<signals> tags inside untrusted text."""
    cleaned, count = _DELIMITER.subn(NEUTRALISED, text)
    return cleaned, count > 0


@dataclass(frozen=True)
class BuiltMessages:
    messages: list[dict[str, str]]
    delimiter_tampering: bool  # the text contained our delimiter tags


def build_messages(
    prompt: Prompt,
    redacted_text: str,
    *,
    sentiment: str | None = None,
    key_phrases: tuple[str, ...] | list[str] = (),
    flags: tuple[str, ...] | list[str] = (),
) -> BuiltMessages:
    """System = fixed instructions; user = signals + delimited complaint (data only)."""
    complaint, tampered = neutralise_delimiters(redacted_text)
    phrases = [neutralise_delimiters(p)[0] for p in key_phrases]
    signal_lines = [
        f"sentiment: {sentiment or 'unavailable'}",
        f"key_phrases: {', '.join(phrases) if phrases else 'none'}",
    ]
    if flags:
        signal_lines.append(f"input_flags: {', '.join(flags)}")
    user = (
        "Classify the complaint below.\n\n"
        "<signals>\n" + "\n".join(signal_lines) + "\n</signals>\n\n"
        "<complaint>\n" + complaint + "\n</complaint>"
    )
    return BuiltMessages(
        messages=[
            {"role": "system", "content": prompt.text},
            {"role": "user", "content": user},
        ],
        delimiter_tampering=tampered,
    )
