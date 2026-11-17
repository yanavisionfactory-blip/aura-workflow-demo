"""Fixed-repository recovery dispatch through the operator's managed GitHub grant.

No provider token is read or copied. The broker authenticates the request using
the existing account. The connection workspace is configuration, never input
from a customer run. The command-line probe dispatches a harmless CI job only.
"""
from __future__ import annotations

import asyncio
import json
import re
from time import monotonic
from uuid import uuid4

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal, set_tenant_context
from .models import ToolConnection
from .pipedream_connect import pipedream_client_for_tool

REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}")
PROBE_EVENT = "aura_recovery_auth_probe"


class RecoveryGitHubConfigurationError(ValueError):
    pass


async def operator_connection():
    settings = get_settings()
    workspace_id = settings.recovery_github_connection_workspace_id
    if (not workspace_id or not REPOSITORY.fullmatch(settings.recovery_github_repository)
            or settings.recovery_github_repository.split("/")[-1] in {".", ".."}):
        raise RecoveryGitHubConfigurationError("recovery_operator_connection_not_configured")
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        tool = await session.scalar(select(ToolConnection).where(
            ToolConnection.workspace_id == workspace_id,
            ToolConnection.slug == "github", ToolConnection.enabled.is_(True)))
        config = tool.config if tool else {}
        if (not tool or config.get("managed_by") != "pipedream"
                or config.get("vendor_app") != "github"
                or not config.get("external_user_id") or not config.get("account_id")):
            raise RecoveryGitHubConfigurationError("recovery_operator_connection_unavailable")
        client = pipedream_client_for_tool(tool)
        user, account = config["external_user_id"], config["account_id"]
    verified = await client.verify_account(user, "github", account)
    if not verified.get("ok"):
        raise RecoveryGitHubConfigurationError("recovery_operator_connection_unverified")
    return client, user, account


async def dispatch_with_connection(payload: dict) -> None:
    client, user, account = await operator_connection()
    repository = get_settings().recovery_github_repository
    await client.proxy_request(user, account,
        {"method": "POST", "path": f"/repos/{repository}/dispatches"},
        {"body": payload}, allow_empty_response=True)


async def probe_dispatch(*, timeout_seconds: float = 150) -> dict:
    """Prove write authorization and a completed GitHub job without running Codex."""
    from .release_info import release_sha

    client, user, account = await operator_connection()
    repository = get_settings().recovery_github_repository
    probe_id = str(uuid4())
    sha = release_sha()
    if not sha:
        raise RecoveryGitHubConfigurationError("recovery_probe_requires_stamped_release")
    await client.proxy_request(user, account,
        {"method": "POST", "path": f"/repos/{repository}/dispatches"},
        {"body": {"event_type": PROBE_EVENT,
                  "client_payload": {"probe_id": probe_id, "release_sha": sha}}},
        allow_empty_response=True)
    # Never retry a POST whose outcome is uncertain. Read back the unique
    # dispatch instead, and require the expected workflow to finish successfully.
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        result = await client.proxy_request(user, account,
            {"method": "GET", "path": f"/repos/{repository}/actions/workflows/recovery-github-probe.yml/runs"},
            {"query": {"event": "repository_dispatch", "per_page": 30}})
        runs = result.get("workflow_runs", [])
        run = next((run for run in runs if run.get("display_title") == f"AURA recovery auth probe {probe_id}"), None)
        if run and run.get("status") == "completed":
            return {"ok": run.get("conclusion") == "success", "transport": "managed_github_connection",
                    "release_sha": sha, "workflow_run_id": run["id"], "conclusion": run.get("conclusion")}
        await asyncio.sleep(5)
    return {"ok": False, "reason_code": "recovery_probe_completion_timeout", "release_sha": sha}


async def _main() -> int:
    try:
        result = await probe_dispatch()
    except Exception as exc:  # noqa: BLE001 - diagnostic command must not print provider/DB payloads
        result = {"ok": False, "error_type": type(exc).__name__,
                  "http_status": getattr(exc, "status_code", None)}
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
