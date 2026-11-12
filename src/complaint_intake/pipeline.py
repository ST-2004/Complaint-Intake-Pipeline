"""Orchestration: the eight steps of Figure 1, with the fail-closed paths.

    1 intake -> 2 input checks -> 3 redact -> 4 enrich -> 5 classify
    -> 6 validate + rules -> 7 route -> 8 audit

Raw text exists only inside `triage()` until step 3 returns. Every path, including
every failure, ends in a `TriageDecision` and an audit record with redacted
data only. v1 never replies to the customer or closes a case (P3).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from complaint_intake.classifier import ClassificationError, ClassificationOutcome, Classifier
from complaint_intake.enrichment import Enricher, Signals
from complaint_intake.input_checks import check_input
from complaint_intake.model_client import Usage
from complaint_intake.redaction import RedactionError, RedactionResult, Redactor
from complaint_intake.rules import RuleContext, apply_rules
from complaint_intake.rules_config import RulesConfig
from complaint_intake.schemas import DEFAULT_DEPARTMENT
from complaint_intake.store import Store, now_utc

log = logging.getLogger(__name__)

HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class TriageDecision:
    """The output record (plan section 4). Contains no raw text or PII values."""

    case_id: str
    queue: str
    status: str
    category: str | None
    severity: str | None
    summary: str | None
    suggested_department: str | None
    requires_human_review: bool
    review_reasons: list[str]
    injection_suspected: bool
    pii_categories_found: list[str]
    prompt_version: str | None
    rules_version: str
    model_deployment: str | None
    error_reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Pipeline:
    def __init__(
        self,
        *,
        redactor: Redactor,
        enricher: Enricher,
        classifier: Classifier,
        rules: RulesConfig,
        store: Store | None = None,
    ) -> None:
        self.redactor = redactor
        self.enricher = enricher
        self.classifier = classifier
        self.rules = rules
        self.store = store

    def triage(self, raw_text: str, *, case_id: str | None = None) -> TriageDecision:
        started = time.perf_counter()
        case_id = case_id or new_case_id()  # 1. intake: nothing stored yet
        check = check_input(raw_text, self.rules)  # 2. input checks

        redaction: RedactionResult | None = None
        signals: Signals | None = None
        outcome: ClassificationOutcome | None = None
        redaction_failed = False
        error: str | None = None
        usage = Usage()
        filter_categories: tuple[str, ...] = ()

        if check.processable:
            try:
                redaction = self.redactor.redact(raw_text)  # 3. the only step that sees raw text
            except RedactionError as exc:
                redaction_failed, error = True, "pii_service_failure"
                log.warning("case=%s redaction failed: %s", case_id, exc)

        # From here on only `redaction.text` is used; raw_text is not touched again.
        if redaction is not None:
            signals = self.enricher.enrich(redaction.text)  # 4. never raises
            try:
                outcome = self.classifier.classify(  # 5. redacted text only
                    redaction.text, signals, flags=check.flags
                )
            except ClassificationError as exc:
                error = exc.reason
                usage = exc.usage
                filter_categories = getattr(exc, "categories", ())
                log.warning(
                    "case=%s classification failed: %s %s",
                    case_id,
                    exc.reason,
                    ",".join(filter_categories),
                )
            else:
                usage = outcome.usage

        triage = outcome.triage if outcome else None
        result = apply_rules(  # 6. rules
            RuleContext(
                input_check=check,
                redacted_text=redaction.text if redaction else None,
                signals=signals,
                model=triage,
                delimiter_tampering=bool(outcome and outcome.delimiter_tampering),
                redaction_failed=redaction_failed,
                classification_error=error if redaction is not None else None,
                filter_categories=filter_categories,
            ),
            self.rules,
        )
        if error is None and not check.processable:
            error = check.flags[0]

        department = DEFAULT_DEPARTMENT[result.category] if result.category else None
        if result.requires_human_review:  # 7. routing; nothing is auto-closed
            queue, status = HUMAN_REVIEW, "pending_review"
        else:
            queue, status = department or HUMAN_REVIEW, "routed"

        injection = "R5" in result.fired
        latency_ms = (time.perf_counter() - started) * 1000
        metrics = {
            "pipeline_latency_ms": round(latency_ms, 1),
            "model_latency_ms": round(outcome.latency_ms, 1) if outcome else None,
            "attempts": outcome.attempts if outcome else None,
            "tokens_in": usage.prompt_tokens,
            "tokens_out": usage.completion_tokens,
            "cost_usd": self.classifier.cost(usage),
            "rules_fired": list(result.fired),
        }
        decision = TriageDecision(
            case_id=case_id,
            queue=queue,
            status=status,
            category=result.category.value if result.category else None,
            severity=result.severity.value if result.severity else None,
            summary=triage.summary if triage else None,
            suggested_department=department,
            requires_human_review=result.requires_human_review,
            review_reasons=list(result.review_reasons),
            injection_suspected=injection,
            pii_categories_found=list(redaction.categories) if redaction else [],
            prompt_version=self.classifier.prompt.version,
            rules_version=result.rules_version,
            model_deployment=outcome.model_deployment if outcome else None,
            error_reason=error,
            metrics=metrics,
        )

        if self.store is not None:  # 8. audit: redacted data only
            self.store.save_case(
                {
                    "case_id": case_id,
                    "created_at": now_utc(),
                    "status": status,
                    "queue": queue,
                    "redacted_text": redaction.text if redaction else None,
                    "pii_provider": redaction.provider if redaction else self.redactor.name,
                    "pii_categories": decision.pii_categories_found,
                    "pii_entity_count": redaction.entity_count if redaction else 0,
                    "input_flags": list(check.flags),
                    "sentiment": signals.sentiment if signals else None,
                    "key_phrases": list(signals.key_phrases) if signals else [],
                    "category": decision.category,
                    "severity": decision.severity,
                    "department": department,
                    "summary": decision.summary,
                    "requires_review": decision.requires_human_review,
                    "review_reasons": decision.review_reasons,
                    "rules_fired": list(result.fired),
                    "injection_suspected": injection,
                    "model_category": triage.category.value if triage else None,
                    "model_severity": triage.severity.value if triage else None,
                    "model_confidence": triage.confidence if triage else None,
                    "error_reason": error,
                    "prompt_version": outcome.prompt_version if outcome else None,
                    "prompt_sha256": outcome.prompt_sha256 if outcome else None,
                    "rules_version": result.rules_version,
                    "model_deployment": outcome.model_deployment if outcome else None,
                    "model_name": outcome.model_name if outcome else None,
                    "attempts": metrics["attempts"],
                    "latency_ms": metrics["pipeline_latency_ms"],
                    "tokens_in": metrics["tokens_in"],
                    "tokens_out": metrics["tokens_out"],
                    "cost_usd": metrics["cost_usd"],
                }
            )
        log.info(
            "case=%s queue=%s status=%s rules=%s error=%s latency_ms=%.0f",
            case_id,
            queue,
            status,
            ",".join(result.fired) or "-",
            error or "-",
            latency_ms,
        )
        return decision


def new_case_id() -> str:
    return "c-" + uuid.uuid4().hex[:10]


def build_pipeline(settings, *, store: Store | None = None) -> Pipeline:
    from complaint_intake.classifier import get_classifier
    from complaint_intake.enrichment import get_enricher
    from complaint_intake.redaction import get_redactor
    from complaint_intake.rules_config import load_rules

    return Pipeline(
        redactor=get_redactor(settings),
        enricher=get_enricher(settings),
        classifier=get_classifier(settings),
        rules=load_rules(settings.rules_version),
        store=store if store is not None else Store(settings.db_path),
    )
