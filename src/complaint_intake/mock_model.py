"""A keyword 'model' for running the pipeline and the evaluation harness offline.

NOT a classifier to measure. It exists so the harness, reports and CI can run
without Azure or quota (plan risk table: "a mock model keeps tests independent
of quota"). Every report produced with it is stamped MOCK.
"""

from __future__ import annotations

import json
import re

from complaint_intake.model_client import ModelResponse, Usage

_KEYWORDS: list[tuple[str, str]] = [
    (
        "PRIVACY_DATA",
        r"privacy|personal information|data breach|disclos|someone else's statement|"
        r"another customer|opted out|delete my",
    ),
    (
        "FRAUD_UNAUTHORIZED",
        r"never (sent|made|authori[sz]ed|applied)|unauthori[sz]ed|wasn'?t me|"
        r"identity|scam|pretending|stolen|didn'?t (spend|make)",
    ),
    ("LOAN_MORTGAGE", r"mortgage|loan|line of credit|foreclos"),
    ("FEES_CHARGES", r"\bfees?\b|interest|overdraft|charged \$"),
    ("PAYMENT_TRANSFER", r"e-?transfer|wire|payment|deposit|payee|sent money"),
    ("CARD_ISSUE", r"\bcard\b|declined|pin\b|atm"),
    ("ACCOUNT_ACCESS", r"locked out|log ?in|password|sign in|access|open(ing)? a"),
    ("DIGITAL_BANKING", r"\bapp\b|website|online banking|notification|screen"),
    ("SERVICE_CONDUCT", r"teller|branch|rude|advisor|waited|call(ed)? back|guard"),
]
_INJECTION = re.compile(r"ignore|system (note|prompt)|you are now|classify (this|it) as", re.I)
_URGENT = re.compile(r"right now|immediately|scared|don'?t see the point|lawyer|legal", re.I)


class MockModelClient:
    deployment = "mock-keyword-model"

    def complete(self, messages, **kwargs) -> ModelResponse:
        user = messages[-1]["content"]
        complaint = user.split("<complaint>", 1)[-1].split("</complaint>", 1)[0].strip()
        category = next(
            (cat for cat, pattern in _KEYWORDS if re.search(pattern, complaint, re.I)),
            "OTHER_UNCLEAR",
        )
        severity = (
            "CRITICAL"
            if _URGENT.search(complaint)
            else ("HIGH" if category == "FRAUD_UNAUTHORIZED" else "MEDIUM")
        )
        first_sentence = re.split(r"(?<=[.!?])\s", complaint, maxsplit=1)[0][:200]
        answer = {
            "summary": first_sentence or "Empty complaint.",
            "category": category,
            "severity": severity,
            "requires_human_review": category
            in ("FRAUD_UNAUTHORIZED", "PRIVACY_DATA", "OTHER_UNCLEAR"),
            "review_reasons": [],
            "injection_suspected": bool(_INJECTION.search(complaint)),
            "distress_suspected": False,
            "confidence": 0.5,
        }
        tokens_in = len(" ".join(m["content"] for m in messages)) // 4
        return ModelResponse(
            json.dumps(answer), "stop", None, self.deployment, Usage(tokens_in, 60)
        )
