# System card: Bank Complaint Intake Pipeline v1.0.0

A responsible-AI summary of what this system does, how it was tested, where it
fails, and what it must not be used for. Every number on this page comes from the
held-out report
[`eval/reports/2026-11-22_heldout_9ab7dba.md`](../eval/reports/2026-11-22_heldout_9ab7dba.md)
unless stated otherwise.

> **Status: proof of concept on synthetic data.** It has never processed a real
> customer complaint and is not approved for one. It is not affiliated with any
> bank.

## 1. Purpose

Read a free-text retail-banking complaint and produce a **suggestion** for triage:
a short summary, a category (10 classes), a severity (LOW to CRITICAL), a routing
queue, and whether a person must look at it first. The goal is to shorten the time
until urgent complaints (fraud, distress, regulatory threats) reach the right person,
not to answer or resolve complaints.

**Intended users:** complaint-handling staff and team leads, who see only redacted
text.

**Out of scope, and must not be used for:** replying to customers; deciding
refunds, credit, account closure or anything else with a financial or legal effect on
a customer; regulatory complaint reporting; assessing individual staff; or any data
that is not synthetic until the gaps in section 8 are closed.

## 2. How a decision is made

```
complaint -> input checks -> PII redaction (fail closed) -> enrichment
          -> LLM suggestion (strict JSON schema) -> deterministic rules -> route / human review
          -> audit log (redacted only)
```

| Step | What it does | Who decides |
|---|---|---|
| Input checks | Empty, too short, noise, > 20,000 chars, injection patterns, delimiter tampering | Code |
| PII redaction | Azure AI Language PII (Presidio fallback); names, cards, accounts, phones, emails, addresses, IDs, sign-off names. **If redaction fails, the model is never called** (R8) | Code |
| Enrichment | Sentiment and key phrases on the redacted text | Azure service |
| Classification | `gpt-4.1-mini`, prompt `classify_v3`, temperature 0, strict JSON schema, Pydantic validation, one retry | Model **suggests** |
| Rules `rules_v3` | R1-R11: fraud floor, privacy office, regulatory language, distress, injection, unclear input, unusable output, PII failure, money / duration / vulnerability severity floors | Code; can only **raise** scrutiny, never lower it (checked) |
| Review | Every case a rule flags waits in a queue; a reviewer approves or overrides with a recorded reason | **A person** |

The department is derived from the category in code, not chosen by the model.
The prompt version, rules version, model deployment and every fired rule are stored
with each case.

## 3. Data

- **All data is synthetic.** 80 hand-written situations, expanded with Faker
  (seed `20261121`) into a 50-case dev set and a 30-case held-out set, plus 21
  red-team cases and 10 counterfactual pairs. Labels follow
  [`data/LABELING_GUIDE.md`](../data/LABELING_GUIDE.md) v1.1.
- Labels were written by one person (the author). Inter-annotator agreement has not
  been measured; the guide's 20% relabel check is still open.
- The held-out set was used only at milestone ends and never tuned on.
- Complaint text is English only. Names and personal details come from five Faker
  locales (en_CA, fr_CA, en_IN, es_MX, en_GB) so that redaction meets more than
  Anglo names. Complaints written in French or any other language are **not** tested.

## 4. Results (held-out, n = 30)

| Measure | Result | Target | Met |
|---|---|---|---|
| Seeded PII values reaching the model or the database | **0 / 23** | 0 | yes |
| Cases needing a human that got one (review recall) | **10 / 10** | >= 0.95 | yes |
| Category macro-F1 | **0.98** | >= 0.85 | yes |
| Schema-valid on first attempt | 29 / 30 | >= 0.95 | yes |
| Red-team pass rate | 20 / 21 | >= 0.90 | yes |
| HIGH + CRITICAL recall | **0.82 (9/11)** | >= 0.95 | **no** |
| Counterfactual consistency | 9 / 10 | >= 0.95 | **no** |
| Severity accuracy | 0.80 | n/a | |
| Review precision (reviews that were needed) | 0.71 | n/a | |
| Latency p95 / cost per complaint | 8.8 s / ~$0.0006 | n/a | |

With n = 30, one case moves most rates by 3 to 10 points. Running the same code
twice gave different answers on 3 of 30 cases (temperature 0 is not fully
deterministic), so treat any one-case difference as noise.

## 5. Fairness

- **Counterfactual pairs** change only things that should not matter (name and
  implied origin, gender, pronouns and relationship, typos, second-language English,
  tone, all capitals, missing punctuation) and check that
  category and severity stay the same: 9/10 held. The failing pair (cf-06) is text
  that genuinely fits two categories, and the all-capitals version flips between them.
- The classifier never sees names (they are redacted first), which removes the most
  direct route for name-based bias but not bias from dialect, spelling or topic.
- **Known gap:** a discrimination complaint (sc-04, a customer mocked for their accent)
  was rated LOW instead of HIGH. The labelling guide does not list discrimination as
  HIGH, so neither the guide nor the rules caught it. It still went to a human.
- Not measured: performance by language variety or literacy level, or with real
  demographic data (there is none).

## 6. Privacy and security

- Redaction happens **before** the model call; logs and the database hold
  redacted text only. A leak check scans the exact model input and the database
  dump for every seeded value on every evaluation run, and CI fails the build on
  any leak (offline, Presidio).
- No keys: Entra ID only, with key-based auth disabled on both Azure accounts, and
  role assignments scoped to those two accounts.
- Complaint text is treated as untrusted input: it is delimited, injection patterns
  are checked in code, Azure Prompt Shields blocks direct jailbreaks, and an injection
  suspicion forces review (R5). The model has no tools and cannot take actions.
- The Presidio debug logger was found to print raw PII during development; it is
  pinned to WARNING. This is the kind of leak a production review must look for.

## 7. Failure behaviour

The system fails **towards a human**. If the model call fails, is filtered or returns
invalid JSON twice, R7 sends the case to review with the reason recorded. This
happened for real in the final run (rate limiting on two cases) and was handled. If
redaction fails, nothing is sent to the model and no text is stored (R8).

## 8. Known limitations

1. **Severity under-rates harm without a number.** Wrong credit reports, refused
   credit and discrimination have no dollar amount or duration for rules R9 and R10
   to check (pd-07, sc-04). Fixing it needs a guide change **and a new held-out set**.
2. Small, synthetic, single-annotator dataset. Real complaints are longer, messier
   and multilingual.
3. Review precision 0.71: about 3 in 10 reviews were not strictly needed. That is the
   deliberate cost of high review recall, and in production it must be measured
   against staff capacity.
4. Run-to-run variation at temperature 0, and capacity limits (10K tokens per minute)
   that caused real call failures during evaluation bursts.
5. Indirect-attack and groundedness detection in Azure AI Content Safety are not
   enabled.
6. The redaction categories cover North American formats. Other countries' IDs and
   addresses are untested.

## 9. What a bank would still need before production

- Real, consented, de-identified complaint data with **multiple annotators**,
  measured agreement, and a labelling guide owned by the complaints function.
- Model risk management sign-off (for example under OSFI E-23 or SR 11-7), a
  privacy impact assessment, and legal review of complaint-handling obligations.
- Monitoring: drift in category mix, override rate per category, PII-leak sampling,
  latency and cost; plus a fallback process when the service is down.
- Network isolation (private endpoints), data residency decisions, customer-managed
  keys if required, retention and deletion rules for the audit log.
- A load-tested deployment with capacity sized to peak volume, and retries with
  back-off.
- Accessibility and usability testing of the reviewer workflow with the staff who
  will use it.
- French (and other language) support, tested to the same standard.

## 10. Versions

| Component | Version |
|---|---|
| Model | `gpt-4.1-mini` (Global Standard), westus3 |
| Prompt | `prompts/classify_v3.md` (sha256 `abfc6b823329...`) |
| Rules | `config/rules_v3.toml` |
| Labelling guide | v1.1 |
| Dataset | `data/synthetic/heldout.jsonl` (sha256 `a82734faa8e533ad...`) |

Earlier prompt and rules versions are kept so that every older report can be
reproduced. See [hardening.md](hardening.md) for how v3 was reached.
