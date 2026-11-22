# Changelog

## v1.0.0 (2026-11-22)

First complete version: every milestone in the project plan is done. Defaults are
prompt `classify_v3` and rules `rules_v3`. Held-out results are in the
[README](README.md#results-held-out-set-never-tuned-on) and the
[system card](docs/system-card.md).

### M6: docs, CI and showcase
- GitHub Actions CI with no cloud credentials: ruff, unit tests, an offline
  evaluation with a PII gate (`--fail-on-pii-leak`), pre-commit hygiene and a secret
  scan, and `terraform fmt` + `validate`.
- `--offline` for `triage` and `batch` (Presidio + MOCK model), and
  `python tasks.py demo`, which runs five demo complaints, the review queue and stats
  with no Azure.
- [System card](docs/system-card.md), [demo script](docs/demo.md), final README.

### M5: hardening
- `classify_v2`, then `classify_v3`: a privacy definition, thresholds, strict distress,
  tone neutrality, CRITICAL examples and a fee tie-break.
- Sign-off name redaction for both PII providers.
- `rules_v2` severity floors: R9 money, R10 duration, R11 vulnerability.
- `rules_v3`: the model's distress flag on its own gives HIGH + review, not CRITICAL.
- Labelling guide v1.1; red-team case rt-21.
- Held-out, against M4: PII leaks 1 -> 0, review recall 0.90 -> 1.00, severity
  0.63 -> 0.80. HIGH + CRITICAL recall 0.91 -> 0.82 is a documented gap.

### M4: dataset and evaluation harness
- 80 labelled situations -> seeded dev (50) and held-out (30) sets, 21 red-team cases
  and 10 counterfactual pairs.
- Evaluation harness: metrics, PII leak scan of the model input and the database,
  baseline comparison, caching, and an offline mock model.

### M3: rules, routing, audit log and review
- Deterministic rules R1-R8 that can only raise scrutiny, department routing, a
  SQLite audit log (redacted only), and a review queue with approve / override and
  a reason.

### M2: LLM classifier
- `gpt-4.1-mini` with a strict JSON schema, Pydantic validation, one retry, content
  filter handling and a versioned prompt.

### M0 + M1: foundations and PII
- Terraform environment (Entra ID only, key auth disabled), preflight checks, `.env`
  generation and a smoke test.
- Azure AI Language PII redaction with a Presidio fallback, fail-closed behaviour,
  name propagation and enrichment.
