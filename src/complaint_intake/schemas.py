"""Taxonomy and the schema the model must answer in.

`ModelTriage` is what the LLM returns. It is advice (principle P3): the rules in
M3 can raise its severity or add review reasons, never lower them. The
department is NOT asked from the model; code derives it from the category.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Category(StrEnum):
    FRAUD_UNAUTHORIZED = "FRAUD_UNAUTHORIZED"
    CARD_ISSUE = "CARD_ISSUE"
    PAYMENT_TRANSFER = "PAYMENT_TRANSFER"
    ACCOUNT_ACCESS = "ACCOUNT_ACCESS"
    FEES_CHARGES = "FEES_CHARGES"
    LOAN_MORTGAGE = "LOAN_MORTGAGE"
    DIGITAL_BANKING = "DIGITAL_BANKING"
    SERVICE_CONDUCT = "SERVICE_CONDUCT"
    PRIVACY_DATA = "PRIVACY_DATA"
    OTHER_UNCLEAR = "OTHER_UNCLEAR"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]

DEFAULT_DEPARTMENT: dict[Category, str] = {
    Category.FRAUD_UNAUTHORIZED: "Fraud and Disputes",
    Category.CARD_ISSUE: "Cards",
    Category.PAYMENT_TRANSFER: "Payments",
    Category.ACCOUNT_ACCESS: "Account Services",
    Category.FEES_CHARGES: "Account Services",
    Category.LOAN_MORTGAGE: "Lending",
    Category.DIGITAL_BANKING: "Digital Support",
    Category.SERVICE_CONDUCT: "Customer Experience",
    Category.PRIVACY_DATA: "Privacy Office",
    Category.OTHER_UNCLEAR: "General triage",
}

SUMMARY_MAX_CHARS = 300
MAX_REVIEW_REASONS = 8


class ModelTriage(BaseModel):
    """The model's structured answer. Validated after every call; never trusted as is."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=SUMMARY_MAX_CHARS)
    category: Category
    severity: Severity
    requires_human_review: bool
    review_reasons: list[str] = Field(max_length=MAX_REVIEW_REASONS)
    injection_suspected: bool
    distress_suspected: bool
    # Self-reported confidence is a weak signal. Measure its calibration (M4)
    # and never rely on it alone.
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def department(self) -> str:
        return DEFAULT_DEPARTMENT[self.category]


def model_output_json_schema() -> dict[str, Any]:
    """Strict JSON schema sent with the request (structured outputs).

    Hand-written rather than generated so it stays inside the subset strict mode
    accepts: every field required, no additional properties, enums inlined.
    Length and range limits are enforced by Pydantic afterwards. `summary` comes
    first so the model states the facts before it labels them.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {
                "type": "string",
                "description": "At most 40 words. Only facts stated in the complaint.",
            },
            "category": {"type": "string", "enum": [c.value for c in Category]},
            "severity": {"type": "string", "enum": [s.value for s in Severity]},
            "requires_human_review": {"type": "boolean"},
            "review_reasons": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short snake_case reasons, empty if no review is needed.",
            },
            "injection_suspected": {"type": "boolean"},
            "distress_suspected": {"type": "boolean"},
            "confidence": {"type": "number", "description": "0.0 to 1.0"},
        },
        "required": [
            "summary",
            "category",
            "severity",
            "requires_human_review",
            "review_reasons",
            "injection_suspected",
            "distress_suspected",
            "confidence",
        ],
    }
