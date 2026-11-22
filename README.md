# Bank Complaint Intake Pipeline

AI-assisted triage of retail-bank complaints on Azure, with privacy built in. Personal
data is redacted **before** any model sees it, the model's output is schema-validated
and checked by deterministic rules, risky cases go to a human, and an evaluation
harness measures how the whole system behaves. Terraform builds and removes the
entire environment in any subscription that allows it.

> **Proof of concept on synthetic data only.** Not production banking software. Not
> affiliated with any employer or financial institution. All names, numbers and
> complaints are generated.

## Status

| Milestone | State |
|---|---|
| **M0** Foundations and infrastructure spike | Done: apply, env, smoke, destroy and a second apply verified (westus3, ~2 min each way) |
| **M1** PII detection and enrichment | Done: Azure and Presidio providers, 0 / 28 seeded values leaked on both ([details](docs/pii-redaction.md)) |
| **M2** LLM classifier | Done: 10/10 schema-valid on the first attempt, prompt version recorded ([details](docs/classifier.md)) |
| **M3** Rules, routing, audit log and review | Done: end-to-end pipeline, rules R1-R8, review queue, 0/28 seeded PII in the database ([details](docs/rules-and-review.md)) |
| **M4** Dataset and evaluation harness | Harness and data done, tested offline; **baseline run on Azure pending** ([details](docs/evaluation.md)) |
| M5 Hardening | not started |
| M6 Docs, CI and showcase | not started |

## Quick start

Needs Python 3.12+, Terraform 1.6+, Azure CLI. Every task is `python tasks.py <task>`,
which works the same in PowerShell, Git Bash, macOS and Linux.

```powershell
python tasks.py setup              # .venv, pinned deps, pre-commit hooks
.venv\Scripts\Activate.ps1         # or: source .venv/bin/activate

az login --use-device-code
az account set --subscription "<name or id>"

python tasks.py preflight          # read-only: login, provider, region policy, F0 slot, quota
copy infra\terraform\terraform.tfvars.example infra\terraform\terraform.tfvars   # optional: adjust
python tasks.py infra-up           # terraform init + apply (asks to confirm)
python tasks.py env                # writes .env from terraform outputs
python tasks.py smoke              # one PII call + one model call, Entra ID auth
python tasks.py run "My card was charged twice for the same purchase..."   # triage one complaint
python tasks.py review             # human-review queue (works offline too)
python tasks.py infra-down         # terraform destroy + check nothing is left behind
```

New role assignments can take 5-10 minutes to work; if `smoke` returns 401/403 right
after `infra-up`, wait and retry.

Evaluation: `python tasks.py eval` (dev + red-team + counterfactual), `eval --set heldout
--save-baseline` (the baseline), `eval --offline` (no Azure, mock model). See
[docs/evaluation.md](docs/evaluation.md).

Other tasks: `pii-check` (redact the seeded samples and report leaks; add
`--provider presidio` to run fully offline), `classify-check` (redact, enrich and
classify 10 labelled samples; needs the environment up), `test` (unit tests, no cloud), `lint`
(ruff + terraform fmt/validate), `fmt`, `leftovers`. Live tests: `pytest -m integration`.

## What gets created

`terraform apply` creates one resource group containing an Azure AI Language account
(PII, sentiment, key phrases), an Azure AI Services account with a `gpt-4.1-mini`
deployment, and two role assignments scoped to those accounts for the signed-in
identity. Key-based auth is disabled; everything uses Entra ID. Nothing is hard-coded
to a subscription, tenant or region. See [docs/cost-and-limits.md](docs/cost-and-limits.md)
for cost, limits and what each subscription allowed.

## Repository layout

```
infra/terraform/     Terraform: versions, variables, main, outputs, example tfvars
scripts/             preflight.py, make_env.py (Python so they run on Windows too)
src/complaint_intake config, auth, input_checks, redaction/ (Azure + Presidio),
                     enrichment, schemas, prompts, model_client, classifier, rules,
                     pipeline, store (SQLite audit + review), cli, smoke, checks
prompts/             versioned prompts (classify_v1.md)
config/              versioned rules configuration (rules_v1.toml)
data/                synthetic only: situations, generated dev/held-out sets, labelling guide
eval/                red-team and counterfactual sets, reports/
tests/               unit tests (offline) + integration tests (marked)
docs/                cost-and-limits.md, pii-redaction.md, classifier.md, rules-and-review.md,
                     evaluation.md
tasks.py             task runner
```

## Principles

Synthetic data only. PII never reaches the model or the logs (fail closed). The model
suggests; code and people decide. Structured, validated output. Complaint text is
untrusted input. Least privilege. Measure, do not assume. Reproducible and disposable
infrastructure. Honest documentation.

## License

MIT. See [LICENSE](LICENSE).
