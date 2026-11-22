"""Metrics for the evaluation report (plan section 10). Pure functions, unit-tested.

Every rate comes with its counts: with 30 held-out cases one mistake moves a
score by more than three points, so the report always shows k/n.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from complaint_intake.schemas import Category, Severity

NONE_LABEL = "NONE"  # prediction when the pipeline produced no category (R7/R8)
SEVERITIES = [s.value for s in Severity]
HIGH_PLUS = {"HIGH", "CRITICAL"}


@dataclass(frozen=True)
class Ratio:
    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    def __str__(self) -> str:
        return f"{self.value:.2f} ({self.k}/{self.n})" if self.n else "n/a (0/0)"


@dataclass(frozen=True)
class ClassScores:
    label: str
    precision: float
    recall: float
    f1: float
    support: int


def confusion(truth: list[str], pred: list[str], labels: list[str]) -> dict[str, Counter]:
    matrix: dict[str, Counter] = {t: Counter() for t in labels}
    for t, p in zip(truth, pred, strict=True):
        matrix.setdefault(t, Counter())[p] += 1
    return matrix


def per_class(truth: list[str], pred: list[str], labels: list[str]) -> list[ClassScores]:
    scores = []
    for label in labels:
        tp = sum(t == label and p == label for t, p in zip(truth, pred, strict=True))
        fp = sum(t != label and p == label for t, p in zip(truth, pred, strict=True))
        fn = sum(t == label and p != label for t, p in zip(truth, pred, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(ClassScores(label, precision, recall, f1, tp + fn))
    return scores


def macro_f1(truth: list[str], pred: list[str], labels: list[str] | None = None) -> float:
    """Mean F1 over the classes that appear in the truth (support > 0)."""
    labels = labels or sorted(set(truth))
    present = [s for s in per_class(truth, pred, labels) if s.support > 0]
    return sum(s.f1 for s in present) / len(present) if present else 0.0


def accuracy(truth: list[str], pred: list[str]) -> Ratio:
    return Ratio(sum(t == p for t, p in zip(truth, pred, strict=True)), len(truth))


def severity_off_by_one(truth: list[str], pred: list[str]) -> Ratio:
    """Predictions exactly one level away (e.g. HIGH vs CRITICAL). Missing = not counted."""
    k = sum(
        p in SEVERITIES and abs(SEVERITIES.index(t) - SEVERITIES.index(p)) == 1
        for t, p in zip(truth, pred, strict=True)
    )
    return Ratio(k, len(truth))


def severity_under(truth: list[str], pred: list[str]) -> Ratio:
    """Predicted lower than the label (the costly direction). Missing counts as under."""
    k = sum(
        p not in SEVERITIES or SEVERITIES.index(p) < SEVERITIES.index(t)
        for t, p in zip(truth, pred, strict=True)
    )
    return Ratio(k, len(truth))


def recall_of(truth: list[bool], pred: list[bool]) -> Ratio:
    positives = [p for t, p in zip(truth, pred, strict=True) if t]
    return Ratio(sum(positives), len(positives))


def precision_of(truth: list[bool], pred: list[bool]) -> Ratio:
    flagged = [t for t, p in zip(truth, pred, strict=True) if p]
    return Ratio(sum(flagged), len(flagged))


def high_plus_recall(truth: list[str], pred: list[str]) -> Ratio:
    return recall_of([t in HIGH_PLUS for t in truth], [p in HIGH_PLUS for p in pred])


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..1)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


# --------------------------------------------------------------- groundedness

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
# Capitalised words a summary may use that need not appear in the complaint.
_ALLOWED_CAPS = {
    "customer",
    "customers",
    "the",
    "a",
    "an",
    "they",
    "their",
    "he",
    "she",
    "his",
    "her",
    "i",
    "it",
    "this",
    "that",
    "bank",
    "account",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "person",
    "phone_number",
    "email",
    "address",
    "card_number",
    "account_number",
    "government_id",
    "pii",
    "ip_address",
    "atm",
    "pin",
    "nsf",
    "app",
    "sin",
    "visa",
    "mastercard",
    "english",
    "french",
}


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER.findall(text):
        value = raw.replace(",", "").rstrip(".")
        out.add(value[:-3] if value.endswith(".00") else value)
    return out


def ungrounded_terms(summary: str, complaint: str) -> list[str]:
    """Numbers and proper nouns in the summary that are not in the complaint.

    A cheap automatic check for invented facts. Proper nouns are capitalised
    words that are not the first word of a sentence and not common words.
    """
    problems = sorted(_numbers(summary) - _numbers(complaint))
    complaint_words = {w.lower() for w in _WORD.findall(complaint)}
    sentence_start = True
    for word in re.findall(r"[A-Za-z][A-Za-z'\-]*|[.!?]", summary):
        if word in {".", "!", "?"}:
            sentence_start = True
            continue
        if (
            not sentence_start
            and word[0].isupper()
            and word.lower() not in _ALLOWED_CAPS
            and word.lower() not in complaint_words
        ):
            problems.append(word)
        sentence_start = False
    return problems


CATEGORY_LABELS = [c.value for c in Category]
