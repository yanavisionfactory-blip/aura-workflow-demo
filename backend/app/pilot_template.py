"""A bounded, model-free four-app pilot built from exact user supplied fields."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .schemas import WorkflowPlan

PILOT_PREFIX = "AURA_PILOT_V1\n"
PILOT_OPERATIONS = (
    "docs.create",
    "calendar.create",
    "canva.presentation.create",
    "canva.export.create",
    "gmail.send",
)
PILOT_PROVIDERS = {operation: ("canva" if operation.startswith("canva.") else "google")
                   for operation in PILOT_OPERATIONS}
PILOT_READBACKS = {
    "docs.create": "docs.get", "calendar.create": "calendar.get",
    "canva.presentation.create": "canva.import.get",
    "canva.export.create": "canva.export.get", "gmail.send": "gmail.get",
}


class PilotInputError(ValueError):
    """The exact pilot request needs correction before any provider action."""


class PilotFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_title: str = Field(min_length=1, max_length=80)
    doc_body: str = Field(min_length=1, max_length=4000)
    event_title: str = Field(min_length=1, max_length=80)
    event_start: datetime
    event_end: datetime
    canva_title: str = Field(min_length=1, max_length=50)
    canva_bullets: list[str] = Field(min_length=1, max_length=5)
    email_to: Literal["me"]
    illustrated_poem: bool = False


def _poem_phases(body: str) -> list[dict]:
    stanzas = [stanza.strip().splitlines() for stanza in body.strip().split("\n\n")]
    if (len(stanzas) != 3 or any(len(lines) < 3 or len(lines) > 4 for lines in stanzas)
            or any(not line.strip() or len(line) > 90 for lines in stanzas for line in lines)):
        raise PilotInputError(
            "The illustrated poem needs exactly three verses of three or four short lines each."
        )
    scenes = ("rain_window", "paper_boat", "lantern")
    titles = ("First light", "A small voyage", "Carry the light")
    return [
        {"period": f"Verse {index + 1}", "title": titles[index],
         "items": [line.strip() for line in lines], "scene": scenes[index]}
        for index, lines in enumerate(stanzas)
    ]


def _owner(inventory: list[dict], operation: str) -> dict | None:
    # This bounded pilot uses the audited native connector contracts. A second
    # marketplace integration must not silently change the selected account.
    matches = [item for item in inventory if item.get("slug") == PILOT_PROVIDERS[operation]]
    if len(matches) != 1:
        return None
    item = matches[0]
    granted = set(item.get("allowed_operations") or [])
    return {**item, "connected": bool(item.get("connected")
                                   and {operation, PILOT_READBACKS[operation]} <= granted)}


def pilot_template(prompt: str, inventory: list[dict]) -> WorkflowPlan | None:
    """Use only literal fields and unique owners; never infer a recipient or event time."""
    if not prompt.startswith(PILOT_PREFIX):
        return None
    try:
        fields = PilotFields.model_validate(json.loads(prompt[len(PILOT_PREFIX):]))
    except (ValueError, ValidationError) as exc:
        raise PilotInputError("Check the pilot fields and try again; no action was run.") from exc
    start, end = fields.event_start, fields.event_end
    if (start.tzinfo is None or end.tzinfo is None
            or start.utcoffset() is None or end.utcoffset() is None):
        raise PilotInputError("Include an explicit time zone offset for both event times.")
    now = datetime.now(UTC)
    if not now < start.astimezone(UTC) < end.astimezone(UTC) <= now + timedelta(days=30):
        raise PilotInputError("Choose a future event within 30 days, with an end after its start.")
    if end - start > timedelta(hours=4):
        raise PilotInputError("Keep the pilot event to four hours or less.")
    if not all(value.strip() for value in (fields.doc_title, fields.doc_body,
                                           fields.event_title, fields.canva_title)) or any(
        not bullet.strip() or len(bullet) > 90 for bullet in fields.canva_bullets
    ):
        raise PilotInputError("Provide titles, document text, and one to five Canva bullets of at most 90 characters.")

    operations = {op: _owner(inventory, op) for op in PILOT_OPERATIONS}
    if any(owner is None for owner in operations.values()):
        raise PilotInputError(
            "The pilot needs the native Google and Canva connections. Connect both accounts and try again."
        )
    slug = {op: str(operations[op]["slug"]) for op in PILOT_OPERATIONS}
    phases = (
        _poem_phases(fields.doc_body) if fields.illustrated_poem
        else [{"period": "Pilot", "title": "Pilot briefing", "items": fields.canva_bullets}]
    )
    delivery_body = (
        f"{fields.doc_title}\n\n{fields.doc_body}\n\n"
        "The illustrated Canva PDF is attached. The same poem was created in Google Docs, "
        f"and its presentation is scheduled as '{fields.event_title}'."
        if fields.illustrated_poem else (
            f"The pilot Google Doc '{fields.doc_title}' and calendar event "
            f"'{fields.event_title}' are ready. The Canva PDF is attached."
        )
    )
    steps = [
        {
            "key": "create_doc", "agent": "Google Docs Agent",
            "tool_slug": slug["docs.create"], "operation": "docs.create",
            "arguments": {"title": fields.doc_title, "body": fields.doc_body},
            "reason": "Write the complete poem in Google Docs." if fields.illustrated_poem
            else "Create the exact pilot document you supplied.",
            "expected_output": "Verified Google Doc identity and text.",
            "consequential": True, "required_evidence": ["write_receipt"],
        },
        {
            "key": "create_event", "agent": "Google Calendar Agent",
            "tool_slug": slug["calendar.create"], "operation": "calendar.create",
            "arguments": {
                "title": fields.event_title,
                "description": f"AURA pilot: {fields.doc_title}",
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
            "reason": (
                f"Schedule '{fields.event_title}' for "
                f"{start:%a %d %b %Y, %I:%M %p UTC%z} to "
                f"{end:%I:%M %p UTC%z}."
            ),
            "expected_output": "Verified calendar event and time.",
            "consequential": True, "depends_on": ["create_doc"],
            "required_evidence": ["write_receipt"],
        },
        {
            "key": "create_canva", "agent": "Canva Presentation Agent",
            "tool_slug": slug["canva.presentation.create"],
            "operation": "canva.presentation.create",
            "arguments": {
                "title": fields.canva_title, "layout": "slides",
                "phases": phases,
            },
            "reason": "Illustrate all three verses in Canva." if fields.illustrated_poem
            else "Create a populated Canva slide from the exact bullets you supplied.",
            "expected_output": "Verified three-page illustrated Canva design." if fields.illustrated_poem
            else "Verified populated Canva design.",
            "consequential": True, "depends_on": ["create_event"],
            "required_evidence": ["dispatch_receipt", "populated_presentation"],
        },
        {
            "key": "export_canva", "agent": "Canva Presentation Agent",
            "tool_slug": slug["canva.export.create"],
            "operation": "canva.export.create",
            "arguments": {"design_id": "{{steps.create_canva.job.id}}", "format": "pdf"},
            "reason": "Export the verified design as the email attachment.",
            "expected_output": "Verified Canva PDF export URL.",
            "consequential": False, "depends_on": ["create_canva"],
            "required_evidence": ["dispatch_receipt"],
        },
        {
            "key": "send_email", "agent": "Gmail Delivery Agent",
            "tool_slug": slug["gmail.send"], "operation": "gmail.send",
            "arguments": {
                "to": "me", "subject": f"{fields.doc_title} — poem and illustrations"
                if fields.illustrated_poem else f"AURA pilot: {fields.doc_title}",
                "body": delivery_body,
                "attachments": [{"filename": "Illustrated poem.pdf" if fields.illustrated_poem
                                 else "AURA pilot.pdf",
                                 "url": "{{steps.export_canva.job.urls[0]}}"}],
            },
            "reason": "Email the poem and illustrated PDF to your connected Gmail account."
            if fields.illustrated_poem else "Email the verified Canva PDF to your connected Gmail account.",
            "expected_output": "Verified Gmail delivery with the PDF attached.",
            "consequential": True, "depends_on": ["export_canva"],
            "required_evidence": ["write_receipt"],
        },
    ]
    plan = WorkflowPlan.model_validate({
        "name": "Poem and illustrations pilot" if fields.illustrated_poem else "AURA four-app pilot",
        "interpretation": (
            "Write the poem in Google Docs, illustrate its three verses in Canva, "
            "email the poem and PDF to your connected Gmail account, and schedule its presentation."
            if fields.illustrated_poem else
            "Create the supplied Google Doc, calendar event, and Canva slide, "
            "then send the verified PDF to your connected Gmail account."
        ),
        "steps": steps,
        "result_contract": {
            "primary_step_key": "send_email", "completion_step_key": "send_email",
            "artifact_step_key": "create_canva",
            "supporting_step_keys": ["create_doc", "create_event", "create_canva", "export_canva"],
        },
    })
    missing = list(dict.fromkeys(
        slug[op] for op in PILOT_OPERATIONS if not operations[op].get("connected", True)
    ))
    plan.planning_artifacts = {
        "planner_recovery_mode": "audited_four_app_pilot_v1",
        "connection_requirements": missing,
        "objective_spec": {
            "goal": "Complete the exact four-app pilot request.",
            "deliverables": ["Google Doc", "Calendar event", "Canva PDF", "Gmail message to self"],
            "constraints": ["No inferred recipients, dates, or presentation content",
                            "Review every consequential action before dispatch"],
            "success_metrics": ["All five operations have matching provider read-back receipts"],
            "required_inputs": [],
        },
        "toolset_proposal": {
            "tools": [{"slug": value, "role": operation} for operation, value in slug.items()],
            "missing_capabilities": missing,
        },
        "preflight_evaluation": {"passed": True, "estimated_risk": "medium",
                                  "risk_score": 0.4, "permission_scope": "write"},
        "architecture": ["document", "event", "slide", "export", "email", "read-back"],
        "senior_orchestrator": {"action": "approve", "reason": "Bounded pilot input and contracts passed",
                                "source": "audited_template"},
        "timings_ms": {"model": 0, "repair": 0, "total": 0},
    }
    return plan
