"""Load the versioned rules configuration (config/<version>.toml)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@dataclass(frozen=True)
class RulesConfig:
    version: str
    min_chars: int
    min_words: int
    max_chars: int
    min_letter_ratio: float
    regulatory: re.Pattern[str]
    distress: re.Pattern[str]
    injection: tuple[re.Pattern[str], ...]


def _terms_regex(terms: list[str]) -> re.Pattern[str]:
    # Longest first so "legal action" wins over "legal"; word boundaries on both ends.
    escaped = sorted((re.escape(t.lower()) for t in terms), key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE)


def parse_rules(data: dict) -> RulesConfig:
    inp = data["input"]
    return RulesConfig(
        version=data["version"],
        min_chars=int(inp["min_chars"]),
        min_words=int(inp["min_words"]),
        max_chars=int(inp["max_chars"]),
        min_letter_ratio=float(inp["min_letter_ratio"]),
        regulatory=_terms_regex(data["r3_regulatory"]["terms"]),
        distress=_terms_regex(data["r4_distress"]["terms"]),
        injection=tuple(re.compile(p, re.IGNORECASE) for p in data["injection"]["patterns"]),
    )


@lru_cache(maxsize=4)
def load_rules(version: str, directory: Path = CONFIG_DIR) -> RulesConfig:
    path = directory / f"{version}.toml"
    if not re.fullmatch(r"[a-z0-9_]+", version) or not path.is_file():
        raise FileNotFoundError(f"rules config '{version}' not found in {directory}")
    config = parse_rules(tomllib.loads(path.read_text(encoding="utf-8")))
    if config.version != version:
        raise ValueError(f"{path.name} declares version {config.version!r}, expected {version!r}")
    return config
