# Rules, routing, audit log and review (M3)

M3 joins the steps into one pipeline (`pipeline.py`) and adds the controls that
make the model's output safe to act on: deterministic rules, a human-review
queue and an audit log.

```
raw text -> input checks -> redact (R8 if it fails) -> enrich -> classify (R7 if it fails)
         -> rules R1-R8 -> route -> SQLite audit log
```

Every path, including every failure, ends in a decision and an audit record.
v1 never replies to a customer and never closes a case.

## Rules (rules_v1)

Keyword lists and injection patterns live in
[`config/rules_v1.toml`](../config/rules_v1.toml), so they can be reviewed and
changed without touching code. Matching uses word boundaries on the redacted text.

| Rule | Trigger | Action |
|---|---|---|
| R1 Fraud floor | category FRAUD_UNAUTHORIZED | severity at least HIGH; review |
| R2 Privacy office | category PRIVACY_DATA | review |
| R3 Regulatory language | regulator, ombudsman, lawyer, legal action, court... | review |
| R4 Distress | distress terms in text or key phrases, or the model's `distress_suspected` | CRITICAL; review |
| R5 Injection | model flag, input-check pattern, delimiter tampering, or Azure Prompt Shields `jailbreak` / `indirect_attack` | review |
| R6 Unclear input | OTHER_UNCLEAR, too short, noise, empty, longer than 20,000 characters | review |
| R7 No usable output | invalid after retry, content filter (categories recorded), refusal, timeout | review |
| R8 PII failure | redaction error | review; model never called; no text stored |
| (extra) | enrichment broke (not switched off) | review |

**Rules only add scrutiny.** `apply_rules` ends with an explicit check (not
`assert`, so it holds under `python -O`) that the severity was never lowered and
a review was never cleared. A test runs that check over all 320 combinations of
category, severity and model flags. The model's own review request and reasons
are kept (`model_requested_review`, `model:<reason>`).

## Routing

- Any review requirement: queue `human_review`, status `pending_review`.
- Otherwise: the department queue for the category, status `routed`.
- The review queue is sorted unlabelled cases first (R7/R8: nothing is known),
  then CRITICAL, HIGH, MEDIUM, LOW, then oldest first.

## Audit log (SQLite, `DB_PATH`)

`cases` holds one row per complaint: redacted text, PII categories (never
values), input flags, signals, the final category and severity, the **model's
own suggestion kept separately**, review reasons, rules fired, error reason,
prompt version and SHA, rules version, model, attempts, latency, tokens and cost.
When redaction failed, `redacted_text` is NULL: a reviewer opens the original in
the source system.

`reviews` is append-only: reviewer, action (`approve` | `override`), the new
label, and a mandatory reason for overrides. A case can be reviewed once.

## Reviewer and team-lead commands

```powershell
python tasks.py run "complaint text"            # triage one complaint (needs the environment)
python tasks.py run --json "complaint text"     # full output record
python -m complaint_intake.cli batch data/samples/classify_samples.jsonl
python tasks.py review                          # list pending cases, most urgent first
python tasks.py review show c-8eddd45704
python tasks.py review approve c-d883bb080b --reviewer reviewer-1 --note "confirmed"
python tasks.py review override c-8eddd45704 --reviewer reviewer-1 --severity HIGH --reason "..."
python -m complaint_intake.cli stats            # queues, statuses, override rate
```

Review and stats work offline on the local database.

## Definition of done: evidence

| Requirement | Evidence |
|---|---|
| Every red-flag case ends in the review queue | `test_every_red_flag_ends_in_human_review`: 14 cases (fraud, privacy, regulatory, distress, two kinds of injection, unclear, too short, empty, too long, invalid twice, content filter, model down, PII failure) |
| Overrides are recorded | `test_override_is_recorded_end_to_end`, `test_store.py`; live: one override and one approval, override rate 50% (1/2) |
| No raw PII anywhere in the database | `test_no_seeded_pii_in_database_model_input_or_logs`: all 28 seeded values checked against the full DB dump, every model input and every log line, with a worst-case model that copies its input into the summary. Live: 20 complaints through Azure, 0/28 seeded values in `triage.db`. |

## Findings during M3

1. **Presidio's DEBUG logging leaked raw PII.** It prints the words around each
   match ("Context list is: ... s.gallagher@example.net"). The no-PII-in-logs
   test caught it. Fixed by pinning the `presidio-analyzer` logger (and the Azure
   SDK HTTP logger) to WARNING inside the redaction modules, so app-level DEBUG
   logging cannot re-enable it.
2. **Rule R5 closes the gap M2 found.** The injection complaint the model left at
   "no review" now goes to human review.
3. **Azure Prompt Shields blocked a live injection as `jailbreak`** before the
   model answered. The case still went to review (R7), with PII removed. Now the
   filter category is recorded and also triggers R5.
4. **The injection regex missed "ignore *your previous* instructions"** (it
   allowed one qualifier word). Widened to up to three, with regression tests.
5. **R4 over-escalates:** the model flagged "can't buy groceries" as
   vulnerability, so R4 set CRITICAL. That is safe but noisy. In the live run a
   reviewer overrode it to HIGH, which is exactly the override-rate signal the
   team lead watches. Tune in M5 on the dev set.

## Limitations

- Keyword rules are English-only and literal; paraphrased distress or legal
  threats rely on the model flag.
- The review CLI has no authentication; reviewer names are free text. A real
  deployment needs SSO and role-based access (see README).
- SQLite suits a single-user proof of concept, not concurrent reviewers.
