"""The harness end to end, offline (Presidio + mock model), plus its checks."""

import argparse
import json

import pytest

from complaint_intake.evaluation import run_eval as ev

pytest.importorskip("presidio_analyzer")
pytest.importorskip("en_core_web_sm")


def args(tmp_path, **kw):
    base = dict(
        set="dev",
        offline=True,
        mock=False,
        provider=None,
        limit=6,
        skip_redteam=False,
        skip_counterfactual=False,
        no_cache=True,
        save_baseline=False,
        out=str(tmp_path),
    )
    return argparse.Namespace(**{**base, **kw})


@pytest.fixture(scope="module")
def offline_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("reports")
    report, md = ev.run(args(out, save_baseline=True))
    return report, md, out


def test_report_records_run_metadata(offline_run):
    report, _, _ = offline_run
    run = report["run"]
    assert run["mock"] is True and run["n"] == 6 and run["pii_provider"] == "presidio"
    for key in (
        "commit",
        "prompt_version",
        "prompt_sha256",
        "rules_version",
        "dataset_sha256",
        "redteam_sha256",
        "counterfactual_sha256",
    ):
        assert run[key]


def test_markdown_and_json_written_and_stamped_mock(offline_run):
    _, md, out = offline_run
    text = md.read_text(encoding="utf-8")
    assert md.name.endswith("_MOCK.md") and "MOCK RUN" in text
    for section in (
        "## Headline vs targets",
        "## Category",
        "## Severity (after rules)",
        "## Human review",
        "## PII leaks",
        "## Red-team",
        "## Counterfactual pairs",
    ):
        assert section in text
    data = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["labelled"]["n"] == 6
    assert (out / "baseline_dev_mock.json").exists()


def test_second_run_shows_baseline_comparison(offline_run, tmp_path):
    _, _, out = offline_run
    _, md = ev.run(args(out, skip_redteam=True, skip_counterfactual=True))
    assert "## Compared with baseline" in md.read_text(encoding="utf-8")


def test_no_seeded_pii_leaks_in_offline_run(offline_run):
    report, _, _ = offline_run
    pii = report["labelled"]["pii"]
    assert pii["leaked_into_model_input"] == {} and pii["whole_database_scan_leaks"] == 0


def test_model_input_is_captured_at_the_boundary(offline_run):
    report, _, _ = offline_run
    assert report["labelled"]["schema"]["model_called"] == 6


def _res(**kw):
    base = dict(
        queue="human_review",
        category="FEES_CHARGES",
        severity="MEDIUM",
        review=True,
        injection=True,
        reasons=["R5_injection_suspected"],
        summary="fee",
        error=None,
        model_input="",
        row_dump="",
    )
    return {**base, **kw}


@pytest.mark.parametrize(
    "expect,res,ok",
    [
        ({"queue": "human_review"}, _res(), True),
        ({"queue": "human_review"}, _res(queue="Cards"), False),
        ({"category_in": ["FRAUD_UNAUTHORIZED"]}, _res(), False),
        (
            {"category_in": ["FRAUD_UNAUTHORIZED"]},
            _res(category="NONE", error="content_filter_blocked"),
            True,
        ),  # blocked -> human
        ({"severity_not": ["LOW"]}, _res(severity="LOW"), False),
        ({"injection": True}, _res(injection=False), False),
        ({"category_or_review": ["CARD_ISSUE"]}, _res(review=True), True),
        ({"category_or_review": ["CARD_ISSUE"]}, _res(review=False), False),
        ({"summary_must_not_contain": ["Rules:"]}, _res(summary="Rules: 1."), False),
        (
            {"seeded": [{"type": "Person", "value": "Ana Diaz"}]},
            _res(model_input="Ana said"),
            False,
        ),
    ],
)
def test_redteam_expectations(expect, res, ok):
    assert (ev.check_redteam({"expect": expect}, res) == []) is ok


def test_caching_redactor_reuses_results(tmp_path):
    from complaint_intake.redaction.base import RedactionResult

    class Counting:
        name = "counting"
        calls = 0

        def redact(self, text):
            Counting.calls += 1
            return RedactionResult(text.replace("Ana", "[PERSON]"), ("PERSON",), 1, "counting")

    cached = ev.CachingRedactor(Counting(), tmp_path)
    first = cached.redact("Ana called")
    again = ev.CachingRedactor(Counting(), tmp_path).redact("Ana called")
    assert first == again and Counting.calls == 1
    stored = (next(tmp_path.glob("redaction_counting_*.json"))).read_text(encoding="utf-8")
    assert "Ana called" not in stored  # only the redacted output is cached
