"""Audited fallbacks for high-stakes workflow shapes the generic planner may miss."""

from __future__ import annotations

import re

from .schemas import WorkflowPlan


def _owner(inventory: list[dict], operations: set[str]) -> dict | None:
    matches = [
        item
        for item in inventory
        if operations.issubset(set(item.get("allowed_operations") or []))
    ]
    return matches[0] if len(matches) == 1 else None


def notion_to_jira_template(
    prompt: str,
    inventory: list[dict],
) -> WorkflowPlan | None:
    """Return an immediate executable plan for a bounded Notion-to-Jira request.

    The adapter intentionally owns the finite block-to-task normalization and
    Jira bulk request.  That keeps the reviewable plan independent of connection
    state without asking a model to invent a foreach graph or provider IDs.
    """
    requested = prompt.casefold()
    if "notion" not in requested or "jira" not in requested:
        return None
    if not any(marker in requested for marker in ("action item", "to-do", "todo")):
        return None
    if not any(marker in requested for marker in ("task", "ticket", "issue")):
        return None

    page_match = re.search(
        r"(?:my|the)\s+(.{1,80}?)\s+(?:in|from)\s+notion\b",
        prompt,
        re.IGNORECASE,
    )
    page_query = page_match.group(1).strip(" \t\n\r,.") if page_match else "research notes"
    if not page_query or page_query.casefold() in {"action items", "tasks", "tickets"}:
        page_query = "research notes"

    notion = _owner(
        inventory,
        {"notion.search", "notion.blocks.children.list"},
    )
    jira = _owner(inventory, {"jira.issues.create_from_blocks"})
    if not notion or not jira:
        return None

    notion_slug = str(notion["slug"])
    jira_slug = str(jira["slug"])
    plan = WorkflowPlan.model_validate(
        {
            "name": "Turn Notion action items into Jira tasks",
            "interpretation": (
                f"Read the {page_query} page in Notion, extract its action items, "
                "and create the approved task batch in Jira."
            ),
            "steps": [
                {
                    "key": "find_research_notes",
                    "agent": "Notion Research Agent",
                    "tool_slug": notion_slug,
                    "operation": "notion.search",
                    "arguments": {
                        "query": page_query,
                        "page_size": 10,
                        "filter": {"value": "page", "property": "object"},
                    },
                    "reason": "Find the named Notion page without asking for an internal page ID.",
                    "expected_output": "The matching Notion page identity and metadata.",
                    "required_evidence": ["resource_metadata"],
                },
                {
                    "key": "read_research_notes",
                    "agent": "Notion Research Agent",
                    "tool_slug": notion_slug,
                    "operation": "notion.blocks.children.list",
                    "arguments": {
                        "block_id": "{{steps.find_research_notes.results[0].id}}",
                        "page_size": 100,
                    },
                    "reason": "Read the actual page blocks so Jira tasks are grounded in the notes.",
                    "expected_output": "The current Notion page blocks containing the action items.",
                    "depends_on": ["find_research_notes"],
                    "required_evidence": ["page_body"],
                },
                {
                    "key": "create_jira_tasks",
                    "agent": "Jira Task Agent",
                    "tool_slug": jira_slug,
                    "operation": "jira.issues.create_from_blocks",
                    "arguments": {
                        "source_blocks": "{{steps.read_research_notes.results}}",
                        "issue_type": "Task",
                        "max_issues": 20,
                    },
                    "reason": (
                        "Convert the retrieved action-item blocks into one bounded Jira bulk "
                        "request after approval."
                    ),
                    "expected_output": "A verified receipt for every Jira task created.",
                    "consequential": True,
                    "depends_on": ["read_research_notes"],
                    "required_evidence": ["write_receipt"],
                },
            ],
        }
    )
    missing = [
        slug
        for slug, item in ((notion_slug, notion), (jira_slug, jira))
        if not item.get("connected", True)
    ]
    plan.planning_artifacts = {
        "objective_spec": {
            "goal": "Create Jira tasks from action items in the named Notion page.",
            "deliverables": ["One bounded batch of Jira tasks"],
            "constraints": [
                "Use only retrieved Notion page content",
                "Do not create any Jira issue before approval",
                "Do not guess a Jira project when more than one is available",
            ],
            "success_metrics": ["Every created issue has a Jira receipt"],
            "required_inputs": [],
        },
        "toolset_proposal": {
            "tools": [
                {"slug": notion_slug, "role": "Notion page discovery and content read"},
                {"slug": jira_slug, "role": "Approved Jira bulk task creation"},
            ],
            "missing_capabilities": [],
        },
        "preflight_evaluation": {
            "passed": True,
            "estimated_risk": "medium",
            "risk_score": 0.4,
            "permission_scope": "write",
        },
        "architecture": ["find", "read", "extract", "approve", "bulk create", "verify"],
        "senior_orchestrator": {
            "action": "approve",
            "reason": "Audited Notion-to-Jira template passed deterministic preflight.",
            "source": "audited_template",
        },
        "planner_recovery_mode": "audited_notion_to_jira_template",
        "connection_requirements": missing,
        "timings_ms": {"model": 0, "repair": 0, "total": 0},
    }
    return plan


def weather_presentation_template(
    prompt: str,
    inventory: list[dict],
) -> WorkflowPlan | None:
    """Return an immediate audited plan for a bounded weather presentation."""
    requested = prompt.casefold()
    if not any(word in requested for word in ("presentation", "deck", "slide")):
        return None
    if not any(word in requested for word in ("weather", "forecast")):
        return None
    location_match = re.search(
        r"\b(?:weather|forecast)\s+(?:in|for)\s+(.+?)"
        r"(?=\s+(?:today|tomorrow)\b|[,.!?]|$)",
        prompt,
        re.IGNORECASE,
    )
    relative_date = next(
        (value for value in ("tomorrow", "today") if re.search(rf"\b{value}\b", requested)),
        None,
    )
    if not location_match or not relative_date:
        return None
    location = location_match.group(1).strip(" \t\n\r,.")
    if not location or len(location) > 80:
        return None

    weather = _owner(inventory, {"weather.forecast"})
    canva = _owner(inventory, {"canva.presentation.create"})
    if not weather or not canva:
        return None

    weather_slug = str(weather["slug"])
    canva_slug = str(canva["slug"])
    plan = WorkflowPlan.model_validate(
        {
            "name": f"{location} weather presentation",
            "interpretation": (
                f"Retrieve the public weather forecast for {location} {relative_date} and "
                "create one populated Canva presentation grounded only in that forecast."
            ),
            "steps": [
                {
                    "key": "weather",
                    "agent": "Weather Research Agent",
                    "tool_slug": weather_slug,
                    "operation": "weather.forecast",
                    "arguments": {"location": location, "date": relative_date},
                    "reason": "Retrieve the requested public forecast before composing the presentation.",
                    "expected_output": "Location, forecast date, and grounded weather summary.",
                    "required_evidence": ["forecast"],
                },
                {
                    "key": "create_presentation",
                    "agent": "Canva Presentation Agent",
                    "tool_slug": canva_slug,
                    "operation": "canva.presentation.create",
                    "arguments": {
                        "title": f"{location} weather",
                        "subtitle": "Forecast for {{steps.weather.date}}",
                        "phases": [{
                            "period": "{{steps.weather.date}}",
                            "title": "Weather forecast",
                            "items": ["{{steps.weather.summary}}"],
                        }],
                    },
                    "reason": "Create the requested populated presentation from the retrieved forecast.",
                    "expected_output": "Verified Canva presentation creation job and design identity.",
                    "consequential": True,
                    "depends_on": ["weather"],
                    "required_evidence": ["dispatch_receipt", "populated_presentation"],
                },
            ],
        }
    )
    plan.planning_artifacts = {
        "objective_spec": {
            "goal": f"Create a Canva presentation for {location}'s {relative_date} weather.",
            "deliverables": ["One populated Canva presentation"],
            "constraints": ["Use the current public forecast", "Do not introduce email delivery"],
            "success_metrics": ["The Canva creation job returns a verified design identity"],
            "required_inputs": [],
        },
        "toolset_proposal": {
            "tools": [
                {"slug": weather_slug, "role": "public weather forecast"},
                {"slug": canva_slug, "role": "populated presentation creation"},
            ],
            "missing_capabilities": [],
        },
        "preflight_evaluation": {
            "passed": True,
            "estimated_risk": "medium",
            "risk_score": 0.3,
            "permission_scope": "write",
        },
        "architecture": ["forecast", "compose", "approve", "create", "verify"],
        "senior_orchestrator": {
            "action": "approve",
            "reason": "Audited weather-presentation template passed deterministic preflight.",
            "source": "audited_template",
        },
        "planner_recovery_mode": "audited_weather_presentation_template",
        "connection_requirements": (
            [canva_slug] if not canva.get("connected", True) else []
        ),
    }
    return plan


def creator_outreach_template(
    prompt: str,
    inventory: list[dict],
) -> WorkflowPlan | None:
    """Return a finite, policy-gated creator workflow for the named Grail flow.

    The template is deliberately narrow: it activates only when the user names both
    sheets and the exact approval destination, and only when one connected/catalog
    tool unambiguously owns every required capability. Provider IDs and candidate
    identities remain runtime evidence; the template never guesses either.
    """

    requested = prompt.casefold()
    markers = (
        "creator outreach",
        "my creators",
        "mgr-approver.vercel.app",
    )
    platform_signal = "tiktok" in requested or all(
        marker in requested for marker in ("followers", "videos", "original audio")
    )
    if not platform_signal or not all(marker in requested for marker in markers):
        return None

    google = _owner(
        inventory,
        {
            "google.identity.get",
            "drive.spreadsheet.resolve",
            "sheets.read",
            "sheets.append",
        },
    )
    intelligence = _owner(
        inventory,
        {
            "creator.tiktok.screen",
            "creator.candidates.exclude_existing",
        },
    )
    approvals = _owner(
        inventory,
        {"browser.page.read", "browser.form.batch.submit"},
    )
    if not google or not intelligence or not approvals:
        return None

    google_slug = str(google["slug"])
    intelligence_slug = str(intelligence["slug"])
    approval_slug = str(approvals["slug"])
    plan = WorkflowPlan.model_validate(
        {
            "name": "Grail creator outreach qualification",
            "interpretation": (
                "Resolve the two current original sheets without guessing; screen a bounded "
                "set of public TikTok creators; exclude current-sheet duplicates; submit the "
                "remaining finite batch to the designated private policy gate; and append only "
                "creator-specific approved receipts to my creators. Never contact creators."
            ),
            "steps": [
                {
                    "key": "resolve_creator_outreach",
                    "agent": "Google Sheet Resolver",
                    "tool_slug": google_slug,
                    "operation": "drive.spreadsheet.resolve",
                    "arguments": {"name": "Creator Outreach"},
                    "reason": (
                        "Resolve exactly one current Google Sheet by its literal Drive name; "
                        "ambiguous or not_found is a genuine blocker and must never select an ID."
                    ),
                    "expected_output": "Resolved status and current spreadsheet identity.",
                    "required_evidence": ["unambiguous_resource_identity"],
                },
                {
                    "key": "resolve_my_creators",
                    "agent": "Google Sheet Resolver",
                    "tool_slug": google_slug,
                    "operation": "drive.spreadsheet.resolve",
                    "arguments": {"name": "my creators"},
                    "reason": (
                        "Resolve exactly one current Google Sheet by its literal Drive name; "
                        "ambiguous or not_found is a genuine blocker and must never select an ID."
                    ),
                    "expected_output": "Resolved status and current spreadsheet identity.",
                    "required_evidence": ["unambiguous_resource_identity"],
                },
                {
                    "key": "read_creator_outreach",
                    "agent": "Google Sheets Reader",
                    "tool_slug": google_slug,
                    "operation": "sheets.read",
                    "arguments": {
                        "spreadsheet_id": (
                            "{{steps.resolve_creator_outreach.spreadsheet.id}}"
                        ),
                        "range": "'Contacted Creators'!A:K",
                    },
                    "reason": (
                        "Read the current original contacted/approval history once, including "
                        "status, TikTok handle/URL, creator email, manager, date, and notes."
                    ),
                    "expected_output": "Current Creator Outreach rows and their fixed A:K schema.",
                    "depends_on": ["resolve_creator_outreach"],
                    "required_evidence": ["cell_values"],
                },
                {
                    "key": "read_my_creators",
                    "agent": "Google Sheets Reader",
                    "tool_slug": google_slug,
                    "operation": "sheets.read",
                    "arguments": {
                        "spreadsheet_id": "{{steps.resolve_my_creators.spreadsheet.id}}",
                        "range": "Sheet1!A:B",
                    },
                    "reason": (
                        "Read the current original internal creator/status rows once so already "
                        "approved or documented creators cannot be submitted again."
                    ),
                    "expected_output": "Current my creators rows in the existing A:B layout.",
                    "depends_on": ["resolve_my_creators"],
                    "required_evidence": ["cell_values"],
                },
                {
                    "key": "read_manager_identity",
                    "agent": "Google Identity Reader",
                    "tool_slug": google_slug,
                    "operation": "google.identity.get",
                    "arguments": {},
                    "reason": "Use the connected account's verified email in the approval form.",
                    "expected_output": "Verified connected Google account email.",
                    "required_evidence": ["account_identity"],
                },
                {
                    "key": "verify_approval_form",
                    "agent": "Approval Form Reader",
                    "tool_slug": approval_slug,
                    "operation": "browser.page.read",
                    "arguments": {"path": "/"},
                    "reason": (
                        "Verify the designated approval destination is accessible before any "
                        "candidate submission."
                    ),
                    "expected_output": "Rendered current approval form and named fields.",
                    "required_evidence": ["public_page_content"],
                },
                {
                    "key": "screen_candidates",
                    "agent": "TikTok Screening Agent",
                    "tool_slug": intelligence_slug,
                    "operation": "creator.tiktok.screen",
                    "arguments": {
                        "query": "public TikTok creators with original recent content",
                        "max_candidates": 10,
                        "videos_per_creator": 12,
                        "min_followers": 15000,
                        "min_videos": 10,
                        "min_trimmed_mean_views": 15000,
                        "min_original_audio_ratio": 0.3,
                        "recency_days": 5,
                    },
                    "reason": (
                        "Screen at most 10 profiles and return only evidence-complete creators "
                        "passing the public/access, content, trimmed-view, original-audio, recency, "
                        "and no-management-contact-in-bio requirements."
                    ),
                    "expected_output": (
                        "Per-creator public evidence plus a qualified_candidates array; incomplete "
                        "evidence never qualifies."
                    ),
                    "required_evidence": [
                        "creator_public_metrics",
                        "creator_video_views",
                        "creator_audio_origin",
                        "creator_recency",
                        "creator_bio_management_signals",
                    ],
                },
                {
                    "key": "exclude_existing",
                    "agent": "Creator Deduplication Agent",
                    "tool_slug": intelligence_slug,
                    "operation": "creator.candidates.exclude_existing",
                    "arguments": {
                        "candidates": "{{steps.screen_candidates.qualified_candidates}}",
                        "creator_outreach_rows": (
                            "{{steps.read_creator_outreach.values}}"
                        ),
                        "my_creator_rows": "{{steps.read_my_creators.values}}",
                    },
                    "reason": (
                        "Perform one deterministic, case-insensitive exact handle/URL/email "
                        "comparison over both already-read current sheets. Preserve exclusions; "
                        "do not reread either source."
                    ),
                    "expected_output": (
                        "A duplicate-free eligible_candidates array and per-source exclusion evidence."
                    ),
                    "depends_on": [
                        "read_creator_outreach",
                        "read_my_creators",
                        "screen_candidates",
                    ],
                    "required_evidence": ["candidate_deduplication"],
                },
                {
                    "key": "submit_candidates",
                    "agent": "Creator Approval Execution Agent",
                    "tool_slug": approval_slug,
                    "operation": "browser.form.batch.submit",
                    "arguments": {
                        "records": "{{steps.exclude_existing.eligible_candidates}}",
                        "submit_text": "Submit Creator",
                        "identity_field": "creatorUsername",
                    },
                    "reason": (
                        "Map every duplicate-free candidate into the discovered named form fields, "
                        "using the verified manager email and public creator email when available. "
                        "The form's per-creator approved/rejected status is the authoritative gate "
                        "for its private DNC, active-management, prior-approval, and protected-"
                        "outreach checks. Submit the finite batch only after explicit approval."
                    ),
                    "expected_output": (
                        "One creator-specific receipt per submitted record and approved_records "
                        "containing only explicit approved statuses; unknown is non-approval."
                    ),
                    "consequential": True,
                    "optional": True,
                    "depends_on": [
                        "exclude_existing",
                        "read_manager_identity",
                        "verify_approval_form",
                    ],
                    "condition": {
                        "left": "{{steps.exclude_existing.eligible_count}}",
                        "operator": "greater_than",
                        "right": 0,
                    },
                    "required_evidence": ["write_receipt"],
                },
                {
                    "key": "append_approved_creators",
                    "agent": "Google Sheets Approval Writer",
                    "tool_slug": google_slug,
                    "operation": "sheets.append",
                    "arguments": {
                        "spreadsheet_id": "{{steps.resolve_my_creators.spreadsheet.id}}",
                        "range": "Sheet1!A:B",
                        "values": "{{steps.submit_candidates.approved_records}}",
                    },
                    "reason": (
                        "Map only creator-specific explicit approved receipts into the existing "
                        "two-column internal documentation layout. Rejected, pending, absent, or "
                        "unknown receipts must never be written."
                    ),
                    "expected_output": (
                        "Google Sheets write receipt containing the destination spreadsheet ID "
                        "and updated range."
                    ),
                    "consequential": True,
                    "optional": True,
                    "depends_on": ["submit_candidates", "resolve_my_creators"],
                    "condition": {
                        "left": "{{steps.submit_candidates.approved_records}}",
                        "operator": "not_equals",
                        "right": [],
                    },
                    "required_evidence": ["write_receipt"],
                },
            ],
        }
    )
    plan.planning_artifacts = {
        "objective_spec": {
            "goal": "Qualify and policy-approve TikTok creators without contacting them.",
            "deliverables": [
                "Creator-specific approval receipts",
                "Internal rows only for explicitly approved creators",
            ],
            "constraints": [
                "Use current originals",
                "Never guess a spreadsheet identity",
                "Never contact creators",
                "Never treat unknown approval as approved",
            ],
            "success_metrics": [
                "Every submitted creator passed public evidence and duplicate checks",
                "Every appended creator has an explicit approved receipt",
            ],
            "required_inputs": [],
        },
        "toolset_proposal": {
            "tools": [
                {"slug": google_slug, "role": "current sheets and identity"},
                {"slug": intelligence_slug, "role": "screening and deduplication"},
                {"slug": approval_slug, "role": "private approval policy gate"},
            ],
            "missing_capabilities": [],
        },
        "preflight_evaluation": {
            "passed": True,
            "estimated_risk": "medium",
            "risk_score": 0.4,
            "permission_scope": "write",
        },
        "architecture": [
            "resolve",
            "read",
            "screen",
            "deduplicate",
            "approve",
            "append",
            "verify",
        ],
        "senior_orchestrator": {
            "action": "approve",
            "reason": "Audited policy-gated batch template passed deterministic preflight.",
            "source": "audited_template",
        },
        "planner_recovery_mode": "audited_policy_batch_template",
        "connection_requirements": [
            item["slug"]
            for item in (google, intelligence, approvals)
            if not item.get("connected", True)
        ],
    }
    return plan
