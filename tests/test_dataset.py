"""The synthetic dataset: reproducible, correctly split, labels follow the guide,
every planted value is real-looking but belongs to no one."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from complaint_intake.evaluation.dataset import (
    DEV_PER_CATEGORY,
    OUT_DIR,
    TEST_CARDS,
    build,
    file_sha256,
    guide_needs_review,
    load_situations,
)
from complaint_intake.redaction.presidio import luhn_valid
from complaint_intake.schemas import Category, Severity

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def split():
    return build()


def test_situations_cover_every_category_eight_times():
    counts = Counter(s.category for s in load_situations())
    assert set(counts) == {c.value for c in Category}
    assert set(counts.values()) == {8}


@pytest.mark.parametrize("situation", load_situations(), ids=lambda s: s.sid)
def test_labels_are_valid_and_follow_the_guide(situation):
    Category(situation.category)
    Severity(situation.severity)
    expected = guide_needs_review(situation.category, situation.severity, situation.flags)
    assert situation.needs_review == expected, "needs_review must follow LABELING_GUIDE.md"


def test_split_sizes_and_stratification(split):
    dev, heldout = split
    assert (len(dev), len(heldout)) == (50, 30)
    assert set(Counter(r["label"]["category"] for r in dev).values()) == {DEV_PER_CATEGORY}
    assert not {r["id"] for r in dev} & {r["id"] for r in heldout}


def test_generation_is_reproducible(split):
    assert build() == split


def test_committed_files_match_the_generator(split):
    """data/synthetic/* must be what `generate-data` produces (no hand edits)."""
    manifest = json.loads((OUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    for name, rows in zip(("dev", "heldout"), split, strict=True):
        on_disk = [
            json.loads(x)
            for x in (OUT_DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert on_disk == rows
        assert file_sha256(OUT_DIR / f"{name}.jsonl") == manifest[name]["sha256"]


def test_no_slots_left_and_every_seeded_value_is_in_the_text(split):
    for r in split[0] + split[1]:
        assert not re.search(r"\{[a-z0-9]+\}", r["text"])
        for s in r["seeded"]:
            assert s["value"] in r["text"], (r["id"], s)


def test_fake_values_belong_to_no_one(split):
    seeded = [s for r in split[0] + split[1] for s in r["seeded"]]
    for s in seeded:
        digits = re.sub(r"\D", "", s["value"])
        if s["type"] == "PhoneNumber":
            assert digits[3:6] == "555" and digits[6:8] == "01"
        elif s["type"] == "Email":
            assert s["value"].split("@")[1] in {"example.com", "example.org", "example.net"}
        elif s["type"] == "CreditCardNumber":
            assert digits in TEST_CARDS and luhn_valid(digits)
        elif s["type"] == "CASocialInsuranceNumber":
            assert digits.startswith("0") and luhn_valid(digits)


def test_names_are_not_ordinary_words_in_their_own_complaint(split):
    for r in split[0] + split[1]:
        # Emails are built from the name on purpose (realistic), so remove every
        # seeded value and check only the ordinary words that remain.
        rest = r["text"]
        for other in r["seeded"]:
            rest = rest.replace(other["value"], " ")
        rest = rest.lower()
        for s in r["seeded"]:
            if s["type"] == "Person":
                for part in s["value"].lower().split():
                    assert not re.search(rf"(?<![a-z]){re.escape(part)}(?![a-z])", rest), (
                        r["id"],
                        part,
                    )
