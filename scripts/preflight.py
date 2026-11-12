"""Preflight: can this subscription host the environment? Run before the first apply.

Read-only. It never creates anything. It checks:
  1. tools installed (az, terraform)
  2. Azure CLI signed in with a *usable* token (not just a cached account)
  3. Microsoft.CognitiveServices provider registered
  4. allowed-locations policy (when it can be read)
  5. free-tier slot: an existing F0 Language account blocks a second one
  6. soft-deleted Cognitive Services accounts that can hold names or the F0 slot
  7. per region: model + version + SKU offered, and enough quota for the capacity

Settings come from infra/terraform/terraform.tfvars when present, else the
variables.tf defaults; CLI flags override both.

Usage:
  python scripts/preflight.py
  python scripts/preflight.py --location swedencentral --alt-locations eastus,westus3
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azcli import TF_DIR, CommandError, az_json, read_tfvars, which  # noqa: E402

DEFAULTS = {
    "location": "eastus2",
    "language_sku": "F0",
    "model_name": "gpt-4.1-mini",
    "model_version": "2025-04-14",
    "model_sku": "GlobalStandard",
    "model_capacity": "10",
    "deploy_model": "true",
}
FALLBACK_REGIONS = ["eastus2", "eastus", "swedencentral", "westus3", "canadaeast", "uksouth"]

OK, WARN, BLOCK, INFO = "OK", "WARN", "BLOCK", "INFO"


@dataclass
class Check:
    status: str
    title: str
    detail: str = ""


def _login_fix(err: str) -> str:
    if "AADSTS70043" in err or "AADSTS700082" in err:
        return "token expired via conditional access. Run: az login --use-device-code"
    if "az login" in err:
        return "not signed in. Run: az login --use-device-code"
    lines = [ln for ln in err.splitlines() if ln.strip()]
    last = lines[-1] if lines else "unknown error"
    return f"{last}  (if it persists: az login --use-device-code)"


def check_tools() -> list[Check]:
    checks = []
    for exe in ("az", "terraform"):
        found = which(exe)
        checks.append(
            Check(OK, f"{exe} installed", found)
            if found
            else Check(BLOCK, f"{exe} installed", f"'{exe}' not on PATH")
        )
    return checks


def check_login() -> tuple[Check, dict | None]:
    try:
        account = az_json("account", "show")
        # `account show` reads the local cache. Getting a token proves the login still works.
        az_json("account", "get-access-token", "--query", "expiresOn")
    except CommandError as exc:
        return Check(BLOCK, "Azure CLI login", _login_fix(exc.stderr)), None
    env_sub = os.environ.get("ARM_SUBSCRIPTION_ID")
    detail = f"{account['name']} ({account['id']})"
    if env_sub and env_sub != account["id"]:
        return (
            Check(WARN, "Azure CLI login", f"{detail}; ARM_SUBSCRIPTION_ID points elsewhere"),
            account,
        )
    return Check(OK, "Azure CLI login", detail), account


def check_provider() -> Check:
    try:
        state = az_json(
            "provider", "show", "-n", "Microsoft.CognitiveServices", "--query", "registrationState"
        )
    except CommandError as exc:
        return Check(WARN, "Provider Microsoft.CognitiveServices", exc.stderr.splitlines()[0])
    if state == "Registered":
        return Check(OK, "Provider Microsoft.CognitiveServices", state)
    return Check(
        BLOCK,
        "Provider Microsoft.CognitiveServices",
        f"{state}. Run: az provider register -n Microsoft.CognitiveServices --wait",
    )


def allowed_locations() -> list[str] | None:
    """Best effort: read an 'allowed locations' policy if this identity can see one."""
    try:
        assignments = (
            az_json(
                "policy",
                "assignment",
                "list",
                "--disable-scope-strict-match",
                "--query",
                "[].parameters",
            )
            or []
        )
    except CommandError:
        return None
    for params in assignments:
        for key, val in (params or {}).items():
            if "allowedlocations" in key.lower().replace("_", "").replace("listof", ""):
                value = val.get("value") if isinstance(val, dict) else val
                if isinstance(value, list) and value:
                    return [str(v).lower() for v in value]
    return None


def check_policy(location: str, allowed: list[str] | None) -> Check:
    if allowed is None:
        return Check(
            INFO,
            "Allowed-locations policy",
            "none readable; a policy may still block at apply (RequestDisallowedByAzure)",
        )
    if location.lower() in allowed:
        return Check(OK, "Allowed-locations policy", f"{location} is allowed")
    return Check(BLOCK, "Allowed-locations policy", f"{location} not allowed. Allowed: {allowed}")


def check_free_tier(language_sku: str) -> Check:
    if language_sku != "F0":
        return Check(OK, "Language free-tier slot", f"language_sku={language_sku}, not needed")
    try:
        existing = (
            az_json(
                "cognitiveservices",
                "account",
                "list",
                "--query",
                "[?kind=='TextAnalytics' && sku.name=='F0'].{name:name, rg:resourceGroup}",
            )
            or []
        )
    except CommandError as exc:
        return Check(WARN, "Language free-tier slot", exc.stderr.splitlines()[0])
    if not existing:
        return Check(OK, "Language free-tier slot", "no F0 Language account in this subscription")
    names = ", ".join(f"{a['name']} ({a['rg']})" for a in existing)
    return Check(
        WARN,
        "Language free-tier slot",
        f'F0 already used by {names}. If that is not this project\'s own, set language_sku = "S"',
    )


def check_soft_deleted() -> Check:
    try:
        deleted = (
            az_json(
                "cognitiveservices",
                "account",
                "list-deleted",
                "--query",
                "[].{name:name, location:location, kind:kind}",
            )
            or []
        )
    except CommandError as exc:
        return Check(WARN, "Soft-deleted accounts", exc.stderr.splitlines()[0])
    if not deleted:
        return Check(OK, "Soft-deleted accounts", "none")
    names = ", ".join(f"{d['name']} [{d['kind']}, {d['location']}]" for d in deleted)
    return Check(
        WARN,
        "Soft-deleted accounts",
        f"{names}. They can hold the F0 slot. Purge with: az cognitiveservices account purge "
        "--name <name> --resource-group <rg> --location <loc>",
    )


def _norm(name: str) -> str:
    return name.replace("-", "").lower()


def check_region(location: str, model: str, version: str, sku: str, capacity: int) -> Check:
    title = f"Model {model} {version} / {sku} in {location}"
    try:
        models = az_json("cognitiveservices", "model", "list", "-l", location, timeout=240) or []
    except CommandError as exc:
        return Check(WARN, title, exc.stderr.splitlines()[0])

    matches = [
        m
        for entry in models
        if (m := entry.get("model") or {}).get("name") == model
        and m.get("version") == version
        and any(s.get("name") == sku for s in m.get("skus") or [])
    ]
    if not matches:
        return Check(BLOCK, title, "not offered here; try another region, version or SKU")
    # A Legacy model can still be *listed* with a SKU in a region that refuses new
    # deployments (seen: gpt-4.1-mini GlobalStandard in canadacentral -> 400 at apply).
    legacy = any(str(m.get("lifecycleStatus", "")).lower() == "legacy" for m in matches)

    try:
        usages = az_json("cognitiveservices", "usage", "list", "-l", location) or []
    except CommandError as exc:
        return Check(WARN, title, f"offered; quota unreadable: {exc.stderr.splitlines()[0]}")
    quota_name = f"OpenAI.{sku}.{model}"
    # Azure is inconsistent: the model is `gpt-4.1-mini` but its quota is
    # `OpenAI.GlobalStandard.gpt4.1-mini`. Compare without hyphens or case.
    wanted = _norm(quota_name)
    for u in usages:
        if _norm((u.get("name") or {}).get("value", "")) == wanted:
            free = float(u.get("limit", 0)) - float(u.get("currentValue", 0))
            if free >= capacity and legacy:
                return Check(
                    WARN,
                    title,
                    f"quota {free:g} free, but the model is Legacy: some regions list it yet "
                    "refuse new deployments. Prefer a region where it deployed before, "
                    "or a GA model",
                )
            if free >= capacity:
                return Check(OK, title, f"quota {free:g} free >= capacity {capacity}")
            if free > 0:
                return Check(
                    WARN, title, f"only {free:g} quota free; set model_capacity <= {int(free)}"
                )
            return Check(BLOCK, title, f"no quota ({quota_name} limit {u.get('limit')})")
    return Check(WARN, title, f"offered; no quota entry named {quota_name} found")


def main() -> int:
    tfvars = {**DEFAULTS, **read_tfvars(TF_DIR / "terraform.tfvars")}
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--location", default=tfvars["location"])
    parser.add_argument(
        "--alt-locations",
        default=None,
        help="comma-separated regions to try when the main one is blocked "
        "(default: the policy's allowed regions if readable, else a built-in list)",
    )
    parser.add_argument("--skip-alternatives", action="store_true")
    args = parser.parse_args()

    model, version = tfvars["model_name"], tfvars["model_version"]
    sku, capacity = tfvars["model_sku"], int(tfvars["model_capacity"])
    deploy_model = tfvars["deploy_model"].lower() == "true"

    checks: list[Check] = check_tools()
    if any(c.status == BLOCK for c in checks):
        return report(checks)

    login, _ = check_login()
    checks.append(login)
    if login.status == BLOCK:
        return report(checks)

    checks.append(check_provider())
    allowed = allowed_locations()
    policy = check_policy(args.location, allowed)
    checks.append(policy)
    checks.append(check_free_tier(tfvars["language_sku"]))
    checks.append(check_soft_deleted())

    if args.alt_locations:
        alternatives = [r.strip() for r in args.alt_locations.split(",") if r.strip()]
    else:
        alternatives = list(allowed) if allowed else FALLBACK_REGIONS
    alternatives = [r for r in alternatives if r.lower() != args.location.lower()]

    if deploy_model:
        if policy.status == BLOCK:
            main_status = BLOCK  # no point checking a region we cannot deploy to
        else:
            main_region = check_region(args.location, model, version, sku, capacity)
            checks.append(main_region)
            main_status = main_region.status
        if main_status == BLOCK and not args.skip_alternatives:
            for region in alternatives:
                if allowed is not None and region.lower() not in allowed:
                    continue
                alt = check_region(region, model, version, sku, capacity)
                alt.status = INFO if alt.status == OK else alt.status
                alt.title = f"(alternative) {alt.title}"
                checks.append(alt)
                if alt.status == INFO:
                    alt.detail += f'  -> set location = "{region}" in terraform.tfvars'
                    break
    else:
        checks.append(Check(INFO, "Model deployment", "deploy_model=false; skipped"))

    return report(checks)


def report(checks: list[Check]) -> int:
    width = max(len(c.title) for c in checks)
    for c in checks:
        print(f"[{c.status:5}] {c.title:<{width}}  {c.detail}")
    blocked = [c for c in checks if c.status == BLOCK and not c.title.startswith("(alternative)")]
    print()
    if blocked:
        print("VERDICT: BLOCKED")
        for c in blocked:
            print(f"  - {c.title}: {c.detail}")
        print("Record findings in docs/cost-and-limits.md.")
        return 1
    warns = [c for c in checks if c.status == WARN]
    print("VERDICT: READY" + (f" with {len(warns)} warning(s)" if warns else ""))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
