# Demo script (about 3 minutes)

Two versions. **Offline** needs no Azure account and costs nothing; the labels come
from a keyword stub, so it shows the plumbing (redaction, rules, review queue, audit),
not the model's quality. **Live** uses the real model and costs well under one cent.

## Before recording

```powershell
python tasks.py setup
.venv\Scripts\Activate.ps1
python tasks.py test        # 680+ passed, no cloud
```

Use a terminal at least 110 columns wide with a large font. Close anything that
shows your subscription, tenant or email address.

## 1. The problem (20 s, talking over the README)

"Banks get thousands of free-text complaints. The urgent ones (fraud, a customer in
distress, a regulator mention) sit in the same pile as app bugs. This triages them
with an LLM, with three constraints: personal data never reaches the model, the model
only *suggests*, and anything risky goes to a person."

## 2. One run, five complaints (60 s)

```powershell
python tasks.py demo          # offline
python tasks.py demo --live   # real model (environment must be up, see below)
```

Point at each line of `data/samples/demo_complaints.jsonl` as it appears:

| Complaint | What to say |
|---|---|
| demo-1 app logs out | Routine: goes straight to Digital Support, no human needed |
| demo-2 name, card, phone, email | "PII removed: CARD_NUMBER, EMAIL, PERSON, PHONE_NUMBER." The summary says `[PERSON]`. Fraud goes to a human whatever the model says (R1) |
| demo-3 "Ignore your previous instructions..." | The text is data, not instructions. Flagged R5, sent to review |
| demo-4 ombudsman, lawyer | Regulatory language forces review (R3) |
| demo-5 "bad service" | Too short to classify: not guessed at, sent to a person (R6) |

## 3. The reviewer and the team lead (40 s)

The demo prints the review queue (sorted by severity) and the stats. Then open the
top case (demo-4) and override it:

```powershell
$env:DB_PATH = "demo.db"
python -m complaint_intake.cli review show <case_id>     # redacted text, every fired rule, versions
python -m complaint_intake.cli review override <case_id> --reviewer sam `
    --severity HIGH --reason "regulatory threat, no sign of distress"
python -m complaint_intake.cli stats                     # override rate appears
Remove-Item Env:DB_PATH
```

"Every decision records the prompt version, the rules version and which rules fired.
An override needs a reason, and the model's original suggestion is kept."

## 4. The evidence (40 s)

Open [`eval/reports/2026-11-22_heldout_9ab7dba.md`](../eval/reports/2026-11-22_heldout_9ab7dba.md):

- "0 of 23 seeded personal-data values reached the model or the database."
- "10 of 10 cases that needed a person got one."
- "HIGH and CRITICAL recall is 0.82, below my 0.95 target. Two harms with no dollar
  amount, a wrong credit report and a discrimination complaint, were under-rated. Both
  still reached a human. I documented them instead of tuning on the test set."

Then show the green CI run on GitHub: "Every push runs the tests, an offline
evaluation that fails the build on any PII leak, a secret scan and Terraform validate,
all without cloud credentials."

## 5. Close (20 s)

"Terraform builds the whole thing in about two minutes and removes it in two, so it
costs nothing when it's not running." Show `python tasks.py leftovers` -> `CLEAN`.

## Live version: setup and teardown

```powershell
python tasks.py preflight
python tasks.py infra-up
python tasks.py env
python tasks.py smoke         # wait 5-10 min after infra-up if this returns 401/403
python tasks.py demo --live
python tasks.py infra-down    # ends with CLEAN: nothing left behind
```
