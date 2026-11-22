"""CLI and offline pipeline: no Azure, no network (Presidio + MOCK model)."""

import json
from pathlib import Path

import pytest

from complaint_intake import cli
from complaint_intake.evaluation.run_eval import pii_gate
from complaint_intake.store import Store

DEMO_FILE = Path(__file__).resolve().parents[1] / "data" / "samples" / "demo_complaints.jsonl"

PII_COMPLAINT = (
    "My name is Priya Raman and two payments I never made, $640 and $1,180, came out "
    "of my account yesterday. Call me on 416-555-0199 or email priya.raman@example.com."
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "cli.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return path


def test_offline_triage_redacts_and_routes_fraud_to_review(db, capsys):
    assert cli.main(["triage", "--offline", "--json", PII_COMPLAINT]) == 0
    out = capsys.readouterr().out
    assert out.startswith(cli.MOCK_NOTE)
    record = json.loads(out[len(cli.MOCK_NOTE) :])
    assert record["requires_human_review"] is True
    assert "R1_fraud_floor" in record["review_reasons"]
    for value in ("Priya", "Raman", "416-555-0199", "priya.raman@example.com"):
        assert value not in out

    store = Store(str(db))
    try:
        assert all(v not in store.dump_text() for v in ("Raman", "416-555-0199"))
        assert len(store.pending()) == 1
    finally:
        store.close()


def test_offline_batch_demo_file(db, capsys):
    assert cli.main(["batch", "--offline", str(DEMO_FILE)]) == 0
    out = capsys.readouterr().out
    assert "5 complaints triaged, 4 sent to human review." in out
    assert "R5_injection_suspected" in out
    assert "4111 1111 1111 1111" not in out


def test_review_on_empty_db(db, capsys):
    assert cli.main(["review", "list"]) == 0
    assert "Review queue is empty." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("heads", "code"),
    [
        ({"pii_leaks_model_input": 0, "pii_leaks_database": 0}, 0),
        ({"pii_leaks_model_input": 1, "pii_leaks_database": 0}, 1),
        ({"pii_leaks_model_input": 0, "pii_leaks_database": 2}, 1),
        ({"pii_leaks_model_input": 0}, 1),  # missing count fails closed
    ],
)
def test_pii_gate(heads, code, capsys):
    assert pii_gate(heads) == code
    assert ("passed" in capsys.readouterr().out) is (code == 0)
