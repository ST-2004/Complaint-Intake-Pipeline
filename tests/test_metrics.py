import pytest

from complaint_intake.evaluation import metrics as m


def test_per_class_and_macro_f1_known_values():
    truth = ["A", "A", "B", "B", "C"]
    pred = ["A", "B", "B", "B", "A"]
    scores = {s.label: s for s in m.per_class(truth, pred, ["A", "B", "C"])}
    assert scores["A"].precision == 0.5 and scores["A"].recall == 0.5
    assert scores["B"].precision == pytest.approx(2 / 3) and scores["B"].recall == 1.0
    assert scores["C"].f1 == 0.0 and scores["C"].support == 1
    expected = (0.5 + 0.8 + 0.0) / 3
    assert m.macro_f1(truth, pred) == pytest.approx(expected)


def test_macro_f1_ignores_classes_absent_from_truth():
    assert m.macro_f1(["A", "A"], ["A", "A"], ["A", "B"]) == 1.0


def test_confusion_counts_none_predictions():
    matrix = m.confusion(["A", "B"], ["A", m.NONE_LABEL], ["A", "B"])
    assert matrix["A"]["A"] == 1 and matrix["B"][m.NONE_LABEL] == 1


def test_severity_metrics():
    truth = ["LOW", "HIGH", "CRITICAL", "MEDIUM"]
    pred = ["MEDIUM", "HIGH", "HIGH", m.NONE_LABEL]
    assert m.accuracy(truth, pred) == m.Ratio(1, 4)
    assert m.severity_off_by_one(truth, pred) == m.Ratio(2, 4)
    assert m.severity_under(truth, pred) == m.Ratio(2, 4)  # CRITICAL->HIGH and missing
    assert m.high_plus_recall(truth, pred) == m.Ratio(2, 2)


def test_recall_and_precision_of_review():
    truth = [True, True, False, False]
    pred = [True, False, True, False]
    assert m.recall_of(truth, pred) == m.Ratio(1, 2)
    assert m.precision_of(truth, pred) == m.Ratio(1, 2)
    assert str(m.Ratio(0, 0)) == "n/a (0/0)" and str(m.Ratio(27, 30)) == "0.90 (27/30)"


def test_percentile_nearest_rank():
    values = list(range(1, 21))
    assert m.percentile(values, 0.5) == 10 and m.percentile(values, 0.95) == 19
    assert m.percentile([], 0.5) is None


@pytest.mark.parametrize(
    "summary,complaint,expected",
    [
        ("Customer was charged $45 on Friday.", "I was charged $45.00 on Friday", []),
        ("Customer was charged $450.", "I was charged $45", ["450"]),
        (
            "Customer says Jennifer at Westdale was rude.",
            "the teller at Westdale was rude",
            ["Jennifer"],
        ),
        ("[PERSON] reports a fee of $1,200.", "[PERSON] says fee 1200", []),
        ("Customer reports Visa charges. They want a refund.", "charges on my card", []),
    ],
)
def test_ungrounded_terms(summary, complaint, expected):
    assert m.ungrounded_terms(summary, complaint) == expected
