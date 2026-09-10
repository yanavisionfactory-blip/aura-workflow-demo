"""Operation-level readiness, signed release evidence, and customer diagnostics."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import get_settings
from .managed_connectors import managed_connection_reference
from .models import OperationCertification
from .native_connectors import current_capability_manifest
from .operation_contracts import enrich_operation
from .policy import operation_scope

SCENARIOS = {"read": {"execute", "receipt_resume"}, "write": {"execute", "read_back", "receipt_resume", "lost_response"}}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def connection_fingerprint(tool):
    # Include the secret's digest for unmanaged connections, never the secret itself.
    identity = managed_connection_reference(tool) or hashlib.sha256((tool.encrypted_credentials or "").encode()).hexdigest()
    return hashlib.sha256(canonical({"id": tool.id, "slug": tool.slug, "connection": identity,
        "integration": tool.config.get("integration_id"), "base_url": tool.base_url,
        "connection_revision": str(getattr(tool, "updated_at", "")) if managed_connection_reference(tool) else None})).hexdigest()


def validate_attestation(report, signature, key, *, workspace_id, tool, contract, now=None):
    if not key or len(key) < 32:
        raise ValueError("Trusted certification signing is not configured")
    if not hmac.compare_digest(hmac.new(key.encode(), canonical(report), hashlib.sha256).hexdigest(), signature):
        raise ValueError("Certification signature is invalid")
    now = now or datetime.now(timezone.utc)
    expires = datetime.fromisoformat(report["expires_at"].replace("Z", "+00:00"))
    issued = datetime.fromisoformat(report["issued_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None or issued.tzinfo is None or not issued <= now < expires or expires-issued > timedelta(days=30):
        raise ValueError("Certification validity window is invalid")
    if (report.get("workspace_id") != workspace_id or report.get("tool_id") != tool.id
        or report.get("connection_fingerprint") != connection_fingerprint(tool)
        or report.get("contract_hash") != contract["reliability"]["hash"]):
        raise ValueError("Certification does not match this connection and contract")
    required = SCENARIOS["read" if contract["permission_scope"] == "read" else "write"]
    if not required <= {key for key, value in report.get("scenarios", {}).items() if value == "passed"}:
        raise ValueError("Required live scenarios have not passed")
    if (contract["reliability"]["output_validation"] != "typed" or not report.get("provider_account_id")
        or not report.get("release_sha") or report.get("dedicated_test_account") is not True):
        raise ValueError("Typed contracts, a release and dedicated account evidence are required")
    if contract["permission_scope"] != "read" and not contract["reliability"].get("readback_operation"):
        raise ValueError("Write operation has no deterministic read-back contract")
    return expires


async def operation_readiness(session, workspace_id, tool, operation, stored=None):
    manifest = current_capability_manifest(tool.slug, stored)
    module = next((item for item in manifest.get("capabilities", []) if item.get("name") == operation), None)
    if not module:
        return {"execution_ready": False, "status": "unsupported", "reasons": ["Operation has no declared contract"]}
    module = enrich_operation(module)
    contract = module["reliability"]
    reasons = []
    if not tool.enabled or operation not in tool.allowed_operations:
        reasons.append("Connection or operation permission is unavailable")
    if any(read not in tool.allowed_operations for read in contract.get("readback_operations", [])):
        reasons.append("Read-back operation permission is unavailable")
    if contract["output_validation"] != "typed":
        reasons.append("Output contract remains provisional")
    if module["permission_scope"] != "read" and not contract.get("readback_operation"):
        reasons.append("Deterministic write verification is unavailable")
    certification = await session.scalar(select(OperationCertification).where(
        OperationCertification.workspace_id == workspace_id, OperationCertification.tool_id == tool.id,
        OperationCertification.operation == operation, OperationCertification.contract_hash == contract["hash"],
        OperationCertification.connection_fingerprint == connection_fingerprint(tool),
        OperationCertification.revoked.is_(False), OperationCertification.expires_at > datetime.now(timezone.utc),
    ).order_by(OperationCertification.created_at.desc()).limit(1))
    if not certification:
        reasons.append("Current live certification is missing or expired")
    return {"operation": operation, "contract_hash": contract["hash"], "execution_ready": not reasons,
        "status": "certified" if not reasons else "provisional" if contract["output_validation"] != "typed" else "unverified",
        "reasons": reasons, "provides": contract["provides"], "retry": contract["retry"],
        "readback_operation": contract.get("readback_operation"), "pagination": contract.get("pagination"),
        "reconciliation": contract.get("reconciliation"),
        "certification_id": certification.id if certification else None}


def diagnostic(run, attempts=(), pending_dispatches=0):
    errors = " ".join([run.error or "", *(item.error or "" for item in attempts)]).lower()
    code, action, owner = "none", None, None
    autonomy = (getattr(run, "execution_context", None) or {}).get(
        "__aura_autonomy__", {}
    )
    if run.status.value == "awaiting_approval":
        code, action, owner = "approval_required", "Review and approve the saved plan or action.", "customer"
    elif autonomy.get("next_attempt_at") and run.status.value == "recovering":
        code, action, owner = "autonomous_recovery", "AURA is diagnosing and retrying the saved workflow automatically.", "system"
    elif "uncertain" in errors:
        code, action, owner = "uncertain_write", "Check the provider resource or reconcile the saved action; do not repeat the write.", "support"
    elif "authorization_required" in errors or "credential" in errors:
        code, action, owner = "connection_required", "Reconnect the affected app, then resume this run.", "customer"
    elif "certif" in errors:
        code, action, owner = "certification_required", "Complete the operation's live certification before unattended execution.", "administrator"
    elif "budget" in errors:
        code, action, owner = "budget_exhausted", "Inspect the saved attempts and adjust the failing step before resuming.", "support"
    elif "incident" in errors or "trust" in errors:
        code, action, owner = "connector_incident", "Resolve the connector incident before resuming saved work.", "administrator"
    elif run.status.value in {"failed", "blocked", "waiting_for_action"}:
        code, action, owner = "review_required", "Inspect the saved evidence and failing step; resume after resolving the stated issue.", "customer"
    elif pending_dispatches:
        code, action, owner = "dispatch_pending", "Work is saved and awaiting worker dispatch.", "system"
    return {"code": code, "next_action": action, "owner": owner, "run_id": run.id,
            "saved_progress_preserved": True, "pending_dispatches": pending_dispatches,
            "autonomy": autonomy}
