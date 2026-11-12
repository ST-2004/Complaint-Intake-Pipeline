"""Run a redactor over the seeded samples and report leaks by PII type (M1 check).

    python tasks.py pii-check                      # provider from .env (azure by default)
    python tasks.py pii-check --provider presidio  # local, no cloud
    python tasks.py pii-check --show --enrich      # print redacted text and signals

Exit code 1 if any seeded value survives redaction.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from complaint_intake.config import PiiProvider, Settings
from complaint_intake.redaction import RedactionError, get_redactor
from complaint_intake.redaction.leaks import Leak, SeededValue, find_leaks

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples" / "pii_samples.jsonl"


@dataclass
class Sample:
    id: str
    text: str
    seeded: list[SeededValue]


def load_samples(path: Path = SAMPLES) -> list[Sample]:
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            seeded = [SeededValue(s["type"], s["value"]) for s in row["seeded"]]
            samples.append(Sample(row["id"], row["text"], seeded))
    return samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", choices=[p.value for p in PiiProvider])
    parser.add_argument("--show", action="store_true", help="print the redacted text")
    parser.add_argument("--enrich", action="store_true", help="also run sentiment/key phrases")
    args = parser.parse_args(argv)

    overrides = {"pii_provider": args.provider} if args.provider else {}
    settings = Settings(**overrides)
    redactor = get_redactor(settings)
    enricher = None
    if args.enrich:
        from complaint_intake.enrichment import get_enricher

        enricher = get_enricher(settings)

    samples = load_samples()
    seeded_by_type: Counter[str] = Counter()
    leaks_by_type: Counter[str] = Counter()
    failures = 0
    print(f"provider={redactor.name}  samples={len(samples)}\n")
    for sample in samples:
        seeded_by_type.update(s.type for s in sample.seeded)
        try:
            result = redactor.redact(sample.text)
        except RedactionError as exc:
            failures += 1
            print(f"{sample.id}  FAILED CLOSED: {exc}")
            continue
        leaks: list[Leak] = find_leaks(sample.seeded, result.text)
        leaks_by_type.update(leak.type for leak in leaks)
        status = "LEAK" if leaks else "ok  "
        print(f"{sample.id}  {status}  categories={list(result.categories)}")
        for leak in leaks:
            print(f"          survived: {leak.type} -> {list(leak.fragments)}")
        if args.show:
            print(f"          {result.text}")
        if enricher:
            sig = enricher.enrich(result.text)
            if sig.available:
                print(f"          sentiment={sig.sentiment} {sig.scores}")
                print(f"          key_phrases={list(sig.key_phrases)}")
            else:
                print(f"          enrichment unavailable: {sig.error}")

    print("\nLeaks by seeded type (values that survived / values seeded):")
    for kind in sorted(seeded_by_type):
        print(f"  {kind:<26} {leaks_by_type[kind]} / {seeded_by_type[kind]}")
    total_leaks, total_seeded = sum(leaks_by_type.values()), sum(seeded_by_type.values())
    print(f"  {'TOTAL':<26} {total_leaks} / {total_seeded}")
    if failures:
        print(f"\n{failures} sample(s) failed closed (redaction error).")
    ok = total_leaks == 0 and failures == 0
    print("\nPII CHECK " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
