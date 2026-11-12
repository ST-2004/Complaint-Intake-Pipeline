"""Deterministic rules R1-R8 (rules_v1). The model suggests; these decide (P3).

Every rule can only ADD scrutiny: raise severity, require review, add a reason.
No rule can lower a severity or clear a review. `apply_rules` enforces that
invariant at the end, so a future rule cannot break it silently.

| Rule | Trigger                                           | Action                         |
|------|---------------------------------------------------|--------------------------------|
| R1   | category FRAUD_UNAUTHORIZED                       | severity >= HIGH; review       |
| R2   | category PRIVACY_DATA                             | review                         |
| R3   | regulator / ombudsman / lawyer / legal language   | review                         |
| R4   | distress terms in text or key phrases, or model   | CRITICAL; review               |
|      | distress flag                                     |                                |
| R5   | injection: model flag, input flag, delimiter tags,| review                         |
|      | or platform jailbreak / indirect-attack filter    |                                |
| R6   | OTHER_UNCLEAR, too short, noise, empty, too long  | review                         |
| R7   | model output invalid after retry, blocked, failed | review (no model result)       |
| R8   | PII redaction failed                              | review; model never called     |
"""

from __future__ import annotations

from dataclasses import dataclass

from complaint_intake.enrichment import Signals
from complaint_intake.input_checks import InputCheck
from complaint_intake.rules_config import RulesConfig
from complaint_intake.schemas import SEVERITY_ORDER, Category, ModelTriage, Severity


@dataclass(frozen=True)
class RuleContext:
    input_check: InputCheck
    redacted_text: str | None = None  # None when redaction failed or was skipped
    signals: Signals | None = None
    model: ModelTriage | None = None
    delimiter_tampering: bool = False
    redaction_failed: bool = False
    classification_error: str | None = None  # ClassificationError.reason
    filter_categories: tuple[str, ...] = ()  # platform content-filter categories that fired


@dataclass(frozen=True)
class RulesOutcome:
    category: Category | None
    severity: Severity | None
    requires_human_review: bool
    review_reasons: tuple[str, ...]
    fired: tuple[str, ...]
    rules_version: str


def _max(a: Severity | None, b: Severity) -> Severity:
    if a is None:
        return b
    return max(a, b, key=SEVERITY_ORDER.index)


def apply_rules(ctx: RuleContext, config: RulesConfig) -> RulesOutcome:
    model = ctx.model
    category = model.category if model else None
    severity = model.severity if model else None
    review = model.requires_human_review if model else False
    reasons: list[str] = []
    fired: list[str] = []

    def fire(rule: str, reason: str) -> None:
        nonlocal review
        review = True
        if rule not in fired:
            fired.append(rule)
        reasons.append(reason)

    if model and model.requires_human_review:
        reasons.append("model_requested_review")
        reasons.extend(f"model:{r}" for r in model.review_reasons)

    # R8: fail closed on redaction failure. Nothing else about the text is known.
    if ctx.redaction_failed:
        fire("R8", "R8_pii_service_failure")

    # R6 (input side): unprocessable, too short or noisy input.
    check = ctx.input_check
    for flag in check.flags:
        if flag in ("input_empty", "input_too_long", "input_too_short", "input_low_text_quality"):
            fire("R6", f"R6_{flag}")

    # R7: no usable model output. Record which platform filters fired (names only).
    if ctx.classification_error:
        fire("R7", f"R7_{ctx.classification_error}")
    for name in ctx.filter_categories:
        fire("R7", f"R7_filter:{name}")

    if category is Category.FRAUD_UNAUTHORIZED:
        severity = _max(severity, Severity.HIGH)
        fire("R1", "R1_fraud_floor")
    if category is Category.PRIVACY_DATA:
        fire("R2", "R2_privacy_office")
    if category is Category.OTHER_UNCLEAR:
        fire("R6", "R6_category_unclear")

    text = ctx.redacted_text or ""
    if text and config.regulatory.search(text):
        fire("R3", "R3_regulatory_language")

    phrases = " | ".join(ctx.signals.key_phrases) if ctx.signals else ""
    distress_hit = bool(text and config.distress.search(text)) or bool(
        phrases and config.distress.search(phrases)
    )
    if distress_hit or (model and model.distress_suspected):
        severity = Severity.CRITICAL
        fire("R4", "R4_distress_or_vulnerability")

    platform_attack = bool({"jailbreak", "indirect_attack"} & set(ctx.filter_categories))
    if (
        (model and model.injection_suspected)
        or check.injection_flagged
        or ctx.delimiter_tampering
        or platform_attack
    ):
        fire("R5", "R5_injection_suspected")

    # Enrichment that broke (not one that is switched off) is a reason to look harder.
    if (
        text
        and ctx.signals
        and not ctx.signals.available
        and ctx.signals.error != "enrichment_disabled"
    ):
        fire("ENRICH", "enrichment_unavailable")

    # Invariant (P3): never lower the model's severity, never clear its review flag.
    # An explicit check, not `assert`, so it also holds under `python -O`.
    if model and (
        severity is None
        or SEVERITY_ORDER.index(severity) < SEVERITY_ORDER.index(model.severity)
        or (model.requires_human_review and not review)
    ):
        raise RuntimeError("rules invariant violated: a rule reduced scrutiny")

    return RulesOutcome(
        category=category,
        severity=severity,
        requires_human_review=review,
        review_reasons=tuple(dict.fromkeys(reasons)),
        fired=tuple(fired),
        rules_version=config.version,
    )
