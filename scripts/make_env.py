"""Write the git-ignored .env from `terraform output -json`.

Keys this script manages are overwritten; any other keys already in .env
(for example DB_PATH or a PII_PROVIDER you changed) are kept.

Usage: python scripts/make_env.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _azcli import REPO_ROOT, TF_DIR, CommandError, run  # noqa: E402

DEFAULTS = {
    "AZURE_TOKEN_SCOPE": "https://cognitiveservices.azure.com/.default",
    "PII_PROVIDER": "azure",
    "DB_PATH": "./triage.db",
}


def parse_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def build_env(outputs: dict, existing: dict[str, str]) -> dict[str, str]:
    """Merge terraform outputs over existing .env values. Pure, so it is unit-tested."""

    def out(name: str) -> str:
        try:
            return str(outputs[name]["value"])
        except KeyError as exc:
            raise KeyError(
                f"terraform output '{name}' is missing; run `terraform apply` first"
            ) from exc

    env = dict(DEFAULTS)
    env.update(existing)
    env["AZURE_LANGUAGE_ENDPOINT"] = out("language_endpoint")
    env["AZURE_AI_ENDPOINT"] = out("openai_v1_endpoint")
    env["MODEL_DEPLOYMENT"] = out("model_deployment")
    return env


def render_env(env: dict[str, str]) -> str:
    header = "# Written by scripts/make_env.py from terraform outputs. Git-ignored. No secrets.\n"
    return header + "".join(f"{k}={v}\n" for k, v in env.items())


def main() -> int:
    try:
        raw = run(["terraform", "output", "-json"], cwd=TF_DIR).stdout
    except CommandError as exc:
        print(f"Could not read terraform outputs: {exc.stderr}", file=sys.stderr)
        return 1
    outputs = json.loads(raw or "{}")
    if not outputs:
        print("No terraform outputs found. Run `python tasks.py infra-up` first.", file=sys.stderr)
        return 1

    env_path = REPO_ROOT / ".env"
    existing = parse_env(env_path.read_text(encoding="utf-8")) if env_path.exists() else {}
    try:
        env = build_env(outputs, existing)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 1
    env_path.write_text(render_env(env), encoding="utf-8")
    print(f".env written ({len(env)} keys): {', '.join(env)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
