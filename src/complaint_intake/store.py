"""SQLite audit log and review queue.

Stores REDACTED text only (P2). When redaction failed, no text is stored at all:
the reviewer must open the original in the source system. Reviews are
append-only; a case's final label is the latest review, and the model's
original suggestion is never overwritten.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from complaint_intake.schemas import Category, Severity

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id              TEXT PRIMARY KEY,
    created_at           TEXT NOT NULL,
    status               TEXT NOT NULL,          -- pending_review | routed | approved | overridden
    queue                TEXT NOT NULL,          -- human_review | <department>
    redacted_text        TEXT,                   -- NULL if redaction failed (never raw text)
    pii_provider         TEXT,
    pii_categories       TEXT NOT NULL,          -- JSON list of tags, never values
    pii_entity_count     INTEGER NOT NULL,
    input_flags          TEXT NOT NULL,          -- JSON list
    sentiment            TEXT,
    key_phrases          TEXT NOT NULL,          -- JSON list (from redacted text)
    category             TEXT,                   -- after rules; NULL if no model output
    severity             TEXT,
    department           TEXT,
    summary              TEXT,
    requires_review      INTEGER NOT NULL,
    review_reasons       TEXT NOT NULL,          -- JSON list
    rules_fired          TEXT NOT NULL,          -- JSON list
    injection_suspected  INTEGER NOT NULL,
    model_category       TEXT,                   -- the model's own suggestion, kept for audit
    model_severity       TEXT,
    model_confidence     REAL,
    error_reason         TEXT,
    prompt_version       TEXT,
    prompt_sha256        TEXT,
    rules_version        TEXT NOT NULL,
    model_deployment     TEXT,
    model_name           TEXT,
    attempts             INTEGER,
    latency_ms           REAL,
    tokens_in            INTEGER,
    tokens_out           INTEGER,
    cost_usd             REAL
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

CREATE TABLE IF NOT EXISTS reviews (
    review_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT NOT NULL REFERENCES cases(case_id),
    reviewed_at   TEXT NOT NULL,
    reviewer      TEXT NOT NULL,
    action        TEXT NOT NULL CHECK (action IN ('approve', 'override')),
    category      TEXT,
    severity      TEXT,
    department    TEXT,
    reason        TEXT NOT NULL
);
"""

JSON_FIELDS = (
    "pii_categories",
    "input_flags",
    "key_phrases",
    "review_reasons",
    "rules_fired",
)


class ReviewError(ValueError):
    pass


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Stats:
    total: int
    by_queue: dict[str, int]
    by_status: dict[str, int]
    pending_review: int
    reviewed: int
    overridden: int

    @property
    def override_rate(self) -> float | None:
        return self.overridden / self.reviewed if self.reviewed else None


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    # ------------------------------------------------------------ cases
    def save_case(self, record: dict[str, Any]) -> None:
        row = dict(record)
        for key in JSON_FIELDS:
            row[key] = json.dumps(list(row.get(key) or []))
        for key in ("requires_review", "injection_suspected"):
            row[key] = int(bool(row[key]))
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        with self._tx() as conn:
            conn.execute(f"INSERT INTO cases ({cols}) VALUES ({marks})", row)  # noqa: S608

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            return None
        case = _decode(row)
        case["reviews"] = [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM reviews WHERE case_id = ? ORDER BY review_id", (case_id,)
            )
        ]
        return case

    def pending(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM cases WHERE status = 'pending_review' ORDER BY "
            "CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 "
            "WHEN 'LOW' THEN 3 ELSE -1 END, created_at"
        )
        return [_decode(r) for r in rows]

    # ------------------------------------------------------------ reviews
    def approve(self, case_id: str, reviewer: str, note: str = "") -> None:
        case = self._require_pending(case_id)
        if case["category"] is None:
            raise ReviewError(
                "this case has no model label to approve; use override with --category and "
                "--severity"
            )
        self._record(
            case_id,
            reviewer,
            "approve",
            case["category"],
            case["severity"],
            case["department"],
            note or "approved as suggested",
            "approved",
        )

    def override(
        self,
        case_id: str,
        reviewer: str,
        *,
        reason: str,
        category: Category | str | None = None,
        severity: Severity | str | None = None,
    ) -> None:
        from complaint_intake.schemas import DEFAULT_DEPARTMENT

        if not reason.strip():
            raise ReviewError("an override needs a reason")
        case = self._require_pending(case_id)
        new_cat = (
            Category(category)
            if category
            else (Category(case["category"]) if case["category"] else None)
        )
        new_sev = (
            Severity(severity)
            if severity
            else (Severity(case["severity"]) if case["severity"] else None)
        )
        if new_cat is None or new_sev is None:
            raise ReviewError("this case has no model label; give both --category and --severity")
        if new_cat.value == case["category"] and new_sev.value == case["severity"]:
            raise ReviewError("nothing changed; use approve instead")
        self._record(
            case_id,
            reviewer,
            "override",
            new_cat.value,
            new_sev.value,
            DEFAULT_DEPARTMENT[new_cat],
            reason.strip(),
            "overridden",
        )

    def _require_pending(self, case_id: str) -> dict[str, Any]:
        case = self.get_case(case_id)
        if case is None:
            raise ReviewError(f"no case {case_id}")
        if case["status"] != "pending_review":
            raise ReviewError(f"case {case_id} is {case['status']}, not pending review")
        return case

    def _record(self, case_id, reviewer, action, category, severity, department, reason, status):
        if not reviewer.strip():
            raise ReviewError("reviewer is required")
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO reviews (case_id, reviewed_at, reviewer, action, category, severity,"
                " department, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    now_utc(),
                    reviewer.strip(),
                    action,
                    category,
                    severity,
                    department,
                    reason,
                ),
            )
            conn.execute(
                "UPDATE cases SET status = ?, queue = ? WHERE case_id = ?",
                (status, department or "General triage", case_id),
            )

    # ------------------------------------------------------------ team lead view
    def stats(self) -> Stats:
        def counts(col: str) -> dict[str, int]:
            q = f"SELECT {col}, COUNT(*) FROM cases GROUP BY {col}"  # noqa: S608 - fixed names
            return {k: v for k, v in self._conn.execute(q)}

        by_status = counts("status")
        reviewed = self._conn.execute("SELECT COUNT(DISTINCT case_id) FROM reviews").fetchone()[0]
        overridden = by_status.get("overridden", 0)
        return Stats(
            total=sum(by_status.values()),
            by_queue=counts("queue"),
            by_status=by_status,
            pending_review=by_status.get("pending_review", 0),
            reviewed=reviewed,
            overridden=overridden,
        )

    def dump_text(self) -> str:
        """Everything in the database as SQL text (used by the no-raw-PII test)."""
        return "\n".join(self._conn.iterdump())


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    case = dict(row)
    for key in JSON_FIELDS:
        case[key] = json.loads(case[key])
    case["requires_review"] = bool(case["requires_review"])
    case["injection_suspected"] = bool(case["injection_suspected"])
    return case
