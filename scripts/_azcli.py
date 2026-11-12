"""Small helpers shared by the scripts: run `az` / `terraform`, parse tfvars.

Python rather than shell so every script runs the same on Windows PowerShell,
Git Bash, macOS and Linux.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TF_DIR = REPO_ROOT / "infra" / "terraform"


class CommandError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stderr: str) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"{' '.join(cmd)} failed ({returncode}): {self.stderr}")


@dataclass(frozen=True)
class Result:
    stdout: str
    stderr: str


def which(exe: str) -> str | None:
    # On Windows `az` is az.cmd; shutil.which resolves PATHEXT so we never need shell=True.
    return shutil.which(exe)


def run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 180) -> Result:
    exe = which(cmd[0])
    if exe is None:
        raise CommandError(cmd, 127, f"'{cmd[0]}' was not found on PATH")
    proc = subprocess.run(
        [exe, *cmd[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr or proc.stdout)
    return Result(proc.stdout, proc.stderr)


def az_json(*args: str, timeout: float = 180) -> Any:
    out = run(["az", *args, "-o", "json"], timeout=timeout).stdout
    return json.loads(out) if out.strip() else None


_TFVAR_LINE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(".*?"|[^#\s]+)')


def read_tfvars(path: Path) -> dict[str, str]:
    """Read simple `key = value` scalars from a .tfvars file (maps/lists are skipped)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _TFVAR_LINE.match(line)
        if not match:
            continue
        key, raw = match.groups()
        if raw.startswith("{") or raw.startswith("["):
            continue
        values[key] = raw.strip('"')
    return values
