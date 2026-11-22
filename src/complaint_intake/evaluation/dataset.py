"""Build the labelled synthetic dataset from hand-written situations.

    python -m complaint_intake.evaluation.dataset                 # write dev + held-out
    python -m complaint_intake.evaluation.dataset --relabel-sample
    python -m complaint_intake.evaluation.dataset --relabel-compare data/relabel_sample.jsonl

`data/situations.jsonl` holds 80 hand-written complaints with labels and PII
slots ({name}, {phone}, {email}, {card}, {account}, {address}, {sin}, {name2}).
This module fills the slots with seeded fake values, records every value it
planted (so the leak check is mechanical), and splits 5 dev / 3 held-out per
category. Same seed, same output, byte for byte.

Fake values are chosen so they belong to no one:
- phones: the 555-01xx range reserved for fiction, in several formats
- emails: reserved example.com / example.org / example.net domains
- cards: publicly documented test numbers (Luhn-valid)
- SINs: Luhn-valid, starting with 0 (a prefix never assigned)
- names and street addresses: Faker (en_CA, fr_CA, en_IN, es_MX, en_GB)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from complaint_intake.schemas import Category, Severity

ROOT = Path(__file__).resolve().parents[3]
SITUATIONS = ROOT / "data" / "situations.jsonl"
OUT_DIR = ROOT / "data" / "synthetic"
DEFAULT_SEED = 20261121
DEV_PER_CATEGORY = 5
LOCALES = ["en_CA", "fr_CA", "en_IN", "es_MX", "en_GB"]

TEST_CARDS = [
    "4111111111111111",
    "4012888888881881",
    "4242424242424242",
    "5555555555554444",
    "5105105105105100",
    "6011111111111117",
    "378282246310005",
    "371449635398431",
]
AREA_CODES = ["416", "647", "437", "905", "613", "604", "778", "514", "403", "902", "204", "306"]
EMAIL_DOMAINS = ["example.com", "example.org", "example.net"]
# Name parts that are also ordinary words would make the word-level leak check
# report false leaks ("Hope", "Will") or hide real ones. They are re-drawn.
COMMON_WORDS = {
    "hope",
    "will",
    "grace",
    "faith",
    "joy",
    "mark",
    "bill",
    "sue",
    "rose",
    "may",
    "june",
    "april",
    "august",
    "summer",
    "page",
    "bank",
    "case",
    "king",
    "street",
    "branch",
    "card",
    "young",
    "long",
    "small",
    "rich",
    "price",
    "money",
    "cash",
    "best",
    "love",
    "gay",
    "brown",
    "green",
    "white",
    "black",
    "wood",
    "hill",
    "lane",
    "park",
    "baker",
    "cook",
}
SLOT = re.compile(r"\{(name2|name|phone|email|card|account|address|sin)\}")
REVIEW_FLAGS = {"regulatory", "distress", "injection"}
ALWAYS_REVIEW = {Category.FRAUD_UNAUTHORIZED, Category.PRIVACY_DATA, Category.OTHER_UNCLEAR}


def guide_needs_review(category: str, severity: str, flags: list[str]) -> bool:
    """The needs_review rule from data/LABELING_GUIDE.md."""
    return (
        Category(category) in ALWAYS_REVIEW
        or Severity(severity) is Severity.CRITICAL
        or bool(REVIEW_FLAGS & set(flags))
    )


def luhn_check_digit(partial: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(partial)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def _ascii(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", folded.lower())


class FakePii:
    """Seeded fake PII. Every value is recorded with its type by the caller."""

    def __init__(self, seed: int) -> None:
        from faker import Faker

        self.rng = random.Random(seed)
        self.faker = Faker(LOCALES)
        self.faker.seed_instance(seed)
        self.address_faker = Faker("en_CA")
        self.address_faker.seed_instance(seed + 1)

    def name(self, avoid: set[str]) -> str:
        for _ in range(200):
            first, last = self.faker.first_name(), self.faker.last_name()
            parts = [p.lower() for p in re.findall(r"[^\W\d_]+", f"{first} {last}")]
            if all(len(p) > 2 and p not in COMMON_WORDS and p not in avoid for p in parts):
                return f"{first} {last}"
        raise RuntimeError("could not draw a usable name")

    def phone(self) -> str:
        area = self.rng.choice(AREA_CODES)
        line = f"01{self.rng.randint(0, 99):02d}"
        fmt = self.rng.choice(["{a}-555-{l}", "({a}) 555-{l}", "{a}.555.{l}", "{a} 555 {l}"])
        return fmt.format(a=area, l=line)

    def email(self, name: str | None) -> str:
        if name:
            first, *rest = name.split()
            local = f"{_ascii(first)[:1]}.{_ascii(rest[-1] if rest else first)}"
        else:
            local = f"customer{self.rng.randint(100, 999)}"
        return f"{local}{self.rng.randint(1, 99)}@{self.rng.choice(EMAIL_DOMAINS)}"

    def card(self) -> str:
        number = self.rng.choice(TEST_CARDS)
        sep = self.rng.choice([" ", "-", ""])
        groups = (
            [number[:4], number[4:10], number[10:]]
            if len(number) == 15
            else [number[i : i + 4] for i in range(0, 16, 4)]
        )
        return sep.join(groups)

    def account(self) -> str:
        if self.rng.random() < 0.5:
            return f"{self.rng.randint(0, 99999):05d}-{self.rng.randint(0, 9999999):07d}"
        return f"{self.rng.randint(10**9, 10**10 - 1)}"

    def sin(self) -> str:
        partial = "0" + "".join(str(self.rng.randint(0, 9)) for _ in range(7))
        digits = partial + luhn_check_digit(partial)
        sep = self.rng.choice([" ", "-"])
        return sep.join([digits[:3], digits[3:6], digits[6:]])

    def address(self) -> tuple[str, list[str]]:
        f = self.address_faker
        street, postcode = f.street_address(), f.postcode()
        full = f"{street}, {f.city()}, {f.province_abbr()} {postcode}"
        return full, [street, postcode]


@dataclass
class Situation:
    sid: str
    category: str
    severity: str
    needs_review: bool
    flags: list[str]
    text: str


def load_situations(path: Path = SITUATIONS) -> list[Situation]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(Situation(**json.loads(line)))
    return out


def fill(situation: Situation, pii: FakePii) -> dict:
    """Fill one situation's slots; return the record with its seeded values."""
    avoid = {w.lower() for w in re.findall(r"[^\W\d_]+", SLOT.sub(" ", situation.text))}
    seeded: list[dict] = []
    values: dict[str, str] = {}
    for slot in dict.fromkeys(SLOT.findall(situation.text)):
        if slot in ("name", "name2"):
            values[slot] = pii.name(avoid)
            seeded.append({"type": "Person", "value": values[slot]})
        elif slot == "phone":
            values[slot] = pii.phone()
            seeded.append({"type": "PhoneNumber", "value": values[slot]})
        elif slot == "email":
            values[slot] = pii.email(values.get("name"))
            seeded.append({"type": "Email", "value": values[slot]})
        elif slot == "card":
            values[slot] = pii.card()
            seeded.append({"type": "CreditCardNumber", "value": values[slot]})
        elif slot == "account":
            values[slot] = pii.account()
            seeded.append({"type": "BankAccountNumber", "value": values[slot]})
        elif slot == "sin":
            values[slot] = pii.sin()
            seeded.append({"type": "CASocialInsuranceNumber", "value": values[slot]})
        elif slot == "address":
            values[slot], parts = pii.address()
            seeded.extend({"type": "Address", "value": p} for p in parts)
    text = SLOT.sub(lambda m: values[m.group(1)], situation.text)
    return {
        "id": situation.sid,
        "text": text,
        "label": {
            "category": situation.category,
            "severity": situation.severity,
            "needs_review": situation.needs_review,
        },
        "flags": situation.flags,
        "seeded": seeded,
    }


def build(seed: int = DEFAULT_SEED, situations: list[Situation] | None = None):
    """Return (dev, heldout) record lists. Stratified: 5 dev / rest held-out per category."""
    situations = situations if situations is not None else load_situations()
    pii = FakePii(seed)
    records = [fill(s, pii) for s in situations]  # fill in file order: stable values
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cat[r["label"]["category"]].append(r)
    rng = random.Random(seed)
    dev, heldout = [], []
    for category in sorted(by_cat):
        group = sorted(by_cat[category], key=lambda r: r["id"])
        rng.shuffle(group)
        dev.extend(group[:DEV_PER_CATEGORY])
        heldout.extend(group[DEV_PER_CATEGORY:])
    return sorted(dev, key=lambda r: r["id"]), sorted(heldout, key=lambda r: r["id"])


def write_jsonl(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(data, encoding="utf-8", newline="\n")
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------- relabel check


def relabel_sample(seed: int, out: Path, fraction: float = 0.2) -> int:
    situations = load_situations()
    rng = random.Random(seed + 7)
    picked = sorted(rng.sample(situations, round(len(situations) * fraction)), key=lambda s: s.sid)
    rows = [
        {"sid": s.sid, "text": s.text, "category": "", "severity": "", "needs_review": None}
        for s in picked
    ]
    write_jsonl(out, rows)
    return len(rows)


def relabel_compare(path: Path) -> dict[str, tuple[int, int]]:
    truth = {s.sid: s for s in load_situations()}
    agree = {"category": 0, "severity": 0, "needs_review": 0}
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        s = truth[row["sid"]]
        n += 1
        agree["category"] += row["category"] == s.category
        agree["severity"] += row["severity"] == s.severity
        agree["needs_review"] += row["needs_review"] == s.needs_review
    return {k: (v, n) for k, v in agree.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--relabel-sample", action="store_true")
    parser.add_argument("--relabel-compare", type=Path)
    args = parser.parse_args(argv)

    if args.relabel_sample:
        out = ROOT / "data" / "relabel_sample.jsonl"
        n = relabel_sample(args.seed, out)
        print(f"wrote {n} unlabelled situations to {out.relative_to(ROOT)}; label them by hand")
        return 0
    if args.relabel_compare:
        for field_name, (ok, n) in relabel_compare(args.relabel_compare).items():
            print(f"{field_name:<14} {ok}/{n} agree")
        return 0

    dev, heldout = build(args.seed)
    dev_sha = write_jsonl(OUT_DIR / "dev.jsonl", dev)
    held_sha = write_jsonl(OUT_DIR / "heldout.jsonl", heldout)
    manifest = {
        "seed": args.seed,
        "situations_sha256": file_sha256(SITUATIONS),
        "dev": {"n": len(dev), "sha256": dev_sha},
        "heldout": {"n": len(heldout), "sha256": held_sha},
        "note": "Synthetic data only. Regenerate with the same seed to reproduce exactly.",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    seeded = sum(len(r["seeded"]) for r in dev + heldout)
    print(f"dev={len(dev)} heldout={len(heldout)} seeded PII values={seeded} seed={args.seed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
