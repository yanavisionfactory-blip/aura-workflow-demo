"""Safety gate and release callbacks for isolated automatic code repair.

This module is intentionally standard-library-only so the GitHub runner can use
it before application dependencies are trusted. Codex may edit the isolated
checkout, but this gate controls which changes are allowed to reach tests or a
canary. It never runs inside the production API process.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_PREFIXES = ("backend/app/",)
PROTECTED_PATHS = frozenset(
    {
        "backend/app/code_repair_sandbox.py",
        "backend/app/config.py",
        "backend/app/db.py",
        "backend/app/identity.py",
        "backend/app/main.py",
        "backend/app/migrations.py",
        "backend/app/models.py",
        "backend/app/security.py",
    }
)
PROTECTED_PREFIXES = (".github/", ".codex/", "infra/", "deploy/")
FORBIDDEN_ADDITIONS = (
    re.compile(r"shell\s*=\s*True"),
    re.compile(r"chmod\s+777"),
    re.compile(r"curl\b.*\|\s*(?:ba)?sh"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"recovery_github_token", re.IGNORECASE),
    re.compile(r"credential_encryption_key", re.IGNORECASE),
    re.compile(r"session_signing_key", re.IGNORECASE),
)


@dataclass
class GateReport:
    passed: bool
    base_sha: str
    changed_files: list[str] = field(default_factory=list)
    added_lines: int = 0
    deleted_lines: int = 0
    violations: list[str] = field(default_factory=list)


def _git(*arguments: str, root: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=root,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def validate_repair(base_sha: str, *, root: Path | None = None) -> GateReport:
    """Validate an uncommitted repair against an immutable baseline."""
    if not SHA_PATTERN.fullmatch(base_sha):
        raise ValueError("base_sha must be a full lowercase commit SHA")
    root = (root or Path.cwd()).resolve()
    tracked_names = [
        line.strip()
        for line in _git("diff", "--name-only", base_sha, "--", root=root).splitlines()
        if line.strip()
    ]
    untracked_names = [
        line.strip()
        for line in _git("ls-files", "--others", "--exclude-standard", root=root).splitlines()
        if line.strip()
    ]
    names = sorted(set(tracked_names + untracked_names))
    report = GateReport(passed=False, base_sha=base_sha, changed_files=names)
    if not names:
        report.violations.append("repair produced no source changes")
        return report

    for name in names:
        candidate_path = root / name
        candidate = candidate_path.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            report.violations.append(f"path escapes checkout: {name}")
            continue
        if name in PROTECTED_PATHS or name.startswith(PROTECTED_PREFIXES):
            report.violations.append(f"protected path changed: {name}")
        elif not name.startswith(ALLOWED_PREFIXES):
            report.violations.append(f"path is outside repair allowlist: {name}")
        if candidate_path.is_symlink():
            report.violations.append(f"symbolic links are not allowed: {name}")

    numstat = _git("diff", "--numstat", base_sha, "--", root=root)
    for line in numstat.splitlines():
        added, deleted, _ = line.split("\t", 2)
        if added == "-" or deleted == "-":
            report.violations.append("binary changes are not allowed")
            continue
        report.added_lines += int(added)
        report.deleted_lines += int(deleted)
    patch = _git("diff", "--unified=0", base_sha, "--", root=root)
    addition_parts = [
        "\n".join(
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
    ]
    for name in untracked_names:
        candidate = root / name
        if not candidate.is_file() or candidate.is_symlink():
            continue
        payload = candidate.read_bytes()
        if b"\0" in payload:
            report.violations.append(f"binary changes are not allowed: {name}")
            continue
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError:
            report.violations.append(f"non-UTF-8 changes are not allowed: {name}")
            continue
        lines = content.splitlines()
        report.added_lines += len(lines)
        addition_parts.append(content)
    additions = "\n".join(addition_parts)
    if report.added_lines + report.deleted_lines > 1500 and not any(
        "1500-line" in item for item in report.violations
    ):
        report.violations.append("repair exceeds the 1500-line change budget")
    for pattern in FORBIDDEN_ADDITIONS:
        if pattern.search(additions):
            report.violations.append(f"forbidden addition matched: {pattern.pattern}")
    report.passed = not report.violations
    return report


def wait_for_health(base_url: str, *, timeout_seconds: int = 300) -> dict[str, Any]:
    """Require both liveness and readiness before promotion."""
    deadline = time.monotonic() + timeout_seconds
    failures: list[str] = []
    while time.monotonic() < deadline:
        checks: dict[str, Any] = {}
        try:
            for path in ("/health", "/ready"):
                with urlopen(f"{base_url.rstrip('/')}{path}", timeout=10) as response:
                    checks[path] = json.loads(response.read().decode())
                    if response.status != 200:
                        raise RuntimeError(f"{path} returned {response.status}")
            return {"ok": True, "checks": checks}
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
            failures.append(type(exc).__name__)
            time.sleep(5)
    return {"ok": False, "failure_types": failures[-10:]}


def send_callback(
    callback_base_url: str,
    incident_id: str,
    secret: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    request = Request(
        (
            f"{callback_base_url.rstrip('/')}/v1/internal/recovery-incidents/"
            f"{incident_id}/pipeline-result"
        ),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Aura-Recovery-Timestamp": timestamp,
            "X-Aura-Recovery-Signature": signature,
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def _json_argument(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise TypeError("result arguments must be JSON objects")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate")
    gate.add_argument("--base", required=True)
    health = commands.add_parser("health")
    health.add_argument("--url", required=True)
    health.add_argument("--timeout", type=int, default=300)
    callback = commands.add_parser("callback")
    callback.add_argument("--url", required=True)
    callback.add_argument("--incident", required=True)
    callback.add_argument("--workspace", required=True)
    callback.add_argument("--fingerprint", required=True)
    callback.add_argument(
        "--status",
        choices=("failed", "canary_failed", "rolled_back", "promoted"),
        required=True,
    )
    callback.add_argument("--sandbox-result", default="{}")
    callback.add_argument("--release-result", default="{}")
    args = parser.parse_args()

    if args.command == "gate":
        report = validate_repair(args.base)
        print(json.dumps(asdict(report), sort_keys=True))
        return 0 if report.passed else 1
    if args.command == "health":
        result = wait_for_health(args.url, timeout_seconds=args.timeout)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1

    secret = os.environ.get("RECOVERY_PIPELINE_CALLBACK_SECRET", "")
    if not secret:
        raise RuntimeError("RECOVERY_PIPELINE_CALLBACK_SECRET is required")
    result = send_callback(
        args.url,
        args.incident,
        secret,
        {
            "workspace_id": args.workspace,
            "fingerprint": args.fingerprint,
            "status": args.status,
            "sandbox_result": _json_argument(args.sandbox_result),
            "release_result": _json_argument(args.release_result),
        },
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
