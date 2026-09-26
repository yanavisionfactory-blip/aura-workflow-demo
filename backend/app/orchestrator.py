import asyncio
import base64
import logging
import re
import time
from copy import deepcopy
from datetime import UTC, datetime

import httpx
from jsonschema import Draft202012Validator
from sqlalchemy import select

from .agent_runtime import (
    ConnectionRequiredError,
    create_plan,
    critique_step,
    intent_bounded_tool_inventory,
    is_governed_derivative_step,
    materialize_action_arguments,
    prepare_execution_directive,
    prepare_final_review,
    supervise_execution,
    synthesize_result,
    verify_outcome,
)
from .agent_telemetry import trace_run
from .approval_readiness import self_address_recipient, unfinished_action_content
from .approval_review import build_review_contract
from .autonomous_delivery import (
    RECONCILIABLE_WRITES,
    attempts_for_current_cycle,
    autonomously_recover_run,
    mark_autonomous_handoff,
    mark_recovery_checkpoint_succeeded,
)
from .config import get_settings
from .db import SessionLocal, engine, set_tenant_context
from .execution_lock import execution_lock
from .managed_connectors import managed_connection_reference, managed_connector_client
from .models import (
    Approval,
    ApprovalSnapshot,
    Artifact,
    AuditEvent,
    BrokerCapabilityPack,
    CapabilityManifest,
    ConnectionRequirement,
    DeadLetterEntry,
    ManagedConnectorCatalog,
    ManagedConnectorRelease,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    ToolKind,
    ToolTrustState,
    WorkflowRun,
)
from .native_connectors import (
    NativeConnectorError,
    coerce_module_arguments,
    current_capability_manifest,
    native_manifest,
    native_operations,
    normalize_planned_module_arguments,
    planning_catalog,
)
from .outcome_runtime import check_provider_outcome
from .pilot_template import PILOT_PREFIX, PilotInputError, pilot_template
from .policy import canonical_plan_hash, operation_scope, runtime_policy_check
from .providers import (
    ProviderExecutor,
    idempotency_key,
    refresh_oauth_credentials,
    verify_oauth_credentials,
)
from .replanning import maybe_replan_run
from .result_presentation import resolve_result_presentation
from .run_supervisor import (
    recover_planning_failure,
    transition_run,
)
from .schemas import CriticDecision, OutcomeVerification, PlanStep, WorkflowPlan
from .security import CredentialVault
from .universal_connectors import (
    ConnectorError,
    capability_for,
    discover_provider,
)
from .universal_connectors import (
    allowed_operations as discovered_operations,
)
from .workflow_context import (
    WorkflowContextError,
    canonical_action_arguments,
    evaluate_condition,
    referenced_paths,
    requires_content_composition,
    resolve_value,
    step_context_value,
)

logger = logging.getLogger(__name__)

_TEXT_DOCUMENT_TYPES = {
    "application/csv",
    "application/json",
    "application/ld+json",
    "application/xml",
}


def _future_group_review_arguments(
    operation: str,
    arguments: dict,
    context: dict,
) -> dict | None:
    """Prepare future delivery values without inventing provider outputs."""
    if operation != "gmail.send":
        return None
    prepared: dict = {}
    try:
        for key, value in arguments.items():
            if key != "attachments":
                prepared[key] = resolve_value(value, context)
                continue
            if not isinstance(value, list):
                return None
            attachments = []
            for item in value:
                if not isinstance(item, dict):
                    return None
                filename = resolve_value(item.get("filename"), context)
                url = item.get("url")
                if not isinstance(filename, str) or not isinstance(url, str):
                    return None
                # The URL remains a typed workflow reference at review time and
                # is resolved only after the approved Canva design is exported.
                attachments.append({**item, "filename": filename, "url": url})
            prepared[key] = attachments
    except WorkflowContextError:
        return None
    return prepared


def _planning_prompt_with_documents(prompt: str, inputs: dict | None) -> str:
    """Add bounded uploaded text to the model call without exposing data URLs."""
    documents = (inputs or {}).get("attached_documents", (inputs or {}).get("documents"))
    if not isinstance(documents, list) or not documents:
        return prompt
    sections: list[str] = []
    remaining = 40_000
    for document in documents[:8]:
        if not isinstance(document, dict):
            continue
        name = str(document.get("name") or "document")[:500]
        data_url = document.get("file_url")
        section = f"Attached document: {name}"
        if isinstance(data_url, str) and data_url.startswith("data:") and "," in data_url:
            metadata, encoded = data_url.split(",", 1)
            media_type = metadata[5:].split(";", 1)[0].lower()
            textual = media_type.startswith("text/") or media_type in _TEXT_DOCUMENT_TYPES
            if textual and remaining > 0:
                try:
                    raw = (
                        base64.b64decode(encoded, validate=True)
                        if ";base64" in metadata.lower()
                        else encoded.encode()
                    )
                    content = raw.decode("utf-8", errors="replace").replace("\x00", "")
                    content = content[:remaining]
                    remaining -= len(content)
                    section += f"\n{content}"
                except (ValueError, TypeError):
                    pass
        sections.append(section)
    if not sections:
        return prompt
    return f"{prompt}\n\nUser-attached workflow documents:\n" + "\n\n".join(sections)


def refresh_native_connection_contract(tool: ToolConnection) -> list[str]:
    """Keep persisted native allow-lists aligned with the deployed connector.

    Native capability contracts are application code, while the database row is a
    cached snapshot created at connection time. Refreshing that snapshot prevents a
    newly deployed safe capability from forcing the user through an unrelated OAuth
    loop. Provider credentials and approval policy remain independently enforced.
    """
    config = getattr(tool, "config", None) or {}
    if config.get("managed_by") == "pipedream" or config.get("connector_release_id"):
        return list(tool.allowed_operations or [])
    try:
        operations = native_operations(tool.slug)
    except NativeConnectorError:
        return list(tool.allowed_operations or [])
    tool.allowed_operations = operations
    return operations


async def refresh_browser_connection_contract(
    tool: ToolConnection,
    manifest: CapabilityManifest | None,
) -> list[str]:
    """Refresh a browser connector's discovered schema before planning.

    Browser apps can add fields and batch capabilities without changing the user's
    connection identity. Discovery is read-only and credential-isolated. A temporary
    discovery failure preserves the last verified contract so planning can still use
    known-good capabilities; it never disables the account or starts a login loop.
    """

    if (
        tool.kind != ToolKind.browser
        or manifest is None
        or not tool.base_url
        or not tool.encrypted_credentials
    ):
        return list(tool.allowed_operations or [])
    try:
        credentials = CredentialVault().decrypt(tool.encrypted_credentials)
        refreshed = await discover_provider(
            tool.kind.value,
            str(tool.base_url),
            credentials,
            tool.config or {},
        )
    except (ConnectorError, httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "Browser capability refresh deferred tool_id=%s error_type=%s",
            tool.id,
            type(exc).__name__,
        )
        return list(tool.allowed_operations or [])
    manifest.manifest = refreshed
    manifest.status = "verified"
    manifest.verification = {
        **(manifest.verification or {}),
        "ok": True,
        "source": "planning_discovery_refresh",
    }
    manifest.verified_at = datetime.now(UTC)
    tool.allowed_operations = discovered_operations(refreshed)
    return list(tool.allowed_operations)


def _failure_impacts_trust(exc: Exception) -> bool:
    """Only provider availability failures should affect connector reliability."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
        return False
    return isinstance(exc, (asyncio.TimeoutError, httpx.HTTPError))


def _provider_rejection_detail(exc: Exception) -> str | None:
    """Extract bounded repair evidence from a definitive provider rejection."""
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code not in {
        400,
        404,
        422,
    }:
        return None
    try:
        payload = exc.response.json()
    except ValueError:
        payload = None
    values: list[str] = [f"status={exc.response.status_code}"]
    if isinstance(payload, dict):
        code = payload.get("code")
        if isinstance(code, str) and code:
            values.append(f"code={code}")
        for key in ("message", "error", "errorMessages", "errors", "detail"):
            value = payload.get(key)
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                values.extend(str(item) for item in value if isinstance(item, (str, int, float)))
            elif isinstance(value, dict):
                values.extend(
                    f"{name}: {item}"
                    for name, item in value.items()
                    if isinstance(item, (str, int, float))
                )
    detail = "; ".join(values).strip()
    return re.sub(
        r"(?i)(token|secret|password|authorization|api[-_ ]?key)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        detail,
    )[:1200]


def _friendly_execution_error(error: str | None) -> str:
    detail = (error or "").lower()
    if "[execution_agent_escalated]" in detail:
        return "The Execution Agent paused this step for review. Your completed work is preserved."
    if any(
        marker in detail
        for marker in (
            "input budget",
            "evidence budget",
            "evidence processing budget",
            "context_length_exceeded",
        )
    ):
        return "AURA could not prepare all the source content within this run’s processing limit."
    if any(
        marker in detail
        for marker in (
            "authorization_required",
            "unauthorized",
            "forbidden",
            "sign in",
            "token",
            "credential",
            "connection needs",
            "cannot access the configured original",
        )
    ):
        return "This app connection needs your attention before AURA can continue."
    return "AURA couldn't complete this step safely after automatic recovery. Try again or adjust the workflow."


def _has_empty_collection(result: object) -> bool:
    """Recognize successful search/list responses that found no matching items."""
    if not isinstance(result, dict):
        return False
    return any(
        key in result and isinstance(result[key], list) and not result[key]
        for key in ("results", "items", "records", "candidates", "data")
    )


def _provider_result_is_malformed(result: object) -> bool:
    """Reject transport-success responses that cannot satisfy any action contract."""
    return not isinstance(result, dict) or not result


def _required_read_arguments(manifest: dict, operation: str, arguments: dict) -> dict | None:
    """Create a safe broad-read fallback while preserving all required inputs."""
    capability = next(
        (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
        None,
    )
    if not capability or operation_scope(operation) != "read":
        return None
    schema = capability.get("input_schema", {})
    required = set(schema.get("required", [])) | {
        key
        for key, value in schema.get("properties", {}).items()
        if value.get("x-preserve-on-recovery")
    }
    reduced = {key: value for key, value in arguments.items() if key in required}
    return reduced if reduced != arguments else None


def _accept_successful_read_after_critic(operation: str, criticism: object) -> bool:
    """Keep a provider-confirmed read when the model asks for a semantic retry."""
    policy_notes = getattr(criticism, "policy_violations", []) or []
    semantic_only_policy_notes = all(
        "expected_output" in str(note).lower() and "incomplete" in str(note).lower()
        for note in policy_notes
    )
    return bool(
        operation_scope(operation) == "read"
        and getattr(criticism, "action", None) == "retry"
        and semantic_only_policy_notes
    )


def _current_capability_manifest(slug: str, stored: dict | None) -> dict:
    """Prefer deployed built-in contracts over stale workspace snapshots."""
    return current_capability_manifest(slug, stored)


def _operation_is_consequential(
    operation: str,
    capability: dict | None,
    *,
    planned_consequential: bool = False,
) -> bool:
    """Classify side effects from the verified contract, with a legacy fallback.

    Operation names remain a conservative fallback for old manifests. Once a
    capability declares its permission scope, that contract is authoritative so
    unfamiliar write verbs cannot receive read-style retries.
    """
    declared_scope = capability.get("permission_scope") if capability else None
    contract_consequential = (
        declared_scope != "read"
        if declared_scope in {"read", "write", "destructive"}
        else operation_scope(operation) != "read"
    )
    return bool(planned_consequential or contract_consequential)


def _approved_action_matches(
    step: RunStep, approval: Approval | None, tool_slug: str, operation: str, arguments: dict
) -> bool:
    """Only the provider action shown in the final review may be dispatched."""
    return bool(
        approval
        and approval.status == "approved"
        and approval.preview.get("status") == "ready"
        and approval.preview.get("operation") == operation == step.operation
        and approval.preview.get("tool_slug", step.tool_slug) == tool_slug == step.tool_slug
        and approval.preview.get("arguments") == arguments
    )


def _prepare_provider_arguments(
    manifest: dict,
    operation: str,
    arguments: dict,
) -> tuple[dict, dict]:
    """Coerce and fully validate one released capability before dispatch."""
    capability = capability_for(manifest, operation)
    prepared = coerce_module_arguments(manifest, operation, arguments)
    failures = list(
        Draft202012Validator(capability.get("input_schema") or {}).iter_errors(
            prepared
        )
    )
    if failures:
        raise ValueError("Connector input failed its released schema")
    return prepared, capability


def _bounded_read_trust_score(
    operation: str,
    trust_score: float,
    execution_floor: float,
    recovery_count: int,
) -> tuple[float, bool]:
    """Allow at most three approved read attempts while connector trust recovers."""
    allowed = (
        operation_scope(operation) == "read"
        and trust_score < execution_floor
        and recovery_count < 3
    )
    return (execution_floor, True) if allowed else (trust_score, False)


def _has_confirmed_consequential_result(step: RunStep) -> bool:
    """Return true when replaying a failed write could duplicate external work."""
    return bool(
        (step.consequential or operation_scope(step.operation) != "read")
        and isinstance(step.output, dict)
        and step.output.get("provider_result") is not None
    )


async def audit(
    session,
    workspace_id: str,
    event_type: str,
    payload: dict,
    run_id: str | None = None,
    actor: str = "system",
) -> None:
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            run_id=run_id,
            actor=actor,
            event_type=event_type,
            payload=payload,
        )
    )


async def ensure_aura_intelligence(session, workspace_id: str) -> ToolConnection:
    """Provision AURA's connection-free public-data runtime for every workspace."""
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == workspace_id,
            ToolConnection.slug == "aura",
        )
    )
    operations = native_operations("aura")
    if not tool:
        tool = ToolConnection(
            workspace_id=workspace_id,
            slug="aura",
            display_name="AURA Intelligence",
            kind=ToolKind.api_key,
            encrypted_credentials=CredentialVault().encrypt({}),
            config={"managed_by": "aura"},
            allowed_operations=operations,
            enabled=True,
        )
        session.add(tool)
        await session.flush()
    else:
        tool.display_name = "AURA Intelligence"
        tool.config = {**(tool.config or {}), "managed_by": "aura"}
        tool.allowed_operations = operations
        tool.enabled = True

    manifest = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if not manifest:
        manifest = CapabilityManifest(
            workspace_id=workspace_id,
            tool_id=tool.id,
            provider_type="api_key",
        )
        session.add(manifest)
    manifest.status = "verified"
    manifest.manifest = native_manifest("aura")
    manifest.verification = {"ok": True, "source": "aura_runtime"}
    manifest.verified_at = datetime.now(UTC)
    await session.flush()
    return tool


def _normalize_planned_steps(plan, manifests_by_slug: dict[str, dict]) -> None:
    for planned_step in plan.steps:
        manifest = _current_capability_manifest(
            planned_step.tool_slug,
            manifests_by_slug.get(planned_step.tool_slug),
        )
        if not manifest:
            continue
        capability = next(
            (
                item
                for item in manifest.get("capabilities", [])
                if item.get("name") == planned_step.operation
            ),
            None,
        )
        if (
            capability
            and (capability.get("requires_approval") or capability.get("permission_scope") in {"write", "destructive"})
            and not is_governed_derivative_step(plan, planned_step)
        ):
            # Approval declarations in verified connector contracts outrank an
            # optimistic planner classification, including external agents.
            planned_step.consequential = True
        if capability and planned_step.required_evidence:
            from .operation_contracts import canonicalize_requested_evidence, enrich_operation

            provides = enrich_operation(capability)["reliability"]["provides"]
            planned_step.required_evidence = canonicalize_requested_evidence(
                planned_step.operation, planned_step.required_evidence, provides
            )
        planned_step.arguments = normalize_planned_module_arguments(
            manifest, planned_step.operation, planned_step.arguments
        )
        if planned_step.reduced_scope_arguments is None:
            planned_step.reduced_scope_arguments = _required_read_arguments(
                manifest, planned_step.operation, planned_step.arguments
            )
    from .operation_contracts import normalize_bound_email_inputs, normalize_planner_evidence_roles

    normalize_bound_email_inputs(plan)
    normalize_planner_evidence_roles(plan, manifests_by_slug)
    # A narrative draft may have no {{step}} reference even though it promises
    # to summarize earlier reads. Keep those reads in its executable dependency
    # graph so the argument resolver sees their accepted results before review.
    for index, planned_step in enumerate(plan.steps):
        content_arguments = {**planned_step.arguments, "to": "me"}
        if not unfinished_action_content(planned_step.operation, content_arguments):
            continue
        for source in plan.steps[:index]:
            if operation_scope(source.operation) == "read" and source.key not in planned_step.depends_on:
                planned_step.depends_on.append(source.key)


async def _reviewable_gmail_recipient(
    tool: ToolConnection,
    manifest_record: CapabilityManifest | None,
    arguments: dict,
) -> dict:
    """Show the connected address, not an unresolved self alias, at approval."""
    current = str(arguments.get("to") or "").strip()
    if not self_address_recipient("gmail.send", arguments) and not unfinished_action_content(
        "gmail.send", {"to": current, "body": "Approved message text"}
    ):
        return arguments
    verified = (manifest_record.verification or {}) if manifest_record else {}
    identity = verified.get("identity") or {}
    email = str(identity.get("email") or "").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        if tool.slug != "google" or (tool.config or {}).get("managed_by") == "pipedream":
            raise NativeConnectorError("Connected Gmail recipient cannot be verified for review")
        config = tool.config or {}
        vault = CredentialVault()
        if config.get("managed_by") == "nango":
            credentials = await managed_connector_client().get_credentials(
                managed_connection_reference(tool) or config["connection_id"],
                config["integration_id"],
            )
        else:
            credentials = vault.decrypt(tool.encrypted_credentials)
            if tool.kind == ToolKind.oauth:
                credentials, changed = await refresh_oauth_credentials(
                    get_settings(), tool.slug, credentials, config
                )
                if changed:
                    tool.encrypted_credentials = vault.encrypt(credentials)
        email = await ProviderExecutor(credentials, timeout_seconds=12).gmail_connected_address()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise NativeConnectorError("Connected Gmail recipient cannot be verified for review")
    return {**arguments, "to": email}


def _include_requested_story_in_email(plan, prompt: str) -> None:
    """Keep a requested story and PDF visible in the exact approved email."""
    if not re.search(r"\b(?:email|send)\b[^.]{0,120}\bstory\s+and\s+(?:the\s+)?pdf\b", prompt, re.IGNORECASE):
        return
    doc = next((step for step in plan.steps if step.operation == "docs.create"), None)
    mail = next((step for step in plan.steps if step.operation == "gmail.send"), None)
    if not doc or not mail:
        return
    attachments = mail.arguments.get("attachments") or []
    if not any(
        isinstance(item, dict) and str(item.get("filename", "")).lower().endswith(".pdf")
        for item in attachments
    ):
        raise NativeConnectorError("Emailing the requested story and PDF requires a PDF attachment")
    story = doc.arguments.get("body")
    if not isinstance(story, str) or not story.strip() or "{{" in story:
        raise NativeConnectorError("The story must be grounded in the reviewed Google Doc before email delivery")
    if re.search(
        r"\b(?:to be (?:drafted|written|filled)|placeholder|tbd|insert (?:the )?(?:story|text)|"
        r"write (?:the )?story (?:here|later)|before execution)\b",
        story,
        re.IGNORECASE,
    ) or (story.strip().startswith("[") and story.strip().endswith("]")):
        raise NativeConnectorError(
            "Google Docs must contain the finished original story, not a placeholder; "
            "write its full text in docs.create body before emailing it"
        )
    body = str(mail.arguments.get("body") or "")
    if story.strip() not in body:
        title = str(doc.arguments.get("title") or "the requested story")
        mail.arguments["body"] = (
            f"Here is {title}. The illustrated Canva PDF is attached.\n\n{story.strip()}"
        )


def _ensure_document_body_readback(plan, manifests_by_slug: dict[str, dict]) -> None:
    """Use a verified Docs read for body evidence that create cannot return."""
    from .schemas import PlanStep

    for doc in tuple(plan.steps):
        if doc.operation != "docs.create" or "document_body" not in doc.required_evidence:
            continue
        capabilities = manifests_by_slug.get(doc.tool_slug, {}).get("capabilities", [])
        if not any(item.get("name") == "docs.get" for item in capabilities):
            raise NativeConnectorError("Document body evidence requires a verified docs.get readback")
        readback = next(
            (step for step in plan.steps if step.operation == "docs.get" and doc.key in step.depends_on),
            None,
        )
        if readback is None:
            if len(plan.steps) >= 20:
                raise NativeConnectorError("The document readback exceeds the workflow step limit")
            key = f"{doc.key[:100]}_readback"
            if any(step.key == key for step in plan.steps):
                raise NativeConnectorError("The document readback key is already in use")
            readback = PlanStep(
                key=key, agent="Google Docs Readback", tool_slug=doc.tool_slug,
                operation="docs.get", arguments={"document_id": f"{{{{steps.{doc.key}.id}}}}"},
                reason="Read back the exact created Google Doc before using its story",
                expected_output="Verified title and full document body",
                depends_on=[doc.key], required_evidence=["document_body"],
            )
            plan.steps.insert(plan.steps.index(doc) + 1, readback)
        elif "document_body" not in readback.required_evidence:
            readback.required_evidence.append("document_body")
        doc.required_evidence = list(dict.fromkeys(
            ["write_receipt", *(tag for tag in doc.required_evidence if tag != "document_body")]
        ))
        for step in plan.steps[plan.steps.index(readback) + 1:]:
            if step.operation in {"canva.presentation.create", "gmail.send"} and readback.key not in step.depends_on:
                step.depends_on.append(readback.key)


def _normalize_illustrated_canva_slides(plan, prompt: str) -> None:
    """Move explicit illustration labels into the scene field that renders art."""
    if not re.search(
        r"\billustrat(?:ed|ions?)\b.{0,40}\bcanva\b|\bcanva\b.{0,40}\billustrat(?:ed|ions?)\b",
        prompt,
        re.IGNORECASE | re.DOTALL,
    ):
        return
    for step in plan.steps:
        if step.operation != "canva.presentation.create" or step.arguments.get("layout") != "slides":
            continue
        phases = step.arguments.get("phases") or []
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            items = phase.get("items") or []
            if not phase.get("scene") and isinstance(items, list):
                for item in items:
                    if not isinstance(item, str):
                        continue
                    match = re.search(
                        r"\billustration\s+scene\s*:\s*(rain_window|paper_boat|lantern)\b",
                        item,
                        re.IGNORECASE,
                    )
                    if match:
                        phase["scene"] = match.group(1).lower()
                        phase["items"] = [
                            cleaned for value in items
                            if (cleaned := re.sub(
                                r"\billustration\s+scene\s*:\s*(?:rain_window|paper_boat|lantern)\b",
                                "", value, flags=re.IGNORECASE,
                            ).strip())
                        ]
                        break
        if (
            len(phases) == 3
            and "paper boat" in prompt.casefold()
            and "lantern" in prompt.casefold()
        ):
            available = [
                scene for scene in ("rain_window", "paper_boat", "lantern")
                if scene not in {phase.get("scene") for phase in phases if isinstance(phase, dict)}
            ]
            for phase in phases:
                if not isinstance(phase, dict) or phase.get("scene"):
                    continue
                title = str(phase.get("title") or "").casefold()
                items = " ".join(str(item) for item in phase.get("items") or []).casefold()
                hints = (
                    ("paper_boat", "boat"), ("lantern", "lantern"),
                    ("rain_window", "rain"), ("rain_window", "window"),
                )
                matching = next((scene for scene, word in hints if word in title and scene in available), None)
                matching = matching or next(
                    (scene for scene, word in hints if word in items and scene in available), None
                )
                phase["scene"] = matching or available[0]
                available.remove(phase["scene"])
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            if not phase.get("scene"):
                raise NativeConnectorError(
                    "Illustrated Canva slides require a scene field on every phase: "
                    "rain_window, paper_boat, or lantern"
                )


async def _create_compiled_plan(
    prompt: str,
    inventory: list[dict],
    available_input_names: set[str],
    manifests_by_slug: dict[str, dict],
    requested_tool_names: list[str] | tuple[str, ...] | set[str] = (),
    excluded_tool_families: set[str] | frozenset[str] = frozenset(),
    supervisor_strategy: str | None = None,
    request_prompt: str | None = None,
):
    """Build a schema-valid plan, repairing internal connector mismatches silently."""
    manifests_by_slug = {
        item["slug"]: _current_capability_manifest(
            item["slug"], manifests_by_slug.get(item["slug"])
        )
        for item in inventory
    }
    if excluded_tool_families:
        from .connection_families import capability_family

        def allowed(operation: str) -> bool:
            return capability_family(operation.split(".", 1)[0]) not in excluded_tool_families

        inventory = [
            {**item, "allowed_operations": [op for op in item.get("allowed_operations", []) if allowed(op)]}
            for item in inventory
            if capability_family(item.get("slug")) not in excluded_tool_families
        ]
        included_slugs = {item["slug"] for item in inventory}
        manifests_by_slug = {
            slug: {**manifest, "capabilities": [
                module for module in manifest.get("capabilities", [])
                if allowed(module.get("name", ""))
            ]}
            for slug, manifest in manifests_by_slug.items()
            if slug in included_slugs
        }

    from .request_contracts import requested_external_operations

    objective = request_prompt or prompt
    selected_google_sources = " ".join(str(tool) for tool in requested_tool_names)
    if (
        requested_external_operations(objective) == {"gmail.send"}
        and re.search(r"\b(?:gmail|e-mails?|emails?|inbox|mailbox)\b", objective, re.IGNORECASE)
        and not re.search(
            r"\b(?:drive|docs?|documents?|sheets?|spreadsheets?|calendar|meetings?)\b",
            objective + " " + selected_google_sources,
            re.IGNORECASE,
        )
    ):
        # Google Workspace is one connector with many unrelated operations.
        # A Gmail-only delivery request should not invite the planner to read
        # Drive or substitute account identity for mailbox and send actions.
        inventory = [
            {**item, "allowed_operations": [
                operation for operation in item.get("allowed_operations", [])
                if operation.startswith("gmail.")
            ]} if item["slug"] == "google" else item
            for item in inventory
        ]

    def reject_excluded_steps(plan) -> None:
        if not excluded_tool_families:
            return
        from .connection_families import capability_family

        for planned_step in plan.steps:
            for slug, operation in (
                (planned_step.tool_slug, planned_step.operation),
                (planned_step.fallback_tool_slug, planned_step.fallback_operation),
            ):
                if (capability_family(slug) in excluded_tool_families
                    or capability_family(str(operation or "").split(".", 1)[0]) in excluded_tool_families):
                    raise NativeConnectorError("The revised plan still uses an omitted app")
    inventory = [
        {
            **item,
            "operation_contracts": [
                {
                    key: module.get(key)
                    for key in (
                        "name",
                        "description",
                        "module_type",
                        "input_schema",
                        "output_schema",
                        "permission_scope",
                        "requires_approval",
                        "capability_tags",
                        "reliability",
                    )
                }
                for module in manifests_by_slug[item["slug"]].get("capabilities", [])
                if module.get("name") in item.get("allowed_operations", [])
            ],
        }
        for item in inventory
    ]
    # Intent filtering is advisory. It cannot erase an explicitly requested
    # external action from the catalog used to check plan completeness.
    available_operations = {
        op for item in inventory for op in item.get("allowed_operations", [])
    }
    catalog_inventory = inventory
    from .workflow_templates import (
        creator_outreach_template,
        mailchimp_canva_pilot_template,
        notion_to_jira_template,
        weather_presentation_template,
    )

    # A reviewed change must be compiled from the reviewed steps. The audited
    # first-draft templates match the original request and would silently
    # discard a later instruction (for example, changing one to two slides).
    reviewed_revision = "The user reviewed the proposed workflow and requested this change:" in prompt
    audited_plan = None if reviewed_revision else (
        pilot_template(prompt, inventory)
        or mailchimp_canva_pilot_template(prompt, inventory)
        or creator_outreach_template(prompt, inventory)
        or weather_presentation_template(prompt, inventory)
        or notion_to_jira_template(prompt, inventory)
    )
    if audited_plan is not None:
        reject_excluded_steps(audited_plan)
        _normalize_planned_steps(audited_plan, manifests_by_slug)
        from .plan_preflight import preflight_plan
        from .request_contracts import validate_requested_operations

        validate_requested_operations(
            request_prompt or prompt, audited_plan, available_operations,
            catalog_inventory, manifests_by_slug,
        )
        preflight = preflight_plan(
            audited_plan, catalog_inventory, manifests_by_slug, available_input_names
        )
        if preflight.fixes:
            raise ValueError("Plan failed preflight: " + "; ".join(preflight.fixes))
        audited_plan.planning_artifacts["compiled_contracts"] = preflight.contracts
        return audited_plan
    inventory = intent_bounded_tool_inventory(prompt, inventory, requested_tool_names)
    preferred_route = {
        "repair_plan": "staged",
        "compact_replan": "compact",
    }.get(supervisor_strategy, "combined")
    from .request_contracts import requested_effects

    # Give the planner the independently checked delivery requirements on its
    # first call; discovering a missing action only after generation costs an
    # entire second model pass and can produce an apparently complete read plan.
    repair_requirements = [
        "The user requires a nonoptional " + effect["effect"]
        + " step before completion. Choose a permitted operation from: "
        + ", ".join(sorted({target["operation"] for target in effect["targets"]}))
        + ". Show its resolved arguments for approval before dispatch."
        for effect in requested_effects(
            request_prompt or prompt, catalog_inventory, manifests_by_slug,
        )
    ]
    # Connector-contract validation receives one model repair. Safe generated
    # prose is normalized deterministically before this boundary, so repeating
    # the same repair cannot improve a persistent schema mismatch.
    for attempt in range(2):
        plan = await create_plan(
            prompt,
            inventory,
            available_input_names,
            planner_repair_requirements=list(repair_requirements),
            preferred_route=preferred_route,
        )
        try:
            reject_excluded_steps(plan)
            requested = prompt.casefold()
            # A public forecast has a dedicated source. Never accept a plan
            # which substitutes a private document search for weather data.
            if (
                ("forecast" in requested or "прогноз" in requested)
                and any("weather.forecast" in item.get("allowed_operations", []) for item in inventory)
                and not any(step.operation == "weather.forecast" for step in plan.steps)
            ):
                raise NativeConnectorError(
                    "Fetch the public forecast with AURA weather.forecast before creating downstream content"
                )
            if ("roadmap" in requested or "timeline" in requested) and any(
                s.operation == "canva.design.create" for s in plan.steps
            ):
                raise NativeConnectorError(
                    "A populated roadmap requires canva.presentation.create; blank design creation cannot satisfy this request"
                )
            if "attach" in requested and any(
                s.operation == "gmail.send" and not s.arguments.get("attachments")
                for s in plan.steps
            ):
                raise NativeConnectorError(
                    "The requested file attachment must be present in gmail.send attachments, not substituted with a body link"
                )
            _normalize_planned_steps(plan, manifests_by_slug)
            _ensure_document_body_readback(plan, manifests_by_slug)
            _include_requested_story_in_email(plan, prompt)
            _normalize_illustrated_canva_slides(plan, prompt)
            from .plan_preflight import preflight_plan
            from .request_contracts import validate_requested_operations

            validate_requested_operations(
                request_prompt or prompt, plan, available_operations,
                catalog_inventory, manifests_by_slug,
            )
            preflight = preflight_plan(
                plan, catalog_inventory, manifests_by_slug, available_input_names
            )
            if preflight.fixes:
                raise ValueError("Plan failed preflight: " + "; ".join(preflight.fixes))
            plan.planning_artifacts["compiled_contracts"] = preflight.contracts
            if supervisor_strategy in {"repair_plan", "compact_replan"}:
                plan.planning_artifacts["supervisor_recovery_strategy"] = supervisor_strategy
            return plan
        except (NativeConnectorError, ValueError) as exc:
            if attempt == 1:
                raise
            repair_requirements.append(str(exc))
            reason = str(exc)
            failure_category = (
                "connector_input" if isinstance(exc, NativeConnectorError)
                else "evidence_contract" if reason.startswith("Plan contract validation failed")
                and "cannot supply" in reason
                else "output_reference" if reason.startswith("Plan contract validation failed")
                else "missing_requested_action" if reason.startswith("Requested external action")
                else "plan_validation"
            )
            logger.warning(
                "Repairing plan connector contract attempt=%s error_type=%s failure_category=%s",
                attempt + 2,
                type(exc).__name__,
                failure_category,
            )
    raise RuntimeError("Plan connector-contract recovery exhausted")


def planning_error_message(exc: Exception) -> str:
    """Return a user-facing planning failure without leaking provider payloads."""
    # Recovery wrappers intentionally replace raw provider messages. Walk the
    # exception chain so operational categories such as quota exhaustion and
    # rate limiting are not lost when combined and staged planning both fail.
    chain: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(str(current))
        current = current.__cause__ or current.__context__
    lowered = " ".join(chain).lower()
    if (
        "insufficient_quota" in lowered
        or "credit_balance_exhausted" in lowered
        or "no credits remaining" in lowered
    ):
        from .run_supervisor import PLANNING_QUOTA_MESSAGE

        return PLANNING_QUOTA_MESSAGE
    if "rate limit" in lowered or "error code: 429" in lowered:
        return "AURA's AI planning service is temporarily busy. Please try again shortly."
    if "invalid json" in lowered:
        return "AURA couldn't format the plan correctly. Please try again."
    return "AURA couldn't build the plan right now. Please try again."


_PROMPT_CAPABILITY_ALIASES = {
    "meta-ads": {"meta ads", "facebook ads", "meta advertising"},
}


def _connection_family(item: dict) -> str:
    from .connection_families import capability_family

    slug_family = capability_family(item.get("slug"))
    if slug_family in {"calendar", "docs", "drive", "sheets", "gmail"}:
        return slug_family
    value = str(
        item.get("canonical_provider")
        or item.get("provider")
        or item.get("slug")
        or ""
    ).strip().casefold()
    return capability_family(value)


def _connection_capability_families(item: dict) -> set[str]:
    """Return every app family a connection can actually satisfy.

    Some providers intentionally expose several user-facing apps through one
    verified account. Google Workspace, for example, is stored as ``google``
    while its allow-list contains ``gmail.*``, ``calendar.*``, ``drive.*`` and
    ``sheets.*`` operations. Treating only the storage slug as connected made a
    healthy Google account look disconnected when a plan named Gmail directly.
    """
    families = {_connection_family(item)}
    for operation in item.get("allowed_operations") or []:
        namespace = str(operation or "").split(".", 1)[0]
        family = _connection_family({"canonical_provider": namespace})
        if family:
            families.add(family)
    families.discard("")
    return families


def _connected_capability_families(inventory: list[dict]) -> set[str]:
    return {
        family
        for item in inventory
        if item.get("connected", False)
        for family in _connection_capability_families(item)
    }


def explicit_disconnected_capabilities(prompt: str, inventory: list[dict]) -> list[str]:
    """Find every explicitly named, disconnected provider account family."""
    text = " " + re.sub(r"[^a-z0-9]+", " ", prompt.casefold()).strip() + " "
    connected_families = _connected_capability_families(inventory)
    missing: list[str] = []
    seen_families: set[str] = set()
    for item in inventory:
        family = _connection_family(item)
        if (
            item.get("connected", False)
            or not family
            or family in connected_families
            or family in seen_families
        ):
            continue
        slug = str(item.get("slug") or "").strip().casefold()
        name = str(item.get("name") or "").strip().casefold()
        aliases = {
            re.sub(r"[^a-z0-9]+", " ", value).strip()
            for value in {
                slug,
                name,
                family,
                *_PROMPT_CAPABILITY_ALIASES.get(slug, set()),
            }
            if value
        }
        if any(alias and f" {alias} " in text for alias in aliases):
            missing.append(family)
            seen_families.add(family)
    return missing


def actionable_connection_capabilities(
    requested: list[str], inventory: list[dict]
) -> list[str]:
    """Return only exact, backend-owned connectors that a user can authorize.

    Model-authored missing-capability prose is not a connection route. If it
    cannot be matched to a disconnected catalog entry, recovery stays backstage
    instead of asking the user for API, MCP, or custom OAuth configuration.
    """
    connected_families = _connected_capability_families(inventory)
    aliases: dict[str, str] = {}
    for item in inventory:
        family = _connection_family(item)
        if item.get("connected", False) or not family or family in connected_families:
            continue
        slug = str(item.get("slug") or "").strip().casefold()
        name = str(item.get("name") or "").strip().casefold()
        if slug:
            aliases[re.sub(r"[^a-z0-9]+", "-", slug).strip("-")] = family
        if name:
            aliases[re.sub(r"[^a-z0-9]+", "-", name).strip("-")] = family
        aliases[family] = family

    actionable: list[str] = []
    for value in requested:
        normalized = re.sub(
            r"[^a-z0-9]+", "-", str(value or "").strip().casefold()
        ).strip("-")
        slug = aliases.get(normalized)
        if slug and slug not in actionable:
            actionable.append(slug)
    return actionable


def complete_connection_requirements(
    prompt: str,
    planner_reported: list[str],
    inventory: list[dict],
) -> list[str]:
    """Combine deterministic prompt providers with the planner's exact matches."""
    explicit = explicit_disconnected_capabilities(prompt, inventory)
    planned = actionable_connection_capabilities(planner_reported, inventory)
    return list(dict.fromkeys([*explicit, *planned]))


def _required_permissions(capability: str, inventory: list[dict]) -> list[str]:
    return next(
        (
            list(item.get("allowed_operations") or [])
            for item in inventory
            if _connection_family(item) == capability
        ),
        [],
    )


_PROVIDER_CANDIDATE_STOP_WORDS = {
    "add",
    "analyze",
    "build",
    "compare",
    "connect",
    "create",
    "delete",
    "download",
    "draft",
    "find",
    "format",
    "get",
    "list",
    "make",
    "monitor",
    "post",
    "prepare",
    "publish",
    "read",
    "remove",
    "review",
    "schedule",
    "search",
    "send",
    "share",
    "show",
    "summarize",
    "sync",
    "turn",
    "update",
    "upload",
    "use",
    "write",
}


def _capitalized_provider_candidates(prompt: str) -> list[str]:
    """Extract bounded app-name candidates without treating arbitrary prose as apps."""
    candidates = re.findall(
        r"(?<![A-Za-z0-9])"
        r"[A-Z][A-Za-z0-9._+-]*"
        r"(?:[\s&]+[A-Z][A-Za-z0-9._+-]*){0,2}",
        prompt,
    )
    return list(
        dict.fromkeys(
            candidate.strip().rstrip("._+-")
            for candidate in candidates
            if candidate.strip().rstrip("._+-").casefold()
            not in _PROVIDER_CANDIDATE_STOP_WORDS
        )
    )[:8]


def _catalog_entry_inventory(item: dict, connected_families: set[str]) -> dict:
    provider = str(item.get("provider") or item.get("slug") or "").strip()
    canonical = str(item.get("canonical_provider") or provider).strip()
    family = _connection_family({"slug": provider, "canonical_provider": canonical})
    return {
        "slug": provider,
        "name": str(item.get("display_name") or item.get("name") or provider),
        "canonical_provider": canonical,
        "connected": family in connected_families,
        "allowed_operations": list(item.get("capabilities") or []),
    }


async def connection_requirement_inventory(
    session,
    prompt: str,
    execution_inventory: list[dict],
    requested_tool_names: list[str] | tuple[str, ...] | set[str] = (),
) -> list[dict]:
    """Extend certified actions with connectable apps from the canonical marketplace."""
    combined = list(execution_inventory)
    connected_families = _connected_capability_families(execution_inventory)
    known_families = {
        _connection_family(item) for item in combined if _connection_family(item)
    }

    snapshots = list((await session.scalars(select(ManagedConnectorCatalog))).all())
    for snapshot in snapshots:
        for item in snapshot.providers or []:
            if not item.get("connectable"):
                continue
            catalog_item = _catalog_entry_inventory(item, connected_families)
            family = _connection_family(catalog_item)
            if family and family not in known_families:
                combined.append(catalog_item)
                known_families.add(family)

    candidates = (
        [str(value) for value in requested_tool_names if value]
        if requested_tool_names
        else _capitalized_provider_candidates(prompt)
    )
    unresolved = [
        candidate
        for candidate in candidates
        if _connection_family({"canonical_provider": candidate}) not in known_families
    ]
    if unresolved:
        from .pipedream_connect import marketplace_entry, pipedream_client

        client = pipedream_client()
        if client.configured:
            for candidate in unresolved:
                try:
                    apps = await client.list_apps(candidate, limit=10)
                except Exception as exc:  # noqa: BLE001 - catalog lookup is best effort
                    logger.warning(
                        "Connector requirement catalog lookup deferred candidate=%s error_type=%s",
                        candidate,
                        type(exc).__name__,
                    )
                    continue
                candidate_family = _connection_family(
                    {"canonical_provider": candidate}
                )
                for app in apps:
                    entry = marketplace_entry(app, connectable=True)
                    if not entry.get("connectable"):
                        continue
                    aliases = {
                        _connection_family({"canonical_provider": value})
                        for value in {
                            entry.get("provider"),
                            entry.get("canonical_provider"),
                            entry.get("display_name"),
                            *(entry.get("aliases") or []),
                        }
                        if value
                    }
                    if candidate_family not in aliases:
                        continue
                    catalog_item = _catalog_entry_inventory(entry, connected_families)
                    family = _connection_family(catalog_item)
                    if family and family not in known_families:
                        combined.append(catalog_item)
                        known_families.add(family)
                    break
    return combined


async def _persist_plan_draft(session, run: WorkflowRun, plan) -> tuple[str, str]:
    """Persist a reviewable plan before connection or approval gates."""
    run.plan = plan.model_dump(mode="json")
    plan_hash = canonical_plan_hash(run.plan)
    existing = await session.scalar(
        select(PlanVersion.id).where(
            PlanVersion.run_id == run.id,
            PlanVersion.version == 1,
        )
    )
    if existing:
        return plan_hash, existing
    logger.info(
        "Workflow plan ready run_id=%s graph=%s planner_recovery=%s timings_ms=%s",
        run.id,
        [
            {
                "key": item.key,
                "depends_on": item.depends_on,
                "condition": item.condition is not None,
                "optional": item.optional,
                "operation": item.operation,
            }
            for item in plan.steps
        ],
        plan.planning_artifacts.get("planner_recovery_mode"),
        plan.planning_artifacts.get("timings_ms"),
    )
    plan_version = PlanVersion(
        workspace_id=run.workspace_id,
        run_id=run.id,
        version=1,
        status="draft",
        plan=run.plan,
        plan_hash=plan_hash,
        created_by="aura-plan-builder",
    )
    session.add(plan_version)
    await session.flush()
    for position, item in enumerate(plan.steps):
        step = RunStep(
            run_id=run.id,
            position=position,
            step_key=item.key,
            agent=item.agent,
            tool_slug=item.tool_slug,
            operation=item.operation,
            arguments=item.arguments,
            depends_on=item.depends_on,
            dependency_mode=item.dependency_mode,
            condition=item.condition.model_dump(mode="json") if item.condition else None,
            output_variables=item.output_variables,
            consequential=item.consequential,
            idempotency_key=idempotency_key(
                run.id, position, item.operation, item.arguments
            ),
        )
        session.add(step)
        await session.flush()
        if item.consequential:
            approval = Approval(
                run_id=run.id,
                step_id=step.id,
                preview={"status": "preparing"},
            )
            session.add(approval)
            await session.flush()
            step.approval_id = approval.id
            step.status = StepStatus.awaiting_approval
    return plan_hash, plan_version.id


@trace_run
async def plan_run(run_id: str, workspace_id: str) -> None:
    async with execution_lock(engine, workspace_id, run_id) as acquired:
        if acquired:
            try:
                await _plan_run(run_id, workspace_id)
            except Exception as exc:
                # Inventory refresh, credential control-plane and database-adjacent
                # preparation happen before the model planner.  They still belong
                # to the same durable supervisor and must not fall through to a
                # browser Retry button after Celery exhausts an in-memory retry.
                logger.exception(
                    "Unhandled planning delivery failure run_id=%s error_type=%s",
                    run_id,
                    type(exc).__name__,
                )
                async with SessionLocal() as session:
                    await set_tenant_context(session, workspace_id)
                    run = await session.get(WorkflowRun, run_id)
                    if (
                        run
                        and run.workspace_id == workspace_id
                        and run.status in {RunStatus.queued, RunStatus.planning}
                    ):
                        await recover_planning_failure(
                            session,
                            run,
                            exc,
                            max_attempts=get_settings().max_planning_recovery_rounds,
                            base_delay_seconds=get_settings().autonomous_recovery_base_delay_seconds,
                            max_delay_seconds=get_settings().autonomous_recovery_max_delay_seconds,
                        )
                        await session.commit()


async def _plan_run(run_id: str, workspace_id: str) -> None:
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if (
            not run
            or run.workspace_id != workspace_id
            or run.status not in {RunStatus.queued, RunStatus.planning}
        ):
            return
        transition_run(
            run,
            RunStatus.planning,
            reason="planning_delivery_started",
            actor="plan-builder",
            phase="planning",
            supervisor_status="active",
            dispatch=None,
            allow_same=True,
        )
        await ensure_aura_intelligence(session, run.workspace_id)
        tools = (
            await session.scalars(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == run.workspace_id,
                    ToolConnection.enabled.is_(True),
                )
            )
        ).all()
        manifests = (
            await session.scalars(
                select(CapabilityManifest).where(
                    CapabilityManifest.tool_id.in_([tool.id for tool in tools]),
                    CapabilityManifest.status == "verified",
                )
            )
        ).all()
        manifests_by_tool = {manifest.tool_id: manifest for manifest in manifests}
        from .connection_permissions import refresh_granted_readbacks

        for tool in tools:
            refresh_native_connection_contract(tool)
            refresh_granted_readbacks(tool)
            await refresh_browser_connection_contract(tool, manifests_by_tool.get(tool.id))
        connected_inventory = [
            {
                "slug": tool.slug,
                "name": tool.display_name,
                "canonical_provider": (tool.config or {}).get("canonical_provider")
                or (tool.config or {}).get("vendor_app")
                or tool.slug,
                "kind": tool.kind.value,
                "allowed_operations": tool.allowed_operations,
                "connected": True,
            }
            for tool in tools
            if tool.id in manifests_by_tool
        ]
        connected_slugs = {item["slug"] for item in connected_inventory}
        from .connector_engineer import dynamic_planning_catalog

        dynamic_inventory, dynamic_manifests = await dynamic_planning_catalog(
            session, connected_slugs
        )
        from .pipedream_connect import planning_catalog as pipedream_planning_catalog

        broker_inventory, broker_manifests = await pipedream_planning_catalog(
            session, connected_slugs
        )
        inventory_by_slug = {item["slug"]: item for item in planning_catalog(connected_slugs)}
        inventory_by_slug.update({item["slug"]: item for item in dynamic_inventory})
        inventory_by_slug.update({item["slug"]: item for item in broker_inventory})
        for item in connected_inventory:
            # The account's grants decide execution, not what the planner is
            # allowed to describe. Preserve the declared connector catalog so
            # missing consent becomes a precise connection request instead of
            # forcing the model to invent a substitute operation.
            declared = inventory_by_slug.get(item["slug"], {})
            inventory_by_slug[item["slug"]] = {
                **declared, **item,
                "allowed_operations": declared.get("allowed_operations")
                or item["allowed_operations"],
            }
        inventory = list(inventory_by_slug.values())
        manifests_by_slug = dict(dynamic_manifests)
        manifests_by_slug.update(broker_manifests)
        manifests_by_slug.update({
            tool.slug: manifest.manifest
            for tool in tools
            for manifest in manifests
            if manifest.tool_id == tool.id
        })
        requested_tools = [
            str(value)
            for value in (run.inputs or {}).get("requested_tools", [])
            if value
        ]
        from .connection_families import capability_family

        excluded_families = {
            capability_family(value)
            for value in (run.inputs or {}).get("excluded_tool_families", [])
            if isinstance(value, str)
        }
        requirement_inventory = (
            inventory if run.prompt.startswith(PILOT_PREFIX)
            else await connection_requirement_inventory(session, run.prompt, inventory, requested_tools)
        )
        await session.commit()

        try:
            from .plan_reuse import reuse_saved_plan
            from .request_contracts import validate_requested_operations

            plan = await reuse_saved_plan(session, run, connected_inventory, manifests_by_slug)
            if plan is not None:
                try:
                    validate_requested_operations(
                        run.prompt, plan,
                        {op for item in inventory for op in item.get("allowed_operations", [])},
                        inventory,
                        {item["slug"]: _current_capability_manifest(
                            item["slug"], manifests_by_slug.get(item["slug"])
                        ) for item in inventory},
                    )
                except ValueError:
                    plan = None  # A historical read-only draft cannot satisfy a new delivery.
            if plan is None:
                supervisor = (run.execution_context or {}).get("__aura_supervisor__") or {}
                strategy = (
                    supervisor.get("last_action")
                    if supervisor.get("phase") == "planning"
                    and supervisor.get("last_failure_category") == "malformed_plan"
                    else None
                )
                plan = await _create_compiled_plan(
                    _planning_prompt_with_documents(run.prompt, run.inputs),
                    inventory,
                    set((run.inputs or {}).keys()),
                    manifests_by_slug,
                    requested_tools,
                    excluded_families,
                    supervisor_strategy=strategy,
                    request_prompt=run.prompt,
                )
            if excluded_families:
                for planned_step in plan.steps:
                    for slug, operation in (
                        (planned_step.tool_slug, planned_step.operation),
                        (planned_step.fallback_tool_slug, planned_step.fallback_operation),
                    ):
                        if (capability_family(slug) in excluded_families
                            or capability_family(str(operation or "").split(".", 1)[0]) in excluded_families):
                            raise NativeConnectorError("The revised plan still uses an omitted app")
            from .plan_preflight import preflight_plan

            preflight = preflight_plan(
                plan, inventory, manifests_by_slug, set((run.inputs or {}).keys()),
                connected_inventory,
            )
            if preflight.fixes:
                raise ValueError("Plan failed preflight: " + "; ".join(preflight.fixes))
            plan.planning_artifacts["compiled_contracts"] = preflight.contracts
            reported_missing = list(plan.planning_artifacts.get("connection_requirements", []))
            missing = (
                reported_missing if run.prompt.startswith(PILOT_PREFIX)
                else complete_connection_requirements(run.prompt, reported_missing, requirement_inventory)
            )
            # A catalog connector may be proposed for review, but Start must
            # never be offered until every real operation and verification read
            # is authorized on the connected account.
            missing_grants = preflight.missing_grants
            missing = list(dict.fromkeys([*missing, *missing_grants]))
            missing = [item for item in missing if capability_family(item) not in excluded_families]
            if missing:
                from .connection_recovery import reuse_managed_connection
                from .semantic_memory import source_owner

                owner = await source_owner(session, workspace_id, run.id)
                reused = False
                for slug in list(missing):
                    if await reuse_managed_connection(
                        session, managed_connector_client(), slug, workspace_id, owner
                    ):
                        reused = True
                        missing.remove(slug)
                if reused:
                    # Connection recovery changes the database, not the
                    # snapshot captured before planning. Recheck actual grants
                    # before exposing Start; a reused account may lack a readback.
                    current_tools = (await session.scalars(select(ToolConnection).where(
                        ToolConnection.workspace_id == workspace_id,
                        ToolConnection.enabled.is_(True),
                    ))).all()
                    current_manifests = (await session.scalars(select(CapabilityManifest).where(
                        CapabilityManifest.tool_id.in_([tool.id for tool in current_tools]),
                        CapabilityManifest.status == "verified",
                    ))).all()
                    verified_ids = {manifest.tool_id for manifest in current_manifests}
                    from .connection_permissions import missing_plan_operations

                    missing_grants = missing_plan_operations(plan, [
                        {"slug": tool.slug, "allowed_operations": tool.allowed_operations}
                        for tool in current_tools if tool.id in verified_ids
                    ])
                    missing = list(dict.fromkeys([*missing, *missing_grants]))
            plan.planning_artifacts["connection_requirements"] = missing
            plan_hash, plan_version_id = await _persist_plan_draft(session, run, plan)
            if missing:
                for capability in missing:
                    session.add(
                        ConnectionRequirement(
                            workspace_id=workspace_id,
                            run_id=run.id,
                            capability=capability,
                            provider_hint=capability,
                            reason=(f"Authorize exact operations for {capability}"
                                    if capability in missing_grants
                                    else f"Connect {capability} so AURA can finish the saved plan"),
                            required_permissions=(sorted(missing_grants[capability])
                                                  if capability in missing_grants
                                                  else _required_permissions(capability, requirement_inventory)),
                        )
                    )
                blocker = {
                    "kind": "human_action",
                    "code": "connection_required",
                    "message": "One or more capability providers must be connected",
                    "action": "connect_account",
                    "missing_capabilities": missing,
                    "retryable": False,
                }
                transition_run(
                    run,
                    RunStatus.waiting_for_action,
                    reason="planning_catalog_connection_required",
                    actor="tool-router",
                    phase="connection",
                    supervisor_status="human_action_required",
                    error=blocker["message"],
                    result={
                        "status": "waiting_for_connection",
                        "missing_capabilities": missing,
                    },
                    blocker=blocker,
                    dispatch=None,
                )
                await audit(
                    session,
                    workspace_id,
                    "run.connection_required",
                    {
                        "missing_capabilities": missing,
                        "source": "complete_requirement_set",
                    },
                    run.id,
                    actor="tool-router",
                )
                await session.commit()
                return
            transition_run(
                run,
                RunStatus.awaiting_approval,
                reason="plan_compiled",
                actor="plan-builder",
                phase="approval",
                supervisor_status="human_action_required",
                error=None,
                result={},
                blocker={
                    "kind": "human_action",
                    "code": "plan_approval_required",
                    "message": "Review and approve the compiled workflow plan.",
                    "action": "review_plan",
                    "retryable": False,
                },
                dispatch=None,
                metadata={"plan_hash": plan_hash},
            )
            await audit(
                session,
                run.workspace_id,
                "run.planned",
                {
                    "plan": run.plan,
                    "plan_version_id": plan_version_id,
                    "plan_hash": plan_hash,
                },
                run.id,
            )
            await session.commit()
        except PilotInputError as exc:
            transition_run(
                run,
                RunStatus.waiting_for_action,
                reason="pilot_details_required",
                actor="plan-builder",
                phase="planning",
                supervisor_status="human_action_required",
                error=str(exc),
                result={"status": "pilot_details_required"},
                blocker={
                    "kind": "human_action", "code": "pilot_details_required",
                    "message": str(exc), "action": "edit_pilot_details", "retryable": False,
                },
                dispatch=None,
            )
            await session.commit()
        except ConnectionRequiredError as exc:
            missing = complete_connection_requirements(
                run.prompt, exc.missing_capabilities, requirement_inventory
            )
            missing = [item for item in missing if capability_family(item) not in excluded_families]
            if not missing:
                await audit(
                    session,
                    workspace_id,
                    "run.planning_capability_recovery_started",
                    {
                        "reported_capabilities": exc.missing_capabilities,
                        "user_configuration_requested": False,
                    },
                    run.id,
                    actor="run-supervisor",
                )
                await recover_planning_failure(
                    session,
                    run,
                    exc,
                    max_attempts=get_settings().max_planning_recovery_rounds,
                    base_delay_seconds=get_settings().autonomous_recovery_base_delay_seconds,
                    max_delay_seconds=get_settings().autonomous_recovery_max_delay_seconds,
                )
                await session.commit()
                return
            for capability in missing:
                session.add(
                    ConnectionRequirement(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        capability=capability,
                        provider_hint=None,
                        reason=f"The approved objective requires {capability}",
                        required_permissions=[],
                    )
                )
            blocker = {
                "kind": "human_action",
                "code": "connection_required",
                "message": "One or more capability providers must be connected",
                "action": "connect_account",
                "missing_capabilities": missing,
                "retryable": False,
            }
            transition_run(
                run,
                RunStatus.waiting_for_action,
                reason="planning_connection_required",
                actor="tool-router",
                phase="connection",
                supervisor_status="human_action_required",
                error=blocker["message"],
                result={
                    "status": "waiting_for_connection",
                    "missing_capabilities": missing,
                },
                blocker=blocker,
                dispatch=None,
            )
            await audit(
                session,
                workspace_id,
                "run.connection_required",
                {"missing_capabilities": missing},
                run.id,
                actor="tool-router",
            )
            await session.commit()
        except Exception as exc:
            logger.exception(
                "Workflow planning failed after automatic recovery run_id=%s error_type=%s",
                run.id,
                type(exc).__name__,
            )
            missing = explicit_disconnected_capabilities(
                run.prompt, requirement_inventory
            )
            missing = [item for item in missing if capability_family(item) not in excluded_families]
            if missing:
                for capability in missing:
                    session.add(
                        ConnectionRequirement(
                            workspace_id=workspace_id,
                            run_id=run.id,
                            capability=capability,
                            provider_hint=capability,
                            reason=f"Connect {capability} so AURA can finish the saved plan",
                            required_permissions=next(
                                (
                                    item["allowed_operations"]
                                    for item in requirement_inventory
                                    if _connection_family(item) == capability
                                ),
                                [],
                            ),
                        )
                    )
                blocker = {
                    "kind": "human_action",
                    "code": "connection_required",
                    "message": "One or more capability providers must be connected",
                    "action": "connect_account",
                    "missing_capabilities": missing,
                    "retryable": False,
                }
                transition_run(
                    run,
                    RunStatus.waiting_for_action,
                    reason="planning_catalog_connection_required",
                    actor="planner-recovery",
                    phase="connection",
                    supervisor_status="human_action_required",
                    error=blocker["message"],
                    result={
                        "status": "waiting_for_connection",
                        "missing_capabilities": missing,
                    },
                    blocker=blocker,
                    dispatch=None,
                )
                await audit(
                    session,
                    workspace_id,
                    "run.connection_required",
                    {
                        "missing_capabilities": missing,
                        "recovery": "explicit_catalog_provider_after_planning_failure",
                    },
                    run.id,
                    actor="planner-recovery",
                )
                await session.commit()
                return
            await recover_planning_failure(
                session,
                run,
                exc,
                max_attempts=get_settings().max_planning_recovery_rounds,
                base_delay_seconds=get_settings().autonomous_recovery_base_delay_seconds,
                max_delay_seconds=get_settings().autonomous_recovery_max_delay_seconds,
            )
            await session.commit()


async def _trust_state(session, workspace_id: str, tool: ToolConnection) -> ToolTrustState:
    state = await session.scalar(
        select(ToolTrustState).where(
            ToolTrustState.workspace_id == workspace_id,
            ToolTrustState.tool_id == tool.id,
        )
    )
    if not state:
        # Concurrent first runs may initialize the same connector. Resolve that
        # race atomically without rolling back either workflow's checkpoints.
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        await session.execute(
            insert(ToolTrustState)
            .values(workspace_id=workspace_id, tool_id=tool.id, score=1.0)
            .on_conflict_do_nothing(index_elements=["workspace_id", "tool_id"])
        )
        state = await session.scalar(
            select(ToolTrustState).where(
                ToolTrustState.workspace_id == workspace_id, ToolTrustState.tool_id == tool.id
            )
        )
    return state


def _update_trust(
    state: ToolTrustState,
    *,
    succeeded: bool,
    timed_out: bool,
    latency_ms: float,
) -> None:
    if succeeded:
        state.success_count += 1
    else:
        state.failure_count += 1
    if timed_out:
        state.timeout_count += 1
    total = state.success_count + state.failure_count
    reliability = (state.success_count + 4) / (total + 5)
    incident_penalty = 0.30 if state.incident_active else 0.0
    timeout_penalty = min(0.20, state.timeout_count * 0.02)
    state.score = max(0.0, min(1.0, reliability - incident_penalty - timeout_penalty))
    state.last_latency_ms = latency_ms


def _partial_result(outputs: list[dict], step: RunStep, error: str) -> dict:
    return {
        "partial": True,
        "accepted_artifacts": outputs,
        "failed_step": {
            "id": step.id,
            "position": step.position,
            "tool_slug": step.tool_slug,
            "operation": step.operation,
            "error": error,
        },
        "available_actions": ["retry", "fallback", "skip", "cancel"],
    }


async def review_recorded_result(session, run, step, snapshot, contract, result):
    from .completeness import incomplete_evidence
    from .operation_contracts import output_errors

    errors = (
        []
        if step.output.get("reconciliation", {}).get("status") == "verified"
        else output_errors(step.operation, result)
    ) + incomplete_evidence(step.operation, result, contract.get("required_evidence", []))
    if errors:
        return CriticDecision(action="escalate", reasons=errors)
    if step.operation == "calendar.list":
        from .calendar_time import calendar_list_errors

        errors = calendar_list_errors(contract.get("arguments", {}), result)
        if not errors:
            step.output = {
                **step.output,
                "outcome_check": {
                    "status": "verified",
                    "mode": "accepted_read_receipt",
                    "operation": step.operation,
                },
            }
        return CriticDecision(
            action="escalate" if errors else "accept",
            reasons=errors
            or [
                "Calendar event structure and query interval verified deterministically; semantic appointment selection remains downstream"
            ],
        )
    check = step.output.get("outcome_check", {})
    if check.get("status") != "verified":
        check = await check_provider_outcome(session, run, step, snapshot)
        if check.get("status") != "unsupported":
            step.output = {**step.output, "outcome_check": check}
            await session.commit()
    if check.get("status") not in {"verified", "unsupported"}:
        return CriticDecision(
            action="escalate", reasons=check.get("reasons", ["Read-back is incomplete"])
        )
    if check.get("status") == "verified":
        # Job polling observes the terminal provider response. Pass that response
        # downstream instead of the original in_progress receipt, including on resume.
        if step.operation in {"canva.presentation.create", "canva.export.create"}:
            observed_job = check.get("observed", {}).get("job")
            if observed_job and observed_job.get("id") == result.get("job", {}).get("id"):
                result.update(job=observed_job)
                step.output = {**step.output, "provider_result": dict(result)}
        return CriticDecision(
            action="accept", reasons=["Provider read-back matches the approved action fields"]
        )
    evidence = (
        {**result, "__aura_readback__": check["observed"]}
        if check.get("observed") and isinstance(result, dict)
        else result
    )
    review_contract = {key: value for key, value in contract.items() if key != "required_evidence"}
    review_contract["validated_capability_tags"] = contract.get("required_evidence", [])
    decision = await critique_step(review_contract, evidence)
    # A read receipt is the provider observation itself. Once its typed output,
    # completeness requirements and semantic contract are accepted, mark that
    # evidence verified instead of asking a write-oriented read-back checker to
    # verify the same read again. Consequential operations still require their
    # dedicated provider read-back contract above.
    if decision.action == "accept" and operation_scope(step.operation) == "read":
        step.output = {
            **step.output,
            "outcome_check": {
                "status": "verified",
                "mode": "accepted_read_receipt",
                "operation": step.operation,
            },
        }
    return decision


@trace_run
async def execute_run(run_id: str, workspace_id: str) -> None:
    async with execution_lock(engine, workspace_id, run_id) as acquired:
        if acquired:
            async with SessionLocal() as session:
                await set_tenant_context(session, workspace_id)
                state = await session.scalar(
                    select(WorkflowRun.status).where(
                        WorkflowRun.id == run_id, WorkflowRun.workspace_id == workspace_id
                    )
                )
                if state not in {RunStatus.running, RunStatus.recovering}:
                    return
            for _ in range(3):
                await _execute_run(run_id, workspace_id)
                if await autonomously_recover_run(run_id, workspace_id) in {
                    "scheduled",
                    "handoff",
                }:
                    break
                replanning = await maybe_replan_run(run_id, workspace_id)
                if replanning != "retry":
                    if replanning is False:
                        await mark_autonomous_handoff(run_id, workspace_id)
                    break


async def _execute_run(run_id: str, workspace_id: str) -> None:
    vault = CredentialVault()
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if not run or run.workspace_id != workspace_id:
            return
        if not (run.execution_context or {}).get("execution_mode"):
            automated_origin = await session.scalar(
                select(AuditEvent.id)
                .where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.run_id == run_id,
                    AuditEvent.event_type.in_(
                        [
                            "schedule.dispatched",
                            "polling.change_detected",
                            "webhook.delivery_accepted",
                            "webhook.delivery_replayed",
                        ]
                    ),
                )
                .limit(1)
            )
            if automated_origin:
                run.execution_context = {
                    **(run.execution_context or {}),
                    "execution_mode": "unattended",
                }
        recovery_context = dict(run.execution_context or {})
        recovery_counts = dict(recovery_context.get("__aura_recovery__") or {})
        if run.status not in {RunStatus.running, RunStatus.recovering}:
            return
        if run.cancellation_requested:
            transition_run(
                run,
                RunStatus.cancelled,
                reason="cancellation_observed_before_execution",
                actor="senior-orchestrator",
                phase="execution",
                supervisor_status="cancelled",
                dispatch=None,
            )
            await audit(
                session,
                workspace_id,
                "run.cancelled",
                {"phase": "before_execution"},
                run.id,
            )
            await session.commit()
            return
        if not run.plan_approved:
            transition_run(
                run,
                RunStatus.awaiting_approval,
                reason="execution_requires_plan_approval",
                actor="senior-orchestrator",
                phase="approval",
                supervisor_status="human_action_required",
                blocker={
                    "kind": "human_action",
                    "code": "plan_approval_required",
                    "message": "Review and approve the workflow plan.",
                    "action": "review_plan",
                    "retryable": False,
                },
                dispatch=None,
            )
            await session.commit()
            return
        autonomy = deepcopy((run.execution_context or {}).get("__aura_autonomy__") or {})
        if run.status == RunStatus.recovering and autonomy.get("next_attempt_at"):
            autonomy["next_attempt_at"] = None
            autonomy["last_started_at"] = datetime.now(UTC).isoformat()
            run.execution_context = {
                **(run.execution_context or {}),
                "__aura_autonomy__": autonomy,
            }
            await audit(
                session,
                workspace_id,
                "run.autonomous_recovery_started",
                {
                    "action": autonomy.get("last_action"),
                    "recovery_round": autonomy.get("rounds"),
                },
                run.id,
                actor="senior-orchestrator",
            )
            await session.commit()

        plan_version = await session.scalar(
            select(PlanVersion)
            .where(PlanVersion.run_id == run.id, PlanVersion.status == "approved")
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        snapshot = await session.scalar(
            select(ApprovalSnapshot)
            .where(ApprovalSnapshot.run_id == run.id)
            .order_by(ApprovalSnapshot.approved_at.desc())
            .limit(1)
        )
        current_hash = canonical_plan_hash(run.plan)
        if (
            not plan_version
            or not snapshot
            or plan_version.plan_hash != current_hash
            or snapshot.plan_hash != current_hash
        ):
            message = "Approved plan integrity check failed; re-approval is required"
            transition_run(
                run,
                RunStatus.waiting_for_action,
                reason="approved_plan_integrity_failed",
                actor="policy-governor",
                phase="approval",
                supervisor_status="human_action_required",
                error=message,
                blocker={
                    "kind": "human_action",
                    "code": "plan_approval_required",
                    "message": message,
                    "action": "review_plan",
                    "retryable": False,
                },
                dispatch=None,
                metadata={"current_hash": current_hash},
            )
            await audit(
                session,
                workspace_id,
                "run.plan_integrity_failed",
                {"current_hash": current_hash},
                run.id,
            )
            await session.commit()
            return

        steps = (
            await session.scalars(
                select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
            )
        ).all()
        plan_steps = run.plan.get("steps") or []
        if len(steps) != len(plan_steps):
            transition_run(
                run,
                RunStatus.waiting_for_action,
                reason="executable_step_count_mismatch",
                actor="run-supervisor",
                phase="execution",
                supervisor_status="operator_attention",
                error="Executable step count differs from the approved plan",
                dispatch=None,
            )
            await session.commit()
            return
        for stored, approved in zip(steps, plan_steps, strict=True):
            primary_match = stored.tool_slug == approved.get(
                "tool_slug"
            ) and stored.operation == approved.get("operation")
            approved_fallback_match = (
                bool(approved.get("fallback_tool_slug"))
                and stored.tool_slug == approved.get("fallback_tool_slug")
                and stored.operation == approved.get("fallback_operation")
            )
            mismatch = (
                not (primary_match or approved_fallback_match)
                or stored.step_key != approved.get("key", f"step_{stored.position + 1}")
                or stored.depends_on != approved.get("depends_on", [])
                or stored.dependency_mode != approved.get("dependency_mode", "all_succeeded")
                or stored.condition != approved.get("condition")
                or stored.output_variables != approved.get("output_variables", {})
                or stored.arguments
                not in (
                    approved.get("arguments", {}),
                    approved.get("reduced_scope_arguments"),
                )
                or stored.consequential != approved.get("consequential", False)
            )
            if mismatch:
                transition_run(
                    run,
                    RunStatus.waiting_for_action,
                    reason="executable_plan_mismatch",
                    actor="run-supervisor",
                    phase="execution",
                    supervisor_status="operator_attention",
                    error="Executable steps differ from the immutable approved plan",
                    dispatch=None,
                    metadata={"step_id": stored.id},
                )
                await audit(
                    session,
                    workspace_id,
                    "run.executable_plan_mismatch",
                    {"step_id": stored.id},
                    run.id,
                )
                await session.commit()
                return

        # Prove current credentials and literal resource access before the first
        # workflow step.  This phase is read-only, durably checkpointed, and may
        # schedule its own delayed delivery for temporary provider failures.
        from .execution_preflight import preflight_approved_run

        preflight = await preflight_approved_run(session, run, steps)
        if preflight.status != "passed":
            return

        transition_run(
            run,
            RunStatus.running,
            reason="execution_preflight_passed",
            actor="run-supervisor",
            phase="execution",
            supervisor_status="active",
            error=None,
            blocker=None,
            dispatch=None,
            allow_same=True,
        )
        await session.commit()

        outputs: list[dict] = []
        context = deepcopy(run.execution_context) or {
            "inputs": run.inputs or {},
            "vars": run.inputs or {},
            "steps": {},
        }
        supervision, supervision_source = await supervise_execution(
            run.prompt,
            run.plan,
            [
                {
                    "key": step.step_key,
                    "status": step.status.value,
                    "tool_slug": step.tool_slug,
                    "operation": step.operation,
                    "depends_on": step.depends_on,
                    "consequential": step.consequential,
                    "has_recorded_receipt": isinstance(step.output, dict)
                    and "provider_result" in step.output,
                }
                for step in steps
            ],
        )
        context["agent_supervision"] = {
            "orchestrator": "AURA Senior Orchestrator",
            "action": supervision.action,
            "reason": supervision.reason,
            "source": supervision_source,
            "delegations": [
                delegation.model_dump(mode="json") for delegation in supervision.delegations
            ],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        run.execution_context = deepcopy(context)
        await audit(
            session,
            workspace_id,
            "run.execution_supervised",
            {
                "action": supervision.action,
                "reason": supervision.reason,
                "source": supervision_source,
                "delegation_count": len(supervision.delegations),
            },
            run.id,
            actor="senior-orchestrator",
        )
        if supervision.action == "pause":
            message = f"The Senior Orchestrator paused execution for review: {supervision.reason}"
            transition_run(
                run,
                RunStatus.waiting_for_action,
                reason="execution_supervisor_paused",
                actor="senior-orchestrator",
                phase="execution",
                supervisor_status="operator_attention",
                error=message,
                dispatch=None,
            )
            await session.commit()
            return
        delegations = {delegation.step_key: delegation for delegation in supervision.delegations}
        await session.commit()
        step_by_key = {step.step_key: step for step in steps}
        for step in steps:
            from .parallel_reads import prefetch_ready_reads

            await prefetch_ready_reads(
                session, run, steps, step.position, snapshot, context, outputs
            )
            materialized_for_approval = False
            recorded_result = isinstance(step.output, dict) and "provider_result" in step.output
            if recorded_result and step.output.get("critic", {}).get("action") != "accept":
                from .verification_recovery import verification_due

                if not verification_due(step):
                    return
                contract = {
                    **plan_steps[step.position],
                    "step_id": step.id,
                    "arguments": step.output.get("resolved_arguments", step.arguments),
                }
                criticism = await review_recorded_result(
                    session, run, step, snapshot, contract, step.output["provider_result"]
                )
                step.output = {**step.output, "critic": criticism.model_dump(mode="json")}
                await audit(
                    session,
                    workspace_id,
                    "step.review_resumed",
                    {"step_id": step.id, "decision": criticism.model_dump(mode="json")},
                    run.id,
                )
                if criticism.action != "accept":
                    from .verification_recovery import defer_verification

                    if await defer_verification(session, run, step):
                        return
                    step.status = StepStatus.failed
                    step.error = "Recorded result needs review; no provider action was repeated."
                    transition_run(
                        run,
                        RunStatus.waiting_for_action,
                        reason="recorded_result_review_incomplete",
                        actor="outcome-checker",
                        phase="verification",
                        supervisor_status="recovering",
                        error=step.error,
                        result=_partial_result(outputs, step, step.error),
                        dispatch=None,
                        metadata={"step_id": step.id},
                    )
                    await session.commit()
                    return
                step.status = StepStatus.completed
                step.error = None
                step.completed_at = datetime.now(UTC)
                session.add(
                    Artifact(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        step_id=step.id,
                        accepted=True,
                        provenance={"plan_hash": snapshot.plan_hash, "review_resumed": True},
                        content=step.output,
                    )
                )
                await session.commit()
            if recorded_result:
                step.status = StepStatus.completed
            if step.status == StepStatus.completed:
                outputs.append(step.output)
                context.setdefault("steps", {})[step.step_key] = step_context_value(
                    step.output.get("provider_result", step.output), step.operation
                )
                for name, value in step.output_variables.items():
                    try:
                        context.setdefault("vars", {})[name] = resolve_value(value, context)
                    except WorkflowContextError:
                        logger.warning(
                            "Skipping unavailable output alias while preserving "
                            "confirmed write run_id=%s step_id=%s alias=%s",
                            run.id,
                            step.id,
                            name,
                        )
                run.execution_context = deepcopy(context)
                await mark_recovery_checkpoint_succeeded(session, run, step)
                await session.commit()
                continue
            if step.status == StepStatus.skipped:
                continue

            dependencies = [step_by_key.get(key) for key in step.depends_on]
            dependency_satisfied = all(
                dependency
                and (
                    dependency.status in {StepStatus.completed, StepStatus.skipped}
                    if step.dependency_mode == "all_settled"
                    else dependency.status == StepStatus.completed
                )
                for dependency in dependencies
            )
            if not dependency_satisfied:
                step.status = StepStatus.skipped
                step.output = {"reason": "dependency_not_satisfied"}
                logger.warning(
                    "Workflow step skipped run_id=%s step_key=%s "
                    "reason=dependency_not_satisfied dependencies=%s",
                    run.id,
                    step.step_key,
                    step.depends_on,
                )
                await audit(
                    session,
                    workspace_id,
                    "step.branch_skipped",
                    {"step_id": step.id, "reason": "dependency_not_satisfied"},
                    run.id,
                )
                await session.commit()
                continue
            try:
                if step.condition and not evaluate_condition(step.condition, context):
                    step.status = StepStatus.skipped
                    step.output = {"reason": "condition_false"}
                    logger.info(
                        "Workflow step skipped run_id=%s step_key=%s "
                        "reason=condition_false optional=%s",
                        run.id,
                        step.step_key,
                        plan_steps[step.position].get("optional", False),
                    )
                    await audit(
                        session,
                        workspace_id,
                        "step.branch_skipped",
                        {"step_id": step.id, "reason": "condition_false"},
                        run.id,
                    )
                    await session.commit()
                    continue
                resolved_arguments = canonical_action_arguments(
                    step.operation,
                    resolve_value(step.arguments, context),
                    context,
                )
            except WorkflowContextError as exc:
                if step.status == StepStatus.awaiting_approval:
                    try:
                        resolved_arguments = await materialize_action_arguments(
                            run.prompt,
                            plan_steps[step.position],
                            context,
                        )
                        materialized_for_approval = True
                    except Exception as recovery_exc:
                        internal_error = str(recovery_exc)
                        logger.exception(
                            "Approval argument recovery failed run_id=%s step_id=%s error_type=%s",
                            run.id,
                            step.id,
                            type(recovery_exc).__name__,
                        )
                        step.status = StepStatus.failed
                        step.error = _friendly_execution_error(internal_error)
                        transition_run(
                            run,
                            RunStatus.waiting_for_action,
                            reason="approval_argument_resolution_exhausted",
                            actor="recovery-engineer",
                            phase="execution",
                            supervisor_status="recovering",
                            error=step.error,
                            dispatch=None,
                            metadata={"step_id": step.id},
                        )
                        await audit(
                            session,
                            workspace_id,
                            "step.variable_resolution_recovery_exhausted",
                            {"step_id": step.id, "internal_error": internal_error},
                            run.id,
                        )
                        await session.commit()
                        return
                else:
                    internal_error = str(exc)
                    logger.exception(
                        "Workflow input resolution failed run_id=%s step_id=%s",
                        run.id,
                        step.id,
                    )
                    step.status = StepStatus.failed
                    step.error = _friendly_execution_error(internal_error)
                    transition_run(
                        run,
                        RunStatus.waiting_for_action,
                        reason="workflow_variable_resolution_failed",
                        actor="recovery-engineer",
                        phase="execution",
                        supervisor_status="recovering",
                        error=step.error,
                        dispatch=None,
                        metadata={"step_id": step.id},
                    )
                    await audit(
                        session,
                        workspace_id,
                        "step.variable_resolution_failed",
                        {"step_id": step.id, "internal_error": internal_error},
                        run.id,
                    )
                    await session.commit()
                    return

            if step.consequential and step.status == StepStatus.pending:
                # Runs approved by an older client can still carry a plan-only
                # approval with no completed action preview. Prepare it here
                # instead of letting the dispatch guard strand the saved run.
                previous = (
                    await session.get(Approval, step.approval_id)
                    if step.approval_id else await session.scalar(
                        select(Approval).where(Approval.step_id == step.id)
                    )
                )
                if not _approved_action_matches(
                    step, previous, step.tool_slug, step.operation, resolved_arguments
                ):
                    if previous is None:
                        previous = Approval(run_id=run.id, step_id=step.id)
                        session.add(previous)
                        await session.flush()
                    previous.status = "pending"
                    previous.decided_by = None
                    previous.decided_at = None
                    previous.preview = {"status": "preparing"}
                    step.approval_id = previous.id
                    step.status = StepStatus.awaiting_approval

            if step.status == StepStatus.awaiting_approval:
                approval = await session.get(Approval, step.approval_id)
                if not approval or approval.status != "pending":
                    step.status = StepStatus.failed
                    step.error = "AURA is safely rebuilding this approval."
                    transition_run(
                        run,
                        RunStatus.waiting_for_action,
                        reason="approval_record_missing",
                        actor="run-supervisor",
                        phase="execution",
                        supervisor_status="recovering",
                        error=step.error,
                        dispatch=None,
                        metadata={"step_id": step.id},
                    )
                    await session.commit()
                    return
                tool = await session.scalar(
                    select(ToolConnection).where(
                        ToolConnection.workspace_id == workspace_id,
                        ToolConnection.slug == step.tool_slug,
                        ToolConnection.enabled.is_(True),
                    )
                )
                if not tool:
                    message = "This app connection needs your attention before AURA can continue."
                    blocker = {
                        "kind": "human_action",
                        "code": "connection_required",
                        "message": message,
                        "action": "connect_account",
                        "tool_slug": step.tool_slug,
                        "retryable": False,
                    }
                    transition_run(
                        run,
                        RunStatus.waiting_for_action,
                        reason="approval_connection_unavailable",
                        actor="connection-supervisor",
                        phase="connection",
                        supervisor_status="human_action_required",
                        error=message,
                        blocker=blocker,
                        dispatch=None,
                        metadata={"step_id": step.id},
                    )
                    await session.commit()
                    return
                manifest_record = await session.scalar(
                    select(CapabilityManifest).where(
                        CapabilityManifest.tool_id == tool.id,
                        CapabilityManifest.status == "verified",
                    )
                )
                manifest = _current_capability_manifest(
                    step.tool_slug,
                    manifest_record.manifest if manifest_record else None,
                )
                try:
                    capability = next(
                        (
                            m
                            for m in manifest.get("capabilities", [])
                            if m.get("name") == step.operation
                        ),
                        {},
                    )
                    if not materialized_for_approval and (
                        unfinished_action_content(step.operation, resolved_arguments)
                        or requires_content_composition(
                            plan_steps[step.position].get("arguments", {}),
                            capability.get("input_schema", {}),
                            context,
                        )
                    ):
                        raise NativeConnectorError(
                            "Action content requires composition from completed evidence before approval"
                        )
                    resolved_arguments = normalize_planned_module_arguments(
                        manifest, step.operation, resolved_arguments
                    )
                    if referenced_paths(resolved_arguments):
                        raise NativeConnectorError("Approval arguments are not concrete")
                    if unfinished_action_content(step.operation, resolved_arguments):
                        raise NativeConnectorError("Action content is still an unfinished draft")
                except (NativeConnectorError, ValueError) as exc:
                    if not materialized_for_approval:
                        try:
                            resolved_arguments = await materialize_action_arguments(
                                run.prompt,
                                plan_steps[step.position],
                                context,
                            )
                            resolved_arguments = normalize_planned_module_arguments(
                                manifest, step.operation, resolved_arguments
                            )
                            if referenced_paths(resolved_arguments):
                                raise NativeConnectorError("Approval arguments are not concrete")
                            if unfinished_action_content(step.operation, resolved_arguments):
                                raise NativeConnectorError("Action content is still an unfinished draft")
                        except Exception as recovery_exc:
                            logger.exception(
                                "Approval argument validation recovery failed "
                                "run_id=%s step_id=%s error_type=%s",
                                run.id,
                                step.id,
                                type(recovery_exc).__name__,
                            )
                            step.status = StepStatus.failed
                            step.error = _friendly_execution_error(str(recovery_exc))
                            transition_run(
                                run,
                                RunStatus.waiting_for_action,
                                reason="approval_argument_validation_recovery_exhausted",
                                actor="recovery-engineer",
                                phase="execution",
                                supervisor_status="recovering",
                                error=step.error,
                                dispatch=None,
                                metadata={"step_id": step.id},
                            )
                            await audit(
                                session,
                                workspace_id,
                                "step.approval_argument_validation_recovery_exhausted",
                                {
                                    "step_id": step.id,
                                    "internal_error": str(recovery_exc),
                                    "phase": "preparing_arguments",
                                },
                                run.id,
                            )
                            await session.commit()
                            return
                    else:
                        logger.exception(
                            "Approval argument validation failed run_id=%s step_id=%s",
                            run.id,
                            step.id,
                        )
                        step.status = StepStatus.failed
                        step.error = _friendly_execution_error(str(exc))
                        transition_run(
                            run,
                            RunStatus.waiting_for_action,
                            reason="approval_argument_validation_failed",
                            actor="recovery-engineer",
                            phase="execution",
                            supervisor_status="recovering",
                            error=step.error,
                            dispatch=None,
                            metadata={"step_id": step.id},
                        )
                        await audit(
                            session,
                            workspace_id,
                            "step.approval_argument_validation_failed",
                            {"step_id": step.id, "internal_error": str(exc)},
                            run.id,
                        )
                        await session.commit()
                        return
                if step.operation == "gmail.send" and resolved_arguments.get("attachments"):
                    from .file_delivery import prepare_attachments

                    # Exact URLs from verified completed exports in this tenant/run.
                    exports = [
                        s.output
                        for s in steps
                        if s.status == StepStatus.completed
                        and s.operation == "canva.export.create"
                        and s.output.get("outcome_check", {}).get("status") == "verified"
                    ]
                    urls = {
                        url
                        for output in exports
                        for url in output.get("outcome_check", {})
                        .get("observed", {})
                        .get("job", {})
                        .get("urls", [])
                    }
                    try:
                        resolved_arguments = await prepare_attachments(resolved_arguments, urls)
                    except Exception:  # noqa: BLE001 - preserve the completed export across any attachment failure
                        message = (
                            "PDF preparation failed before sending. The completed Canva "
                            "export is preserved; retry file preparation."
                        )
                        transition_run(
                            run,
                            RunStatus.waiting_for_action,
                            reason="attachment_preparation_failed",
                            actor="recovery-engineer",
                            phase="execution",
                            supervisor_status="recovering",
                            error=message,
                            dispatch=None,
                            metadata={"step_id": step.id},
                        )
                        await session.commit()
                        return
                if step.operation == "gmail.send":
                    try:
                        resolved_arguments = await _reviewable_gmail_recipient(
                            tool, manifest_record, resolved_arguments
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve unsent action for recovery
                        logger.warning(
                            "Gmail recipient review preparation deferred run_id=%s step_id=%s error_type=%s",
                            run.id,
                            step.id,
                            type(exc).__name__,
                        )
                        transition_run(
                            run,
                            RunStatus.waiting_for_action,
                            reason="review_recipient_preparation_failed",
                            actor="recovery-engineer",
                            phase="execution",
                            supervisor_status="recovering",
                            error="AURA is verifying the connected email address before review.",
                            dispatch=None,
                            metadata={"step_id": step.id},
                        )
                        await session.commit()
                        return
                approval_preview = {
                    "status": "ready",
                    "tool_slug": step.tool_slug,
                    "operation": step.operation,
                    "arguments": resolved_arguments,
                    "review_contract": build_review_contract(
                        step.operation,
                        resolved_arguments,
                        capability,
                        tool.display_name,
                    ),
                }
                approval_group = plan_steps[step.position].get("approval_group")
                if approval_group:
                    group_id = f"{run.id}:{approval_group}"
                    grouped_steps = []
                    for future_step in steps[step.position + 1 :]:
                        future_plan_step = plan_steps[future_step.position]
                        if (
                            future_plan_step.get("approval_group") != approval_group
                            or future_step.status != StepStatus.awaiting_approval
                            or not future_step.approval_id
                        ):
                            continue
                        future_arguments = _future_group_review_arguments(
                            future_step.operation,
                            future_step.arguments,
                            context,
                        )
                        if future_arguments is None:
                            continue
                        future_approval = await session.get(Approval, future_step.approval_id)
                        future_tool = await session.scalar(
                            select(ToolConnection).where(
                                ToolConnection.workspace_id == workspace_id,
                                ToolConnection.slug == future_step.tool_slug,
                                ToolConnection.enabled.is_(True),
                            )
                        )
                        if (
                            not future_approval
                            or future_approval.status != "pending"
                            or not future_tool
                        ):
                            continue
                        future_manifest_record = await session.scalar(
                            select(CapabilityManifest).where(
                                CapabilityManifest.tool_id == future_tool.id,
                                CapabilityManifest.status == "verified",
                            )
                        )
                        future_manifest = _current_capability_manifest(
                            future_step.tool_slug,
                            future_manifest_record.manifest
                            if future_manifest_record
                            else None,
                        )
                        try:
                            future_arguments = normalize_planned_module_arguments(
                                future_manifest,
                                future_step.operation,
                                future_arguments,
                            )
                        except (NativeConnectorError, ValueError):
                            continue
                        if unfinished_action_content(future_step.operation, future_arguments):
                            continue
                        if future_step.operation == "gmail.send":
                            try:
                                future_arguments = await _reviewable_gmail_recipient(
                                    future_tool, future_manifest_record, future_arguments
                                )
                            except Exception as exc:  # noqa: BLE001 - review this action on its own later
                                logger.warning(
                                    "Grouped Gmail recipient preview deferred run_id=%s step_id=%s error_type=%s",
                                    run.id,
                                    future_step.id,
                                    type(exc).__name__,
                                )
                                continue
                        future_capability = next(
                            (
                                item
                                for item in future_manifest.get("capabilities", [])
                                if item.get("name") == future_step.operation
                            ),
                            {},
                        )
                        future_approval.preview = {
                            "status": "ready",
                            "tool_slug": future_step.tool_slug,
                            "operation": future_step.operation,
                            "arguments": future_arguments,
                            "review_contract": build_review_contract(
                                future_step.operation,
                                future_arguments,
                                future_capability,
                                future_tool.display_name,
                            ),
                            "group_id": group_id,
                        }
                        grouped_steps.append(future_step.id)
                    if grouped_steps:
                        approval_preview["group_id"] = group_id
                        approval_preview["grouped_step_ids"] = grouped_steps
                approval.preview = approval_preview
                run.execution_context = deepcopy(context)
                transition_run(
                    run,
                    RunStatus.awaiting_approval,
                    reason="consequential_step_ready_for_approval",
                    actor="senior-orchestrator",
                    phase="approval",
                    supervisor_status="human_action_required",
                    blocker={
                        "kind": "human_action",
                        "code": "external_submission_approval_required",
                        "message": "Review this consequential action before it is submitted.",
                        "action": "review_step",
                        "step_id": step.id,
                        "retryable": False,
                    },
                    dispatch=None,
                    metadata={"step_id": step.id, "operation": step.operation},
                )
                await audit(
                    session,
                    workspace_id,
                    "step.approval_preview_ready",
                    {"step_id": step.id, "operation": step.operation},
                    run.id,
                )
                await session.commit()
                return

            if (
                step.operation == "gmail.send"
                and resolved_arguments.get("attachments")
                and any(
                    not isinstance(item, dict) or not item.get("sha256")
                    for item in resolved_arguments["attachments"]
                )
            ):
                from .file_delivery import prepare_attachments

                export_urls = {
                    url
                    for completed_step in steps
                    if completed_step.status == StepStatus.completed
                    and completed_step.operation == "canva.export.create"
                    and completed_step.output.get("outcome_check", {}).get("status")
                    == "verified"
                    for url in completed_step.output.get("outcome_check", {})
                    .get("observed", {})
                    .get("job", {})
                    .get("urls", [])
                }
                try:
                    resolved_arguments = await prepare_attachments(
                        resolved_arguments,
                        export_urls,
                    )
                except Exception:  # noqa: BLE001 - preserve completed upstream artifacts
                    message = (
                        "PDF preparation failed before sending. The completed Canva "
                        "presentation is preserved; retry file preparation."
                    )
                    transition_run(
                        run,
                        RunStatus.waiting_for_action,
                        reason="attachment_preparation_failed",
                        actor="recovery-engineer",
                        phase="execution",
                        supervisor_status="recovering",
                        error=message,
                        dispatch=None,
                        metadata={"step_id": step.id},
                    )
                    await session.commit()
                    return

            tool = await session.scalar(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == workspace_id,
                    ToolConnection.slug == step.tool_slug,
                    ToolConnection.enabled.is_(True),
                )
            )
            if not tool:
                step.status = StepStatus.failed
                message = f"Tool {step.tool_slug!r} is unavailable"
                blocker = {
                    "kind": "human_action",
                    "code": "connection_required",
                    "message": message,
                    "action": "connect_account",
                    "tool_slug": step.tool_slug,
                    "retryable": False,
                }
                transition_run(
                    run,
                    RunStatus.waiting_for_action,
                    reason="execution_connection_unavailable",
                    actor="connection-supervisor",
                    phase="connection",
                    supervisor_status="human_action_required",
                    error=message,
                    result=_partial_result(outputs, step, message),
                    blocker=blocker,
                    dispatch=None,
                    metadata={"step_id": step.id},
                )
                await session.commit()
                return

            if (run.execution_context or {}).get("execution_mode") == "unattended":
                from .assurance import operation_readiness

                readiness = await operation_readiness(session, workspace_id, tool, step.operation)
                if not readiness["execution_ready"]:
                    transition_run(
                        run,
                        RunStatus.blocked,
                        reason="operation_certification_required",
                        actor="assurance-controller",
                        phase="execution",
                        supervisor_status="operator_attention",
                        error="Operation certification is required for unattended execution",
                        result={**(run.result or {}), "readiness": readiness},
                        dispatch=None,
                        metadata={"step_id": step.id, "operation": step.operation},
                    )
                    await session.commit()
                    return
            trust = await _trust_state(session, workspace_id, tool)
            if trust.incident_active:
                transition_run(
                    run,
                    RunStatus.waiting_for_action,
                    reason="connector_incident_active",
                    actor="connection-supervisor",
                    phase="connection",
                    supervisor_status="recovering",
                    error="Connector incident is active; execution is paused",
                    dispatch=None,
                    metadata={"step_id": step.id, "tool_slug": tool.slug},
                )
                await session.commit()
                return
            approved_permissions = snapshot.permission_snapshot.get(tool.slug, [])
            actual_cost = sum(
                float(output.get("provider_result", {}).get("cost_usd", 0.0))
                for output in outputs
                if isinstance(output.get("provider_result"), dict)
            )
            trust_floor = float(snapshot.policy_snapshot["trust_execution_floor"])
            recovery_count = int(recovery_counts.get(step.id, 0))
            effective_trust, degraded_read_recovery = _bounded_read_trust_score(
                step.operation,
                trust.score,
                trust_floor,
                recovery_count,
            )
            if degraded_read_recovery:
                recovery_counts[step.id] = recovery_count + 1
                context["__aura_recovery__"] = recovery_counts
                run.execution_context = deepcopy(context)
                await audit(
                    session,
                    workspace_id,
                    "step.degraded_trust_read_recovery",
                    {
                        "step_id": step.id,
                        "recovery_attempt": recovery_count + 1,
                    },
                    run.id,
                    actor="policy-governor",
                )
                await session.commit()
            runtime_decision = runtime_policy_check(
                approved_cost=float(snapshot.cost_snapshot.get("estimated_cost_usd", 0.0)),
                actual_cost=actual_cost,
                approved_permissions=approved_permissions,
                current_permissions=tool.allowed_operations,
                operation=step.operation,
                trust_score=effective_trust,
                policy=snapshot.policy_snapshot,
            )
            if runtime_decision["action"] in {"pause", "block"}:
                target_status = (
                    RunStatus.blocked
                    if runtime_decision["action"] == "block"
                    else RunStatus.waiting_for_action
                )
                step.status = StepStatus.failed
                step.error = "; ".join(runtime_decision["reasons"])
                transition_run(
                    run,
                    target_status,
                    reason=f"runtime_policy_{runtime_decision['action']}",
                    actor="policy-governor",
                    phase="execution",
                    supervisor_status="operator_attention",
                    error=step.error,
                    result=_partial_result(outputs, step, step.error),
                    dispatch=None,
                    metadata={"step_id": step.id},
                )
                await audit(
                    session,
                    workspace_id,
                    f"step.policy_{runtime_decision['action']}",
                    {"step_id": step.id, **runtime_decision},
                    run.id,
                    actor="policy-governor",
                )
                await session.commit()
                return
            if runtime_decision["reasons"]:
                await audit(
                    session,
                    workspace_id,
                    "step.policy_warning",
                    {"step_id": step.id, **runtime_decision},
                    run.id,
                    actor="policy-governor",
                )

            step.status = StepStatus.running
            step.started_at = datetime.now(UTC)
            run.updated_at = step.started_at
            await audit(
                session,
                workspace_id,
                "step.started",
                {"step_id": step.id, "operation": step.operation},
                run.id,
            )
            await session.commit()

            async def call(
                active_tool: ToolConnection,
                operation: str,
                arguments: dict,
                step: RunStep = step,
            ) -> tuple[dict | None, str | None]:
                manifest_record = await session.scalar(
                    select(CapabilityManifest).where(
                        CapabilityManifest.tool_id == active_tool.id,
                        CapabilityManifest.status == "verified",
                    )
                )
                runtime_manifest = _current_capability_manifest(
                    active_tool.slug,
                    manifest_record.manifest if manifest_record else None,
                )
                runtime_capability = next(
                    (
                        item
                        for item in runtime_manifest.get("capabilities", [])
                        if item.get("name") == operation
                    ),
                    None,
                )
                consequential = _operation_is_consequential(
                    operation,
                    runtime_capability,
                    planned_consequential=step.consequential,
                )
                governed_derivative = (
                    not step.consequential
                    and operation == "canva.export.create"
                    and is_governed_derivative_step(
                        WorkflowPlan.model_validate(run.plan),
                        PlanStep.model_validate(plan_steps[step.position]),
                    )
                )
                if consequential and not step.consequential and not governed_derivative:
                    # Persist the verified provider contract's side-effect class
                    # before any attempt. This protects unfamiliar operation names
                    # (for example, records.mutate) from read-style retries and
                    # preserves the no-replay decision across worker restarts.
                    step.consequential = True
                approved_action = (
                    await session.get(Approval, step.approval_id)
                    if consequential and step.approval_id else None
                )
                if consequential and not governed_derivative and not _approved_action_matches(
                    step, approved_action, active_tool.slug, operation, arguments
                ):
                    return None, "[authorization_required] Review the exact action before submitting it"

                def confirm_provider_arguments(prepared: dict) -> None:
                    if consequential and not governed_derivative and not _approved_action_matches(
                        step, approved_action, active_tool.slug, operation, prepared
                    ):
                        raise ValueError("Connector changed the approved action; a new review is required")
                if operation == "gmail.send" and arguments.get("attachments"):
                    permitted_urls = {
                        url
                        for s in steps
                        if s.operation == "canva.export.create"
                        and s.status == StepStatus.completed
                        and s.output.get("outcome_check", {}).get("status") == "verified"
                        for url in s.output.get("outcome_check", {})
                        .get("observed", {})
                        .get("job", {})
                        .get("urls", [])
                    }
                    if any(
                        item.get("url") not in permitted_urls for item in arguments["attachments"]
                    ):
                        return (
                            None,
                            "[invalid_request] Attachments must come from verified exports in this run",
                        )
                from .extended_outcomes import required_reads

                verification_reads = required_reads(operation, arguments)
                if not verification_reads <= (
                    set(active_tool.allowed_operations)
                    & set(snapshot.permission_snapshot.get(active_tool.slug, []))
                ):
                    return (
                        None,
                        "[authorization_required] Read-back permissions must be approved before the write",
                    )
                active_trust = await _trust_state(session, workspace_id, active_tool)
                all_existing = (
                    await session.scalars(
                        select(StepAttempt)
                        .where(StepAttempt.step_id == step.id)
                        .order_by(StepAttempt.attempt_number)
                    )
                ).all()
                existing = attempts_for_current_cycle(
                    all_existing,
                    run.execution_context or {},
                    step.id,
                    consequential,
                    idempotency_key=step.idempotency_key,
                )
                if existing:
                    latest = max(existing, key=lambda item: item.attempt_number)
                    if (latest.error or "").startswith(
                        (
                            "[authorization_required]",
                            "[invalid_request]",
                            "[contract_or_runtime_error]",
                            "[budget_exhausted]",
                            "[rate_limited]",
                        )
                    ):
                        return None, latest.error
                if consequential and existing:
                    if operation in RECONCILIABLE_WRITES:
                        # Confirm the requested state using the approved identifier; never repeat the write.
                        step.output = {**step.output, "resolved_arguments": arguments}
                        check = await check_provider_outcome(session, run, step, snapshot)
                        if check.get("status") == "verified":
                            observed = check["observed"]
                            step.output = {
                                "step_id": step.id,
                                "provider_result": observed,
                                "tool": active_tool.slug,
                                "operation": operation,
                                "resolved_arguments": arguments,
                                "outcome_check": check,
                                "reconciliation": {
                                    "status": "verified",
                                    "meaning": "requested_state_confirmed",
                                },
                                "critic": {"action": "escalate", "reasons": ["Review pending"]},
                            }
                            await audit(
                                session,
                                workspace_id,
                                "step.uncertain_write_reconciled",
                                {"step_id": step.id},
                                run.id,
                            )
                            await session.commit()
                            return observed, None
                        await session.commit()
                    return (
                        None,
                        "Previous action outcome is uncertain; reconcile provider state before a new approved action",
                    )
                max_retries = (
                    0 if consequential else int(snapshot.policy_snapshot["max_retries_per_step"])
                )
                from .reliability import classify_failure

                remaining = min(max_retries + 1, get_settings().max_provider_attempts) - len(
                    existing
                )
                if remaining <= 0:
                    return None, "Provider attempt budget exhausted; recorded work is preserved"
                backoffs = list(snapshot.policy_snapshot["retry_backoff_seconds"]) or [1]
                retry_after = 0.0
                last_error: str | None = None
                for retry_index in range(remaining):
                    await session.refresh(run, attribute_names=["cancellation_requested"])
                    if run.cancellation_requested:
                        return None, "Run cancellation requested"
                    if retry_index:
                        delay = backoffs[min(retry_index - 1, len(backoffs) - 1)]
                        delay = max(float(delay), retry_after)
                        if delay > 30:
                            return None, "Provider rate limit exceeds immediate retry budget"
                        await asyncio.sleep(delay)
                    attempt = StepAttempt(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        step_id=step.id,
                        attempt_number=(
                            max((item.attempt_number for item in all_existing), default=0)
                            + retry_index
                            + 1
                        ),
                        status="running",
                        provider_dispatched=False,
                        tool_slug=active_tool.slug,
                        operation=operation,
                    )
                    session.add(attempt)
                    await session.commit()
                    started = time.perf_counter()
                    timed_out = False

                    async def mark_provider_dispatched(
                        current_attempt: StepAttempt = attempt,
                    ) -> None:
                        """Persist the no-return boundary before the external action."""
                        if current_attempt.provider_dispatched:
                            return
                        current_attempt.provider_dispatched = True
                        await session.commit()

                    try:
                        from .reliability import BudgetExceeded, model_budget

                        budget = model_budget.get()
                        if budget and time.monotonic() >= budget.deadline:
                            raise BudgetExceeded("Delivery time budget exhausted")
                        if not manifest_record:
                            raise RuntimeError("Capability provider is not verified")
                        execution_timeout = (
                            min(
                                float(snapshot.policy_snapshot["step_timeout_seconds"]),
                                max(0.01, budget.deadline - time.monotonic()),
                            )
                            if budget
                            else float(snapshot.policy_snapshot["step_timeout_seconds"])
                        )
                        broker_pack_id = (active_tool.config or {}).get(
                            "capability_pack_id"
                        )
                        release_id = (active_tool.config or {}).get(
                            "connector_release_id"
                        )
                        if (
                            active_tool.config.get("managed_by") == "pipedream"
                            and broker_pack_id
                        ):
                            from .pipedream_connect import (
                                pack_signature_valid as pipedream_pack_signature_valid,
                            )
                            from .pipedream_connect import (
                                pipedream_client,
                            )

                            pack = await session.get(BrokerCapabilityPack, broker_pack_id)
                            if (
                                not pack
                                or pack.backend != "pipedream"
                                or pack.provider_slug != active_tool.slug
                                or pack.definition_hash
                                != active_tool.config.get("capability_pack_hash")
                                or pack.status not in {"released", "superseded"}
                                or not pipedream_pack_signature_valid(pack)
                            ):
                                raise RuntimeError(
                                    "Connector capability pack is no longer trusted"
                                )
                            account_id = str(
                                active_tool.config.get("account_id")
                                or active_tool.external_connection_id
                                or ""
                            )
                            external_user_id = str(
                                active_tool.config.get("external_user_id") or ""
                            )
                            if not account_id or not external_user_id:
                                raise RuntimeError("Managed account reference is missing")
                            arguments, capability = _prepare_provider_arguments(
                                pack.definition, operation, arguments
                            )
                            confirm_provider_arguments(arguments)
                            await mark_provider_dispatched()
                            result = await asyncio.wait_for(
                                pipedream_client().run_action(
                                    external_user_id,
                                    account_id,
                                    capability,
                                    arguments,
                                ),
                                timeout=execution_timeout,
                            )
                            output_failures = list(
                                Draft202012Validator(
                                    capability.get("output_schema") or {}
                                ).iter_errors(result)
                            )
                            if output_failures:
                                raise ValueError(
                                    "Connector output failed its released schema"
                                )
                        elif active_tool.config.get("managed_by") == "nango" and release_id:
                            from .connector_engineer import release_signature_valid

                            release = await session.get(ManagedConnectorRelease, release_id)
                            if (
                                not release
                                or release.provider_slug != active_tool.slug
                                or release.integration_id
                                != active_tool.config.get("integration_id")
                                or release.definition_hash
                                != active_tool.config.get("connector_release_hash")
                                or release.status not in {"released", "superseded"}
                                or not release_signature_valid(release)
                            ):
                                raise RuntimeError(
                                    "Connector release is no longer trusted"
                                )
                            current_manifest = release.definition.get("manifest") or {}
                            connection_reference = managed_connection_reference(active_tool)
                            if not connection_reference:
                                raise RuntimeError("Managed connection reference is missing")
                            arguments, capability = _prepare_provider_arguments(
                                current_manifest, operation, arguments
                            )
                            confirm_provider_arguments(arguments)
                            await mark_provider_dispatched()
                            result = await asyncio.wait_for(
                                managed_connector_client().execute_capability(
                                    release.integration_id,
                                    connection_reference,
                                    capability,
                                    arguments,
                                ),
                                timeout=execution_timeout,
                            )
                            output_failures = list(
                                Draft202012Validator(
                                    capability.get("output_schema") or {}
                                ).iter_errors(result)
                            )
                            if output_failures:
                                raise ValueError(
                                    "Connector output failed its released schema"
                                )
                        else:
                            if active_tool.config.get("managed_by") == "nango":
                                credentials = await managed_connector_client().get_credentials(
                                    managed_connection_reference(active_tool)
                                    or active_tool.config["connection_id"],
                                    active_tool.config["integration_id"],
                                )
                                if active_tool.slug == "jira" and not credentials.get(
                                    "cloud_id"
                                ):
                                    verification = await verify_oauth_credentials(
                                        "jira", credentials
                                    )
                                    identity = verification.get("identity", {})
                                    if identity.get("id"):
                                        credentials["cloud_id"] = identity["id"]
                            else:
                                credentials = vault.decrypt(active_tool.encrypted_credentials)
                            if (
                                active_tool.kind.value == "oauth"
                                and active_tool.config.get("managed_by")
                                not in {"nango", "pipedream"}
                            ):
                                credentials, changed = await refresh_oauth_credentials(
                                    get_settings(),
                                    active_tool.slug,
                                    credentials,
                                    active_tool.config,
                                )
                                if changed:
                                    active_tool.encrypted_credentials = vault.encrypt(credentials)
                                    await audit(
                                        session,
                                        workspace_id,
                                        "connector.token_refreshed",
                                        {"tool_id": active_tool.id, "slug": active_tool.slug},
                                        run.id,
                                    )
                            current_manifest = runtime_manifest
                            provider_timeout = float(
                                snapshot.policy_snapshot[
                                    "gateway_timeout_seconds"
                                    if active_tool.kind.value == "mcp"
                                    else "step_timeout_seconds"
                                ]
                            )
                            if (active_tool.config or {}).get("managed_by") == "agent_gateway":
                                provider_timeout = min(
                                    provider_timeout,
                                    float(
                                        (current_manifest.get("limits") or {}).get(
                                            "max_runtime_seconds", provider_timeout
                                        )
                                    ),
                                )
                            executor = ProviderExecutor(
                                credentials,
                                active_tool.base_url,
                                timeout_seconds=provider_timeout,
                                provider_kind=active_tool.kind.value,
                                capability_manifest=current_manifest,
                            )
                            # Connector coercion and schema validation are local
                            # preparation. Complete them before crossing the
                            # durable provider-dispatch boundary so AURA can
                            # repair deterministic contract failures itself.
                            arguments, _ = _prepare_provider_arguments(
                                current_manifest, operation, arguments
                            )
                            confirm_provider_arguments(arguments)
                            await mark_provider_dispatched()
                            result = await asyncio.wait_for(
                                executor.execute(operation, arguments),
                                timeout=execution_timeout,
                            )
                        if _provider_result_is_malformed(result):
                            raise ValueError("Provider returned an empty or malformed response")
                        latency = (time.perf_counter() - started) * 1000
                        attempt.status = "succeeded"
                        attempt.latency_ms = latency
                        attempt.completed_at = datetime.now(UTC)
                        _update_trust(
                            active_trust,
                            succeeded=True,
                            timed_out=False,
                            latency_ms=latency,
                        )
                        step.output = {
                            "step_id": step.id,
                            "provider_result": result,
                            "tool": active_tool.slug,
                            "operation": operation,
                            "resolved_arguments": arguments,
                            "critic": {"action": "escalate", "reasons": ["Review pending"]},
                        }
                        # Fallback identity must survive the same crash boundary as its receipt.
                        step.tool_slug = active_tool.slug
                        step.operation = operation
                        await session.commit()
                        return result, None
                    except TimeoutError as exc:
                        failure = classify_failure(
                            exc,
                            read=not consequential or not attempt.provider_dispatched,
                        )
                        timed_out = True
                        last_error = "Step timed out"
                        failure_impacts_trust = _failure_impacts_trust(exc)
                        logger.exception(
                            "Workflow step timed out run_id=%s step_id=%s tool=%s operation=%s",
                            run.id,
                            step.id,
                            active_tool.slug,
                            operation,
                        )
                    except Exception as exc:
                        failure = classify_failure(
                            exc,
                            read=not consequential or not attempt.provider_dispatched,
                        )
                        last_error = _provider_rejection_detail(exc) or str(exc)
                        failure_impacts_trust = _failure_impacts_trust(exc)
                        logger.exception(
                            "Workflow step failed run_id=%s step_id=%s tool=%s operation=%s error_type=%s",
                            run.id,
                            step.id,
                            active_tool.slug,
                            operation,
                            type(exc).__name__,
                        )
                    latency = (time.perf_counter() - started) * 1000
                    attempt.status = "failed"
                    last_error = f"[{failure.category}] {last_error}"
                    attempt.error = last_error
                    attempt.latency_ms = latency
                    attempt.completed_at = datetime.now(UTC)
                    if failure_impacts_trust:
                        _update_trust(
                            active_trust,
                            succeeded=False,
                            timed_out=timed_out,
                            latency_ms=latency,
                        )
                    await session.commit()
                    if not failure.retryable:
                        break
                    retry_after = failure.retry_after
                return None, last_error

            approved_step = plan_steps[step.position]

            async def delegated_call(
                active_tool: ToolConnection,
                operation: str,
                arguments: dict,
                step: RunStep = step,
                approved_step: dict = approved_step,
            ) -> tuple[dict | None, str | None]:
                delegation = delegations.get(step.step_key)
                execution_agent = (
                    delegation.execution_agent
                    if delegation
                    else f"{active_tool.slug.replace('-', ' ').title()} Execution Agent"
                )
                directive, directive_source = await prepare_execution_directive(
                    run.prompt,
                    {
                        **approved_step,
                        "key": step.step_key,
                        "tool_slug": active_tool.slug,
                        "operation": operation,
                    },
                    arguments,
                    execution_agent,
                )
                await audit(
                    session,
                    workspace_id,
                    "step.execution_agent_decision",
                    {
                        "step_id": step.id,
                        "agent": execution_agent,
                        "action": directive.action,
                        "reason": directive.reason,
                        "source": directive_source,
                        "tool_slug": active_tool.slug,
                        "operation": operation,
                    },
                    run.id,
                    actor=execution_agent,
                )
                if directive.action != "execute":
                    return None, f"[execution_agent_escalated] {directive.reason}"
                return await call(
                    active_tool,
                    directive.operation,
                    directive.arguments,
                )

            result, error = await delegated_call(tool, step.operation, resolved_arguments)
            if (
                not error
                and result is not None
                and _has_empty_collection(result)
                and approved_step.get("reduced_scope_arguments") is not None
            ):
                error = "The narrow read returned no matching items"
            fallback_slug = approved_step.get("fallback_tool_slug")
            fallback_operation = approved_step.get("fallback_operation")
            recovery_blocked_prefixes = (
                "[authorization_required]",
                "[uncertain_write]",
                "[budget_exhausted]",
                "[invalid_request]",
                "[contract_or_runtime_error]",
                "[execution_agent_escalated]",
            )
            recovery_blocked = bool(error and error.startswith(recovery_blocked_prefixes))
            if error and not recovery_blocked and fallback_slug and fallback_operation:
                fallback = await session.scalar(
                    select(ToolConnection).where(
                        ToolConnection.workspace_id == workspace_id,
                        ToolConnection.slug == fallback_slug,
                        ToolConnection.enabled.is_(True),
                    )
                )
                fallback_trust = (
                    await _trust_state(session, workspace_id, fallback) if fallback else None
                )
                fallback_allowed = (
                    fallback
                    and fallback_operation in fallback.allowed_operations
                    and fallback_operation in snapshot.permission_snapshot.get(fallback.slug, [])
                    and fallback_trust.score
                    >= float(snapshot.policy_snapshot["trust_execution_floor"])
                    and operation_scope(fallback_operation) == operation_scope(step.operation)
                    and operation_scope(fallback_operation) == "read"
                )
                if fallback_allowed:
                    await audit(
                        session,
                        workspace_id,
                        "step.fallback_started",
                        {
                            "step_id": step.id,
                            "from_tool": tool.slug,
                            "to_tool": fallback.slug,
                        },
                        run.id,
                    )
                    result, error = await delegated_call(
                        fallback, fallback_operation, resolved_arguments
                    )
                    if not error:
                        step.tool_slug = fallback.slug
                        step.operation = fallback_operation
                        step.idempotency_key = idempotency_key(
                            run.id,
                            step.position,
                            fallback_operation,
                            resolved_arguments,
                        )

            recovery_blocked = bool(error and error.startswith(recovery_blocked_prefixes))

            reduced_arguments = approved_step.get("reduced_scope_arguments")
            if (
                error
                and not recovery_blocked
                and reduced_arguments is not None
                and operation_scope(step.operation) == "read"
                and reduced_arguments != step.arguments
            ):
                await audit(
                    session,
                    workspace_id,
                    "step.reduced_scope_started",
                    {"step_id": step.id},
                    run.id,
                )
                resolved_reduced_arguments = resolve_value(reduced_arguments, context)
                capability = next(
                    (
                        m
                        for m in _current_capability_manifest(tool.slug, None).get(
                            "capabilities", []
                        )
                        if m.get("name") == step.operation
                    ),
                    {},
                )
                for key, schema in capability.get("input_schema", {}).get("properties", {}).items():
                    if schema.get("x-preserve-on-recovery") and key in resolved_arguments:
                        resolved_reduced_arguments[key] = resolved_arguments[key]
                result, error = await delegated_call(
                    tool, step.operation, resolved_reduced_arguments
                )
                if not error:
                    resolved_arguments = resolved_reduced_arguments
                    step.idempotency_key = idempotency_key(
                        run.id, step.position, step.operation, resolved_reduced_arguments
                    )

            if error or result is None:
                step.status = StepStatus.failed
                internal_error = error or "Tool execution failed"
                step.error = _friendly_execution_error(internal_error)
                target_status = (
                    RunStatus.cancelled
                    if run.cancellation_requested
                    else RunStatus.waiting_for_action
                )
                transition_run(
                    run,
                    target_status,
                    reason=(
                        "cancellation_observed_after_attempt"
                        if run.cancellation_requested
                        else "step_recovery_exhausted"
                    ),
                    actor="senior-orchestrator",
                    phase="execution",
                    supervisor_status=("cancelled" if run.cancellation_requested else "recovering"),
                    error=step.error,
                    result=_partial_result(outputs, step, step.error),
                    dispatch=None,
                    metadata={"step_id": step.id},
                )
                attempts = (
                    await session.scalars(select(StepAttempt).where(StepAttempt.step_id == step.id))
                ).all()
                if not run.cancellation_requested:
                    existing_dead_letter = await session.scalar(
                        select(DeadLetterEntry).where(
                            DeadLetterEntry.run_id == run.id,
                            DeadLetterEntry.step_id == step.id,
                        )
                    )
                    if not existing_dead_letter:
                        session.add(
                            DeadLetterEntry(
                                workspace_id=workspace_id,
                                run_id=run.id,
                                step_id=step.id,
                                error=internal_error,
                                attempt_count=len(attempts),
                                payload={
                                    "tool_slug": step.tool_slug,
                                    "operation": step.operation,
                                    "arguments": resolved_arguments,
                                },
                            )
                        )
                await audit(
                    session,
                    workspace_id,
                    "step.recovery_exhausted",
                    {"step_id": step.id, "internal_error": internal_error},
                    run.id,
                )
                await session.commit()
                return

            contract = {
                "step_id": step.id,
                "agent": step.agent,
                "tool_slug": step.tool_slug,
                "operation": step.operation,
                "arguments": resolved_arguments,
                "expected_output": approved_step.get("expected_output", ""),
                "required_evidence": approved_step.get("required_evidence", []),
                "consequential": step.consequential,
            }
            criticism = await review_recorded_result(session, run, step, snapshot, contract, result)
            await audit(
                session,
                workspace_id,
                "step.criticized",
                {"step_id": step.id, "decision": criticism.model_dump(mode="json")},
                run.id,
                actor="tool-output-critic",
            )
            if criticism.action != "accept":
                from .verification_recovery import defer_verification

                if await defer_verification(session, run, step):
                    return
                internal_error = f"Runtime critic {criticism.action}: " + "; ".join(
                    criticism.reasons + criticism.contract_failures + criticism.policy_violations
                )
                logger.error(
                    "Workflow output rejected run_id=%s step_id=%s detail=%s",
                    run.id,
                    step.id,
                    internal_error,
                )
                step.output = {**step.output, "critic": criticism.model_dump(mode="json")}
                step.status = StepStatus.failed
                step.error = "Provider result was recorded but did not pass review."
                transition_run(
                    run,
                    RunStatus.waiting_for_action,
                    reason="provider_result_review_rejected",
                    actor="tool-output-critic",
                    phase="verification",
                    supervisor_status="recovering",
                    error=step.error,
                    result=_partial_result(outputs, step, step.error),
                    dispatch=None,
                    metadata={"step_id": step.id},
                )
                await session.commit()
                return

            step.status = StepStatus.completed
            step.output = {
                "step_id": step.id,
                "step_key": step.step_key,
                "provider_result": result,
                "resolved_arguments": resolved_arguments,
                "tool": step.tool_slug,
                "operation": step.operation,
                "critic": criticism.model_dump(mode="json"),
                "outcome_check": step.output.get("outcome_check", {"status": "unsupported"}),
            }
            step.completed_at = datetime.now(UTC)
            run.updated_at = step.completed_at
            outputs.append(step.output)
            context.setdefault("steps", {})[step.step_key] = step_context_value(
                result, step.operation
            )
            try:
                for name, value in step.output_variables.items():
                    context.setdefault("vars", {})[name] = resolve_value(value, context)
            except WorkflowContextError as exc:
                internal_error = str(exc)
                logger.exception(
                    "Workflow output mapping failed run_id=%s step_id=%s",
                    run.id,
                    step.id,
                )
                await audit(
                    session,
                    workspace_id,
                    "step.output_mapping_failed",
                    {"step_id": step.id, "internal_error": internal_error},
                    run.id,
                )
                if step.consequential:
                    # Output bookkeeping is internal and happens after the
                    # external write. Preserve the confirmed result and never
                    # replay the write merely to repair a missing alias.
                    logger.warning(
                        "Preserving completed consequential step after output "
                        "mapping failure run_id=%s step_id=%s",
                        run.id,
                        step.id,
                    )
                else:
                    run.execution_context = deepcopy(context)
                    step.status = StepStatus.failed
                    step.error = _friendly_execution_error(internal_error)
                    transition_run(
                        run,
                        RunStatus.waiting_for_action,
                        reason="step_output_mapping_failed",
                        actor="recovery-engineer",
                        phase="execution",
                        supervisor_status="recovering",
                        error=step.error,
                        result=_partial_result(outputs, step, step.error),
                        dispatch=None,
                        metadata={"step_id": step.id},
                    )
                    await session.commit()
                    return
            run.execution_context = deepcopy(context)
            await mark_recovery_checkpoint_succeeded(session, run, step)
            session.add(
                Artifact(
                    workspace_id=workspace_id,
                    run_id=run.id,
                    step_id=step.id,
                    accepted=True,
                    provenance={
                        "tool": step.tool_slug,
                        "operation": step.operation,
                        "plan_hash": snapshot.plan_hash,
                    },
                    content=step.output,
                )
            )
            await audit(
                session,
                workspace_id,
                "step.completed",
                {"step_id": step.id, "evidence": step.output},
                run.id,
            )
            await session.commit()
            from .recovery_probe import yield_after_checkpoint

            if await yield_after_checkpoint(session, run, step):
                return

        required_incomplete = [
            step
            for step, approved in zip(steps, plan_steps, strict=True)
            if not approved.get("optional", False) and step.status != StepStatus.completed
        ]
        if required_incomplete:
            message = (
                "AURA couldn't complete every required step after trying the safe "
                "recovery options. No completed work was repeated."
            )
            incomplete_result = {
                "partial": bool(outputs),
                "completed_steps": len(outputs),
                "outputs": outputs,
                "incomplete_steps": [step.step_key for step in required_incomplete],
            }
            transition_run(
                run,
                RunStatus.failed,
                reason="required_steps_incomplete",
                actor="senior-orchestrator",
                phase="execution",
                supervisor_status="recovering",
                error=message,
                result=incomplete_result,
                dispatch=None,
                metadata={"incomplete_steps": [step.step_key for step in required_incomplete]},
            )
            logger.error(
                "Workflow incomplete run_id=%s required_steps=%s statuses=%s",
                run.id,
                [step.step_key for step in required_incomplete],
                {step.step_key: step.status.value for step in steps},
            )
            await audit(
                session,
                workspace_id,
                "run.required_steps_incomplete",
                {
                    "completed_steps": len(outputs),
                    "incomplete_steps": [step.step_key for step in required_incomplete],
                },
                run.id,
            )
            await session.commit()
            return

        outcome_failures = []
        for step in steps:
            if step.status != StepStatus.completed:
                continue
            check = step.output.get("outcome_check", {})
            if check.get("status") != "verified":
                check = await check_provider_outcome(session, run, step, snapshot)
                step.output = {**step.output, "outcome_check": check}
                await session.commit()
            if check.get("status") not in {"verified", "unsupported"}:
                outcome_failures.append(step.step_key)
        outputs = [step.output for step in steps if step.status == StepStatus.completed]
        outputs_by_step = {
            step.step_key: step.output
            for step in steps
            if step.status == StepStatus.completed
        }
        try:
            result_presentation = resolve_result_presentation(
                run.plan,
                outputs_by_step,
            )
        except Exception:
            logger.exception("Could not resolve result presentation run_id=%s", run.id)
            result_presentation = {
                "version": 1,
                "source": "safe_fallback",
                "metrics": [],
                "supporting_step_keys": [],
            }
        synthesis = None
        if outcome_failures:
            verification = OutcomeVerification(
                status="unverified",
                reasons=["Provider read-back could not confirm: " + ", ".join(outcome_failures)],
            )
        else:
            review_started = time.perf_counter()
            try:
                prepared_evidence, evidence_cache, cache_hit = await prepare_final_review(
                    run.prompt,
                    run.plan,
                    outputs,
                    (run.execution_context or {}).get("final_review_evidence"),
                )
            except Exception as exc:  # noqa: BLE001 - preserve completed work across final-review outages
                logger.warning(
                    "Final evidence preparation unavailable run_id=%s error_type=%s",
                    run.id,
                    type(exc).__name__,
                )
                message = (
                    "Delivery results are saved. Final review is temporarily unavailable; "
                    "completed actions will not repeat."
                )
                transition_run(
                    run,
                    RunStatus.waiting_for_action,
                    reason="final_evidence_preparation_unavailable",
                    actor="outcome-verifier",
                    phase="verification",
                    supervisor_status="recovering",
                    error=message,
                    result={
                        "partial": True,
                        "completed_steps": len(outputs),
                        "outputs": outputs,
                        "result_presentation": result_presentation,
                        "verification": {
                            "status": "unverified",
                            "reasons": ["Final evidence preparation unavailable"],
                        },
                    },
                    dispatch=None,
                )
                await session.commit()
                return
            preparation_ms = round((time.perf_counter() - review_started) * 1000)
            run.execution_context = {
                **(run.execution_context or {}),
                "final_review_evidence": evidence_cache,
            }
            await session.commit()
            synthesis = await synthesize_result(run.prompt, outputs, prepared_evidence)
            if not synthesis.validation_passed:
                verification = OutcomeVerification(
                    status="unverified",
                    reasons=["Final response did not pass validation"],
                    required_fixes=synthesis.required_fixes,
                )
                await audit(
                    session,
                    workspace_id,
                    "run.synthesis_rejected",
                    {"required_fixes": synthesis.required_fixes},
                    run.id,
                    actor="tool-output-critic",
                )
            else:
                verification = await verify_outcome(
                    run.prompt,
                    run.plan,
                    outputs,
                    synthesis.model_dump(mode="json"),
                    prepared_evidence,
                )
            await audit(
                session,
                workspace_id,
                "run.final_review_metrics",
                {
                    "preparation_ms": preparation_ms,
                    "evidence_cache_hit": cache_hit,
                    "total_ms": round((time.perf_counter() - review_started) * 1000),
                    "status": verification.status,
                },
                run.id,
            )
        verification_data = verification.model_dump(mode="json")
        await audit(
            session,
            workspace_id,
            "run.outcome_verified",
            verification_data,
            run.id,
            actor="outcome-verifier",
        )
        run.result = {
            "partial": verification.status != "verified",
            "completed_steps": len(outputs),
            "outputs": outputs,
            "result_presentation": result_presentation,
            "verification": verification_data,
        }
        if synthesis is not None:
            run.result["unified_deliverable"] = synthesis.model_dump(mode="json")
        if verification.status != "verified":
            logger.warning(
                "Workflow final verification unresolved run_id=%s status=%s reasons=%s fixes=%s",
                run.id,
                verification.status,
                verification.reasons,
                verification.required_fixes,
            )
            transition_run(
                run,
                RunStatus.waiting_for_action,
                reason="final_outcome_not_verified",
                actor="outcome-verifier",
                phase="verification",
                supervisor_status="recovering",
                error=(
                    "The requested outcome is not yet verified. Recorded actions "
                    "will not be replayed."
                ),
                result=run.result,
                dispatch=None,
            )
            await session.commit()
            return
        completed_result = {
            "partial": False,
            "completed_steps": len(outputs),
            "outputs": outputs,
            "result_presentation": result_presentation,
            "unified_deliverable": synthesis.model_dump(mode="json"),
            "verification": verification_data,
        }
        transition_run(
            run,
            RunStatus.completed,
            reason="verified_completion",
            actor="outcome-verifier",
            phase="delivery",
            supervisor_status="completed",
            error=None,
            result=completed_result,
            blocker=None,
        )
        await audit(session, workspace_id, "run.completed", run.result, run.id)
        await session.commit()
        # Completion atomically enqueues memory indexing off the response path.
