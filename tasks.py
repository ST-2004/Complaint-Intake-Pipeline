"""Task runner that works the same in PowerShell, Git Bash, macOS and Linux.

    python tasks.py <task> [--yes]

Tasks:
  setup       create .venv, install pinned deps (editable), install pre-commit hooks
  preflight   read-only checks: login, provider, region policy, F0 slot, model quota
  infra-up    terraform init + apply (asks for confirmation unless --yes)
  env         write .env from terraform outputs
  smoke       one call to the Language service and one to the model
  pii-check   redact the seeded samples and report leaks [--provider presidio] [--show] [--enrich]
  test        unit tests (no cloud)
  lint        ruff + terraform fmt -check + terraform validate
  fmt         auto-format Python and Terraform
  infra-down  terraform destroy, then verify nothing is left (asks unless --yes)
  leftovers   list anything this project left behind (resource groups, soft-deleted accounts)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TF_DIR = ROOT / "infra" / "terraform"
VENV = ROOT / ".venv"
PROJECT_TAG = "complaints"  # matches var.project default


def venv_python() -> str:
    candidate = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def sh(*cmd: str, cwd: Path = ROOT, env: dict | None = None, check: bool = True) -> int:
    exe = shutil.which(cmd[0]) or cmd[0]
    print(f"$ {' '.join(cmd)}", flush=True)
    code = subprocess.run([exe, *cmd[1:]], cwd=cwd, env=env, check=False).returncode
    if check and code != 0:
        raise SystemExit(code)
    return code


def capture(*cmd: str, cwd: Path = ROOT) -> str:
    exe = shutil.which(cmd[0]) or cmd[0]
    proc = subprocess.run([exe, *cmd[1:]], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        msg = proc.stderr.strip()
        if "AADSTS70043" in msg or "az login" in msg:
            msg += "\n\nFix: az login --use-device-code"
        raise SystemExit(f"{' '.join(cmd)} failed:\n{msg}")
    return proc.stdout.strip()


def tf_env() -> dict:
    """azurerm 4.x requires ARM_SUBSCRIPTION_ID; take it from the az login context."""
    env = dict(os.environ)
    if not env.get("ARM_SUBSCRIPTION_ID"):
        env["ARM_SUBSCRIPTION_ID"] = capture("az", "account", "show", "--query", "id", "-o", "tsv")
    # Fail early with a clear message if the cached login is stale.
    capture("az", "account", "get-access-token", "--query", "expiresOn", "-o", "tsv")
    return env


# ---------------------------------------------------------------- tasks


def task_setup(_: list[str]) -> None:
    if not VENV.exists():
        print("Creating .venv")
        venv.create(VENV, with_pip=True)
    py = venv_python()
    sh(py, "-m", "pip", "install", "--upgrade", "pip")
    sh(py, "-m", "pip", "install", "-r", "requirements.lock")
    sh(py, "-m", "pip", "install", "--no-deps", "-e", ".")
    sh(py, "-m", "pre_commit", "install")
    print(
        "\nSetup done. Activate with:  .venv\\Scripts\\Activate.ps1  (or source .venv/bin/activate)"
    )


def task_preflight(args: list[str]) -> None:
    sh(venv_python(), "scripts/preflight.py", *args)


def task_infra_up(args: list[str]) -> None:
    env = tf_env()
    sh("terraform", "init", "-input=false", cwd=TF_DIR, env=env)
    apply = ["terraform", "apply", "-input=false"]
    if "--yes" in args:
        apply.append("-auto-approve")
    sh(*apply, cwd=TF_DIR, env=env)
    print("\nNext: python tasks.py env && python tasks.py smoke")
    print("Note: new role assignments can take 5-10 minutes to start working.")


def task_env(_: list[str]) -> None:
    sh(venv_python(), "scripts/make_env.py")


def task_smoke(_: list[str]) -> None:
    sh(venv_python(), "-m", "complaint_intake.smoke")


def task_pii_check(args: list[str]) -> None:
    sh(venv_python(), "-m", "complaint_intake.pii_check", *args)


def task_test(args: list[str]) -> None:
    sh(venv_python(), "-m", "pytest", *args)


def task_lint(_: list[str]) -> None:
    py = venv_python()
    sh(py, "-m", "ruff", "check", ".")
    sh(py, "-m", "ruff", "format", "--check", ".")
    sh("terraform", "fmt", "-check", "-recursive", cwd=TF_DIR)
    sh("terraform", "init", "-backend=false", "-input=false", cwd=TF_DIR)
    sh("terraform", "validate", cwd=TF_DIR)


def task_fmt(_: list[str]) -> None:
    py = venv_python()
    sh(py, "-m", "ruff", "check", "--fix", ".")
    sh(py, "-m", "ruff", "format", ".")
    sh("terraform", "fmt", "-recursive", cwd=TF_DIR)


def task_leftovers(_: list[str]) -> int:
    groups = json.loads(
        capture(
            "az",
            "group",
            "list",
            "--query",
            f"[?tags.project=='{PROJECT_TAG}' && tags.managed_by=='terraform'].name",
            "-o",
            "json",
        )
        or "[]"
    )
    deleted = json.loads(
        capture(
            "az",
            "cognitiveservices",
            "account",
            "list-deleted",
            "--query",
            "[].{name:name, location:location}",
            "-o",
            "json",
        )
        or "[]"
    )
    print(f"Resource groups still present: {groups or 'none'}")
    print(f"Soft-deleted Cognitive Services accounts: {deleted or 'none'}")
    if deleted:
        print(
            "Purge with: az cognitiveservices account purge --name <n> --resource-group <rg> "
            "--location <loc>"
        )
    clean = not groups and not deleted
    print("CLEAN: nothing left behind" if clean else "NOT CLEAN: see above")
    return 0 if clean else 1


def task_infra_down(args: list[str]) -> None:
    env = tf_env()
    destroy = ["terraform", "destroy", "-input=false"]
    if "--yes" in args:
        destroy.append("-auto-approve")
    sh(*destroy, cwd=TF_DIR, env=env)
    raise SystemExit(task_leftovers([]))


TASKS = {
    "setup": task_setup,
    "preflight": task_preflight,
    "infra-up": task_infra_up,
    "env": task_env,
    "smoke": task_smoke,
    "pii-check": task_pii_check,
    "test": task_test,
    "lint": task_lint,
    "fmt": task_fmt,
    "infra-down": task_infra_down,
    "leftovers": task_leftovers,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in TASKS:
        print(__doc__)
        return 0 if not argv else 2
    result = TASKS[argv[0]](argv[1:])
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
