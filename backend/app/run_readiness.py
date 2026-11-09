"""Read-only account/capability/resource checks displayed before Start."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from . import meta_ads
from .config import get_settings
from .execution_preflight import _account_label, _connection_credentials
from .extended_outcomes import required_reads
from .models import AuditEvent, CapabilityManifest, ToolConnection
from .policy import canonical_plan_hash
from .providers import ProviderExecutor


def account_fingerprint(tool, verification):
    identity = (verification or {}).get("identity") or {}
    stable = next((str(identity[k]) for k in ("sub", "id", "user_id", "email") if identity.get(k)), None)
    if not stable:
        stable = tool.external_account_id or tool.external_connection_id
    # The connection ID also prevents a different route/account being substituted.
    return hashlib.sha256(json.dumps([tool.id, stable], separators=(",", ":")).encode()).hexdigest()


async def check_run_readiness(session, run, plan):
    now = datetime.now(UTC)
    checks, bindings = [], {}
    required = {}
    for step in plan.steps:
        for slug, op in [(step.tool_slug, step.operation), *([(step.fallback_tool_slug, step.fallback_operation)] if step.fallback_tool_slug and step.fallback_operation else [])]:
            required.setdefault(slug, set()).update({op, *required_reads(op, step.arguments)})
        if step.tool_slug == meta_ads.SLUG and step.arguments.get("account_id") is not None:
            required[step.tool_slug].add("meta-ads.accounts.list")
    tools = (await session.scalars(select(ToolConnection).where(
        ToolConnection.workspace_id == run.workspace_id, ToolConnection.slug.in_(required),
    ))).all()
    by_slug = {tool.slug: tool for tool in tools}
    credentials = {}
    manifests = {}
    for slug, operations in sorted(required.items()):
        tool = by_slug.get(slug)
        row = {"tool_slug": slug, "operations": sorted(operations), "status": "blocked"}
        checks.append(row)
        if not tool or not tool.enabled:
            row.update(code="connection_required", message=f"Connect the selected {slug} account.")
            continue
        manifest = await session.scalar(select(CapabilityManifest).where(
            CapabilityManifest.workspace_id == run.workspace_id, CapabilityManifest.tool_id == tool.id,
        ))
        if not manifest or manifest.status != "verified":
            row.update(code="connection_unverified", message=f"Verify {tool.display_name} access.")
            continue
        try:
            creds, verification, blocker = await _connection_credentials(session, tool, manifest)
        except Exception:  # noqa: BLE001 — sanitize remote failure before returning diagnostics  # Provider payloads/credentials never become a browser error message.
            row.update(code="connection_check_unavailable", message=f"Could not verify {tool.display_name} right now. Check again before starting.")
            continue
        if blocker:
            row.update(code=blocker["code"], message=blocker["message"])
            continue
        from .connection_permissions import kpi_scope_missing, refresh_granted_readbacks
        from .orchestrator import refresh_native_connection_contract
        refresh_native_connection_contract(tool)
        refresh_granted_readbacks(tool)
        if slug == "google" and kpi_scope_missing(operations, creds or {}):
            row.update(code="permission_required", message="Reconnect Google with spreadsheet access so AURA can verify permission to create and read this workbook.")
            continue
        missing = sorted(operations - set(tool.allowed_operations or []))
        if missing:
            row.update(code="capability_required", missing_operations=missing,
                       message=f"The selected {tool.display_name} connection needs these capabilities: {', '.join(missing)}.")
            continue
        credentials[slug], manifests[slug] = creds or {}, manifest.manifest
        bindings[slug] = {"connection_id": tool.id, "account_fingerprint": account_fingerprint(tool, verification)}
        row.update(status="passed", connected_account=_account_label(verification),
                   message=f"{tool.display_name}: account and required capabilities verified.")
        if slug == meta_ads.SLUG:
            row.update(account_label="Meta login", message="Meta sign-in and reporting permissions verified. The reporting ad account is checked separately below.")
    checks.extend(await _meta_account_checks(plan.steps, credentials, by_slug, manifests))
    # Check exact, existing targets. Destinations produced by earlier steps are
    # verified by their creation receipt before a dependent step may use them.
    for step in plan.steps:
        if step.tool_slug not in credentials:
            continue
        args = step.arguments or {}
        probe = None
        if step.operation == "drive.spreadsheet.resolve":
            probe = (step.operation, args)
        elif step.operation == "sheets.append":
            probe = ("sheets.read", {"spreadsheet_id": args.get("spreadsheet_id"), "range": args.get("range", "Sheet1!A1")})
        elif step.operation in {"sheets.read", "docs.get", "calendar.get"}:
            probe = (step.operation, args)
        if not probe or "{{" in json.dumps(probe[1]):
            continue
        row = {"type": "destination", "tool_slug": step.tool_slug, "operation": probe[0], "status": "blocked"}
        checks.append(row)
        try:
            executor = ProviderExecutor(credentials[step.tool_slug], by_slug[step.tool_slug].base_url,
                                        capability_manifest=manifests[step.tool_slug], timeout_seconds=15)
            result = await executor.execute(*probe)
            if step.operation == "drive.spreadsheet.resolve" and result.get("status") != "resolved":
                row.update(code="destination_unresolved", message="Choose one exact accessible spreadsheet before starting.")
            else:
                row.update(status="passed", message="The existing destination is accessible.")
        except Exception:  # noqa: BLE001 — sanitize remote failure before returning diagnostics
            row.update(code="destination_unavailable", message="The selected destination could not be read with this account.")
    report = {"version": 1, "plan_hash": canonical_plan_hash(plan.model_dump(mode="json")),
              "checked_at": now.isoformat(), "expires_at": (now + timedelta(seconds=max(1, get_settings().connection_probe_ttl_seconds))).isoformat(),
              "passed": bool(checks) and all(row["status"] == "passed" for row in checks),
              "checks": checks, "bindings": bindings}
    context = dict(run.execution_context or {})
    context.pop("__aura_preflight__", None)
    run.execution_context = {**context, "__aura_review_readiness__": report}
    session.add(AuditEvent(workspace_id=run.workspace_id, run_id=run.id, actor="readiness-controller",
                           event_type="run.review_readiness_checked", payload={"passed": report["passed"], "check_count": len(checks)}))
    await session.commit()
    return {key: value for key, value in report.items() if key != "bindings"}


async def _meta_account_checks(steps, credentials, tools, manifests):
    """Show the actual report target; a verified Meta login is not an ad account."""
    checks, discovery, discovery_error = [], None, False
    for step in steps:
        if step.tool_slug != meta_ads.SLUG or step.tool_slug not in credentials:
            continue
        args = step.arguments or {}
        if "account_id" not in args:
            continue
        row = {"type": "ad_account", "tool_slug": step.tool_slug, "operation": step.operation,
               "account_label": "Reporting ad account", "status": "blocked"}
        checks.append(row)
        if "{{" in str(args["account_id"]):
            row.update(status="passed", code="ad_account_deferred",
                       message="The ad account will come from an earlier discovery step. AURA verifies that exact account before reading its metrics.")
            continue
        try:
            selected = meta_ads.account_id(args["account_id"])
        except meta_ads.MetaAdsError:
            row.update(code="invalid_ad_account", message="Choose an ad account returned by Meta account discovery. A Meta login or business portfolio ID is not an ad account.")
            continue
        row["account_id"] = selected
        if discovery is None and not discovery_error:
            try:
                tool = tools[step.tool_slug]
                result = await ProviderExecutor(credentials[step.tool_slug], tool.base_url,
                    capability_manifest=manifests[step.tool_slug], timeout_seconds=15).execute("meta-ads.accounts.list", {})
                discovery = result["account_discovery"]
                if (not isinstance(discovery.get("accounts"), list)
                        or any(not isinstance(item, dict) or not item.get("id") for item in discovery["accounts"])):
                    raise ValueError("invalid_account_discovery")
            except Exception:  # noqa: BLE001 — remote content must not enter browser diagnostics
                discovery_error = True
        if discovery_error:
            row.update(code="ad_account_check_unavailable", message="Meta ad-account discovery could not complete. Check again; this does not mean the account has no campaigns.")
            continue
        account = next((item for item in discovery["accounts"] if item.get("id") == selected), None)
        row["available_accounts"] = [{"id": item["id"], "name": item.get("name", "Advertising account")}
                                     for item in discovery["accounts"] if isinstance(item, dict) and item.get("id")]
        if account is None:
            row.update(code="ad_account_not_discovered", connected_account=selected,
                       message="This reporting ad account was not found through this Meta connection. Change the plan to an available account, or check that the Facebook login has access to the intended ad account before reconnecting.")
            continue
        row.update(status="passed", connected_account=f"{account.get('name') or 'Advertising account'} · {selected}",
                   currency=account.get("currency"), timezone=account.get("timezone_name"),
                   message="Compare this ad account with the account selected in Ads Manager before starting. Verified access does not guarantee campaign data for the requested dates.")
        if step.operation == "meta-ads.insights.get":
            row.update(reporting_dates=f"{args.get('since', '')} – {args.get('until', '')}",
                       reporting_level=args.get("level", "campaign"))
    return checks

