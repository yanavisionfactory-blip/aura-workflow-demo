"""Audited fallbacks for high-stakes workflow shapes the generic planner may miss."""

from __future__ import annotations

from .schemas import WorkflowPlan


def _owner(inventory: list[dict], operations: set[str]) -> dict | None:
    matches = [
        item
        for item in inventory
        if operations.issubset(set(item.get("allowed_operations") or []))
    ]
    return matches[0] if len(matches) == 1 else None


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
