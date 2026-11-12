# Cost, limits and per-subscription findings

Free tiers, quotas and region policy differ between subscriptions. This file records
what each subscription actually allowed, so the next run (or someone else's) starts
from facts. Verify prices and limits on the current Azure pricing pages; the figures
below are what the plan assumed and may have changed.

## What the environment creates

| Resource | Tier | Cost driver |
|---|---|---|
| Resource group | n/a | free |
| Azure AI Language (`TextAnalytics`) | `F0` (free) or `S` | text records; F0 has a monthly allowance (about 5,000 records, 5,120 characters per document when planned; confirm) |
| Azure AI Services account (`AIServices`) | `S0` | free on its own |
| Model deployment (`gpt-4.1-mini`, `GlobalStandard`, capacity 10K TPM) | pay per token | input + output tokens x price per token |
| Role assignments | n/a | free |

Nothing is billed for idle capacity on a `GlobalStandard` deployment, but **destroy
after every working session** anyway (`python tasks.py infra-down`) and set a
budget alert before the first apply:

```powershell
# Portal: Cost Management > Budgets > Add. Or (adjust amount and dates):
az consumption budget create --budget-name complaints-poc --amount 10 `
  --category cost --time-grain monthly `
  --start-date 2026-11-01 --end-date 2027-11-01
```

## Known limits and how the code handles them

| Limit | Handling |
|---|---|
| One F0 resource per kind per subscription (soft-deleted ones can count) | `language_sku` variable; preflight warns when the F0 slot is taken; provider purges on destroy |
| Region policy (`RequestDisallowedByAzure`) | `location` variable; preflight reads an allowed-locations policy when visible and tries alternative regions |
| Model quota | model name, version, SKU, capacity are variables; preflight checks `az cognitiveservices usage list`; `deploy_model = false` to use an existing deployment |
| Role-assignment rights | `assign_roles = false`, then an admin grants the roles |
| Role propagation delay | new assignments can take 5-10 minutes; the smoke test prints this hint on 401/403 |
| CLI token expiry under conditional access (`AADSTS70043`) | preflight and smoke test detect it and print `az login --use-device-code` |
| Soft-deleted account names | random 5-character suffix; `purge_soft_delete_on_destroy = true`; `python tasks.py leftovers` lists anything remaining |

## Findings per subscription

Fill one block per subscription after running `python tasks.py preflight` and the
first apply. Do not record subscription ids or tenant ids here (public repo).

### Subscription A: Azure for Students

| Item | Finding |
|---|---|
| Date | 2026-11-11 |
| Preflight verdict | First run BLOCKED at login: `AADSTS70043` (CLI token past the 30-day sign-in-frequency limit); fixed with `az login --use-device-code`. Second run BLOCKED on region policy; after the changes below: READY. |
| Region used | `westus3`. First choice `canadacentral` passed preflight but the deployment failed at apply: `InvalidResourceProperties: The specified SKU 'GlobalStandard' for model 'gpt-4.1-mini 2025-04-14' is not supported in this region`. The model is now **Legacy** (inference retirement 2027-04-14): `canadacentral` still lists the SKU but refuses new deployments. Preflight now warns on Legacy models. |
| Regions allowed by policy | `canadacentral`, `westus3`, `centralus`, `westus`, `norwayeast` (an "allowed locations" policy; `eastus2`, the variable default, is blocked) |
| Language SKU | `F0`. The free slot was held by a Language account from an earlier project; it was deleted and purged to free the slot. |
| Model / version / SKU / capacity | `gpt-4.1-mini` / `2025-04-14` / `GlobalStandard` / 10. Quota 5,000, 100 already used by another deployment (shared across regions for GlobalStandard). |
| Quota naming quirk | The quota entry is `OpenAI.GlobalStandard.gpt4.1-mini` (no hyphen after `gpt`) while the model is `gpt-4.1-mini`; preflight compares names without hyphens. |
| Role assignments created by Terraform? | Yes (`assign_roles = true`). Smoke test passed right after apply, no propagation wait needed. |
| Endpoint + token scope that worked | `https://<ai-subdomain>.openai.azure.com/openai/v1/` with `https://cognitiveservices.azure.com/.default`; Language via its `cognitiveservices.azure.com` custom subdomain. Entra ID only, keys disabled. |
| Apply time / destroy time | ~120 s apply (7 resources), ~135 s destroy |
| Leftovers after destroy | None (no resource groups, no soft-deleted accounts) on all three destroys |
| Smoke test | Language PII 1.5-2.4 s; model 2.2-3.1 s, 15 tokens per call |
| PII finding | An invented surname (`Fakename`) was **not** detected as a Person and leaked; realistic synthetic names are redacted. The leak check now tests each token, not the whole value. Use realistic Faker names in the dataset (M4). |
| Model lifecycle | `gpt-4.1-mini 2025-04-14` retires for inference 2027-04-14. Fine for this project; for a longer life switch to a GA model such as `gpt-5.4-mini` (a reasoning model: check temperature support first). |

### Subscription B: portability check (later)

_Same table._

## Optional: remote state

Local state is the default and is git-ignored. To share state, create a storage
account with RBAC (no access keys) and add to `versions.tf`:

```hcl
backend "azurerm" {
  resource_group_name  = "rg-tfstate"
  storage_account_name = "<unique-name>"
  container_name       = "tfstate"
  key                  = "complaint-intake.tfstate"
  use_azuread_auth     = true
}
```
