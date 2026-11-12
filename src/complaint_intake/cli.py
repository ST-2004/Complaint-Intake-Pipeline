"""Command line: triage complaints, work the review queue, see team-lead stats.

    python -m complaint_intake.cli triage "text of the complaint"
    python -m complaint_intake.cli triage --file complaint.txt
    python -m complaint_intake.cli batch data/samples/classify_samples.jsonl
    python -m complaint_intake.cli review list
    python -m complaint_intake.cli review show <case_id>
    python -m complaint_intake.cli review approve <case_id> --reviewer alex
    python -m complaint_intake.cli review override <case_id> --reviewer alex \
        --category CARD_ISSUE --severity MEDIUM --reason "card decline, not fraud"
    python -m complaint_intake.cli stats

Everything shown is redacted. Triage needs the Azure environment (infra-up + env);
review and stats work offline on the local database (DB_PATH).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from complaint_intake.config import Settings
from complaint_intake.schemas import Category, Severity
from complaint_intake.store import ReviewError, Store


def _print_decision(decision) -> None:
    d = decision.to_dict()
    flag = "-> HUMAN REVIEW" if d["requires_human_review"] else f"-> {d['queue']}"
    print(f"{d['case_id']}  {d['category'] or '(no label)'} / {d['severity'] or '-'}  {flag}")
    if d["summary"]:
        print(f"  summary: {d['summary']}")
    if d["review_reasons"]:
        print(f"  reasons: {', '.join(d['review_reasons'])}")
    if d["pii_categories_found"]:
        print(f"  PII removed: {', '.join(d['pii_categories_found'])}")
    if d["error_reason"]:
        print(f"  error: {d['error_reason']}")


def cmd_triage(args, settings: Settings) -> int:
    from complaint_intake.pipeline import build_pipeline

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = " ".join(args.text)
    else:
        print("Paste the complaint, then Ctrl+Z Enter (Windows) or Ctrl+D (macOS/Linux):")
        text = sys.stdin.read()
    decision = build_pipeline(settings).triage(text)
    if args.json:
        print(json.dumps(decision.to_dict(), indent=2))
    else:
        _print_decision(decision)
    return 0


def cmd_batch(args, settings: Settings) -> int:
    from complaint_intake.pipeline import build_pipeline

    pipeline = build_pipeline(settings)
    count = review = 0
    for line in Path(args.path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        decision = pipeline.triage(json.loads(line)["text"])
        count += 1
        review += decision.requires_human_review
        _print_decision(decision)
    print(f"\n{count} complaints triaged, {review} sent to human review.")
    return 0


def cmd_review(args, settings: Settings) -> int:
    store = Store(settings.db_path)
    try:
        if args.action == "list":
            cases = store.pending()
            if not cases:
                print("Review queue is empty.")
            for c in cases:
                print(
                    f"{c['case_id']}  {c['severity'] or '-':<8} {c['category'] or '(no label)':<20}"
                    f" {', '.join(c['review_reasons'])}"
                )
        elif args.action == "show":
            case = store.get_case(args.case_id)
            if case is None:
                print(f"no case {args.case_id}")
                return 1
            print(json.dumps(case, indent=2))
        elif args.action == "approve":
            store.approve(args.case_id, args.reviewer, args.note or "")
            print(f"{args.case_id} approved by {args.reviewer}")
        elif args.action == "override":
            store.override(
                args.case_id,
                args.reviewer,
                reason=args.reason,
                category=args.category,
                severity=args.severity,
            )
            print(f"{args.case_id} overridden by {args.reviewer}: {args.reason}")
    except ReviewError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        store.close()
    return 0


def cmd_stats(args, settings: Settings) -> int:
    store = Store(settings.db_path)
    s = store.stats()
    store.close()
    print(f"cases: {s.total}   pending review: {s.pending_review}   reviewed: {s.reviewed}")
    rate = f"{s.override_rate:.0%} ({s.overridden}/{s.reviewed})" if s.reviewed else "n/a"
    print(f"override rate: {rate}")
    print("by queue:  " + ", ".join(f"{k}={v}" for k, v in sorted(s.by_queue.items())))
    print("by status: " + ", ".join(f"{k}={v}" for k, v in sorted(s.by_status.items())))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="complaint-intake", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("triage", help="triage one complaint")
    t.add_argument("text", nargs="*")
    t.add_argument("--file")
    t.add_argument("--json", action="store_true", help="print the full output record")
    t.set_defaults(func=cmd_triage)

    b = sub.add_parser("batch", help="triage every line of a JSONL file with a 'text' field")
    b.add_argument("path")
    b.set_defaults(func=cmd_batch)

    r = sub.add_parser("review", help="work the human-review queue")
    rs = r.add_subparsers(dest="action", required=True)
    rs.add_parser("list")
    show = rs.add_parser("show")
    show.add_argument("case_id")
    ap = rs.add_parser("approve")
    ap.add_argument("case_id")
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--note")
    ov = rs.add_parser("override")
    ov.add_argument("case_id")
    ov.add_argument("--reviewer", required=True)
    ov.add_argument("--reason", required=True)
    ov.add_argument("--category", choices=[c.value for c in Category])
    ov.add_argument("--severity", choices=[s.value for s in Severity])
    r.set_defaults(func=cmd_review)

    st = sub.add_parser("stats", help="team-lead view: queues, statuses, override rate")
    st.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args, Settings())


if __name__ == "__main__":
    sys.exit(main())
