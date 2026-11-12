import pytest

from complaint_intake.store import ReviewError, Store


def record(case_id, **kw):
    base = {
        "case_id": case_id,
        "created_at": "2026-11-11T12:00:00+00:00",
        "status": "pending_review",
        "queue": "human_review",
        "redacted_text": "[PERSON] reports charges",
        "pii_provider": "fake",
        "pii_categories": ["PERSON"],
        "pii_entity_count": 1,
        "input_flags": [],
        "sentiment": "negative",
        "key_phrases": ["charges"],
        "category": "FRAUD_UNAUTHORIZED",
        "severity": "HIGH",
        "department": "Fraud and Disputes",
        "summary": "s",
        "requires_review": True,
        "review_reasons": ["R1_fraud_floor"],
        "rules_fired": ["R1"],
        "injection_suspected": False,
        "rules_version": "rules_v1",
    }
    return {**base, **kw}


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_save_and_get_round_trip(store):
    store.save_case(record("c-1"))
    case = store.get_case("c-1")
    assert case["pii_categories"] == ["PERSON"] and case["requires_review"] is True
    assert case["reviews"] == []


def test_pending_is_ordered_by_severity(store):
    store.save_case(record("c-low", severity="LOW"))
    store.save_case(record("c-crit", severity="CRITICAL"))
    store.save_case(record("c-none", severity=None, category=None))
    store.save_case(record("c-routed", status="routed", queue="Cards"))
    assert [c["case_id"] for c in store.pending()] == ["c-none", "c-crit", "c-low"]


def test_approve_records_review_and_closes_queue_item(store):
    store.save_case(record("c-1"))
    store.approve("c-1", "alex")
    case = store.get_case("c-1")
    assert case["status"] == "approved" and case["queue"] == "Fraud and Disputes"
    assert case["reviews"][0]["action"] == "approve" and case["reviews"][0]["reviewer"] == "alex"


def test_override_records_reason_and_keeps_model_suggestion(store):
    store.save_case(record("c-1", model_category="FRAUD_UNAUTHORIZED", model_severity="HIGH"))
    store.override(
        "c-1", "sam", reason="merchant dispute, not fraud", category="CARD_ISSUE", severity="MEDIUM"
    )
    case = store.get_case("c-1")
    review = case["reviews"][0]
    assert case["status"] == "overridden" and case["queue"] == "Cards"
    assert (review["category"], review["severity"], review["reason"]) == (
        "CARD_ISSUE",
        "MEDIUM",
        "merchant dispute, not fraud",
    )
    assert case["model_category"] == "FRAUD_UNAUTHORIZED"  # original suggestion kept
    assert case["category"] == "FRAUD_UNAUTHORIZED"


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"reason": "  "}, "needs a reason"),
        ({"reason": "same"}, "nothing changed"),
    ],
)
def test_override_validation(store, kwargs, message):
    store.save_case(record("c-1"))
    with pytest.raises(ReviewError, match=message):
        store.override("c-1", "sam", **kwargs)


def test_unlabelled_case_needs_override_with_both_fields(store):
    store.save_case(record("c-1", category=None, severity=None, department=None))
    with pytest.raises(ReviewError, match="no model label"):
        store.approve("c-1", "alex")
    with pytest.raises(ReviewError, match="both"):
        store.override("c-1", "alex", reason="r", category="CARD_ISSUE")
    store.override("c-1", "alex", reason="read original", category="CARD_ISSUE", severity="LOW")
    assert store.get_case("c-1")["status"] == "overridden"


def test_cannot_review_twice_or_missing(store):
    store.save_case(record("c-1"))
    store.approve("c-1", "alex")
    with pytest.raises(ReviewError, match="not pending"):
        store.approve("c-1", "alex")
    with pytest.raises(ReviewError, match="no case"):
        store.approve("c-missing", "alex")


def test_stats_override_rate(store):
    for i in range(4):
        store.save_case(record(f"c-{i}"))
    store.save_case(record("c-r", status="routed", queue="Cards", requires_review=False))
    store.approve("c-0", "a")
    store.approve("c-1", "a")
    store.override("c-2", "a", reason="wrong", category="CARD_ISSUE", severity="LOW")
    s = store.stats()
    assert s.total == 5 and s.pending_review == 1 and s.reviewed == 3
    assert s.override_rate == pytest.approx(1 / 3)
    assert s.by_queue["Cards"] == 2
