"""M2 check: redact -> enrich -> classify the 10 labelled samples, then report.

    python tasks.py classify-check            # needs the environment up (infra-up + env)
    python tasks.py classify-check --show     # also print summaries and model review reasons

Definition of done for M2: every sample returns schema-valid output after at most
one retry, with the prompt version recorded. Accuracy is printed for information;
it is measured properly on the full dataset in M4 (n=10 says very little).
Exit code 1 if any sample fails classification.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from complaint_intake.classifier import ClassificationError, get_classifier
from complaint_intake.config import Settings
from complaint_intake.enrichment import get_enricher
from complaint_intake.redaction import RedactionError, get_redactor

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples" / "classify_samples.jsonl"


@dataclass
class Labelled:
    id: str
    text: str
    category: str
    severity: str
    needs_review: bool


def load_labelled(path: Path = SAMPLES) -> list[Labelled]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            lab = r["label"]
            rows.append(
                Labelled(r["id"], r["text"], lab["category"], lab["severity"], lab["needs_review"])
            )
    return rows


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)

    settings = Settings()
    redactor, enricher, classifier = (
        get_redactor(settings),
        get_enricher(settings),
        get_classifier(settings),
    )
    samples = load_labelled()
    print(
        f"prompt={classifier.prompt.version} (sha {classifier.prompt.sha256})  "
        f"deployment={settings.model_deployment}  pii={redactor.name}  n={len(samples)}\n"
    )
    print(f"{'id':<7} {'category':<20} {'sev':<9} {'review':<7} {'try':<4} {'ms':>6}  match")

    valid = first_try = cat_ok = sev_ok = 0
    review_needed = review_caught = 0
    latencies: list[float] = []
    tokens_in = tokens_out = 0
    cost = 0.0
    for s in samples:
        review_needed += s.needs_review
        try:
            redacted = redactor.redact(s.text)
            signals = enricher.enrich(redacted.text)
            out = classifier.classify(redacted.text, signals)
        except RedactionError as exc:
            print(f"{s.id:<7} FAILED CLOSED (redaction): {exc}")
            continue
        except ClassificationError as exc:
            print(
                f"{s.id:<7} -> HUMAN ({exc.reason}) after {exc.attempts} attempt(s): {exc.detail}"
            )
            tokens_in += exc.usage.prompt_tokens
            tokens_out += exc.usage.completion_tokens
            continue
        t = out.triage
        valid += 1
        first_try += out.first_attempt_valid
        cat_ok += t.category == s.category
        sev_ok += t.severity == s.severity
        review_caught += s.needs_review and t.requires_human_review
        latencies.append(out.latency_ms)
        tokens_in += out.usage.prompt_tokens
        tokens_out += out.usage.completion_tokens
        cost += out.cost_usd
        marks = ("C" if t.category == s.category else "c") + (
            "S" if t.severity == s.severity else "s"
        )
        extra = ""
        if t.injection_suspected or out.delimiter_tampering:
            extra += " injection"
        if t.distress_suspected:
            extra += " distress"
        print(
            f"{s.id:<7} {t.category:<20} {t.severity:<9} {str(t.requires_human_review):<7} "
            f"{out.attempts:<4} {out.latency_ms:>6.0f}  {marks}{extra}"
        )
        if t.category != s.category or t.severity != s.severity:
            print(f"        expected {s.category} / {s.severity}")
        if args.show:
            print(f"        summary: {t.summary}")
            print(f"        reasons: {t.review_reasons}  confidence={t.confidence:.2f}")

    n = len(samples)
    print(f"\nM2 results (n={n}; small sample, for a sanity check only)")
    print(f"  schema-valid            {valid}/{n}  (first attempt {first_try}/{n})")
    print(f"  category matches label  {cat_ok}/{n}")
    print(f"  severity matches label  {sev_ok}/{n}")
    print(
        f"  review flagged by model {review_caught}/{review_needed} of cases labelled needs-review"
    )
    if latencies:
        print(
            f"  latency ms              p50 {statistics.median(latencies):.0f}, "
            f"p95 {pct(latencies, 0.95):.0f}"
        )
    print(f"  tokens                  {tokens_in} in, {tokens_out} out")
    print(f"  est. cost               ${cost:.5f} total, ${cost / max(valid, 1):.6f} per complaint")
    ok = valid == n
    print("\nCLASSIFY CHECK " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
