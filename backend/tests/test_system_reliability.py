"""Release gates for shared contracts, dispatch and bounded failures."""
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import dispatch, process_runtime, scheduler_runtime, worker
from app.db import Base
from app.models import DispatchIntent, RunStatus, WorkflowRun, Workspace
from app.native_connectors import NATIVE_CONNECTORS, native_manifest
from app.operation_contracts import (
    KNOWN,
    canonicalize_requested_evidence,
    compile_contracts,
    enrich_operation,
    output_errors,
)
from app.orchestrator import (
    _normalize_planned_steps,
    _operation_is_consequential,
    _prepare_provider_arguments,
)
from app.reliability import (
    BudgetExceeded,
    CallBudget,
    bounded_model_call,
    classify_failure,
    model_budget,
)
from app.request_contracts import (
    draft_only_email_request,
    missing_requested_operations,
    requested_effects,
    requested_external_operations,
    validate_requested_operations,
)
from app.schemas import PlanStep, WorkflowPlan


@pytest.mark.parametrize("slug", sorted(NATIVE_CONNECTORS))
def test_every_native_operation_has_a_versioned_conformance_contract(slug):
    for module in native_manifest(slug)["capabilities"]:
        Draft202012Validator.check_schema(module["input_schema"])
        Draft202012Validator.check_schema(module["output_schema"])
        assert module["reliability"]["hash"] == enrich_operation(module)["reliability"]["hash"]
        assert module["reliability"]["execution_ready"] is False
        if module["permission_scope"] != "read":
            assert module["reliability"]["retry"]["max_attempts"] == 1


@pytest.mark.parametrize("slug", sorted(NATIVE_CONNECTORS))
def test_every_native_operation_uses_declared_scope_for_runtime_retry_safety(slug):
    for module in native_manifest(slug)["capabilities"]:
        assert _operation_is_consequential(module["name"], module) is (
            module["permission_scope"] != "read"
        )


def test_dynamic_connector_scope_outranks_unfamiliar_or_misleading_names():
    assert _operation_is_consequential(
        "records.mutate", {"permission_scope": "write"}
    )
    assert not _operation_is_consequential(
        "reports.create_preview", {"permission_scope": "read"}
    )


def _valid_schema_value(schema):
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    schema_type = schema.get("type", "object")
    if isinstance(schema_type, list):
        schema_type = next(item for item in schema_type if item != "null")
    if schema_type == "object":
        properties = schema.get("properties", {})
        return {
            name: _valid_schema_value(properties.get(name, {}))
            for name in schema.get("required", [])
        }
    if schema_type == "array":
        return [
            _valid_schema_value(schema.get("items", {}))
            for _ in range(int(schema.get("minItems", 0)))
        ]
    if schema_type == "integer":
        return int(schema.get("minimum", 0))
    if schema_type == "number":
        return float(schema.get("minimum", 0))
    if schema_type == "boolean":
        return True
    if schema.get("format") == "date-time":
        return "2026-09-18T12:00:00Z"
    if schema.get("format") == "email":
        return "aura@example.com"
    if schema.get("format") == "uri":
        return "https://example.com/resource"
    if schema.get("pattern") and "@" in schema["pattern"]:
        return "aura@example.com"
    return "value"


@pytest.mark.parametrize("slug", sorted(NATIVE_CONNECTORS))
def test_every_native_operation_accepts_schema_valid_arguments_before_dispatch(slug):
    manifest = native_manifest(slug)
    for module in manifest["capabilities"]:
        arguments = _valid_schema_value(module["input_schema"])
        prepared, selected = _prepare_provider_arguments(
            manifest, module["name"], arguments
        )
        assert prepared == arguments
        assert selected["name"] == module["name"]


def step(key, operation, **kwargs):
    return PlanStep(key=key, agent="reader", tool_slug="notion", operation=operation,
                    reason="Read requested evidence", expected_output="Evidence", **kwargs)


def test_metadata_cannot_satisfy_a_body_content_requirement():
    plan = WorkflowPlan(name="Read", interpretation="Summarize page", steps=[
        step("page", "notion.page.get", arguments={"page_id": "p"}, required_evidence=["page_body"])])
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, {"notion": native_manifest("notion")})
    plan.steps[0].operation = "notion.blocks.children.list"
    assert compile_contracts(plan, {"notion": native_manifest("notion")})["page"]["provides"] == ["page_body"]


def test_receipt_prose_maps_only_to_guarantees_the_connector_provides():
    assert canonicalize_requested_evidence(
        "canva.presentation.create", ["Canva presentation creation receipt"],
        ["dispatch_receipt", "populated_presentation"],
    ) == ["dispatch_receipt", "populated_presentation"]
    assert canonicalize_requested_evidence(
        "calendar.list", ["calendar search results", "document_body"], ["event_state"],
    ) == ["event_state", "document_body"]
    assert canonicalize_requested_evidence(
        "google.identity.get", ["Connected Google account email"], ["account_identity"],
    ) == ["account_identity"]
    assert canonicalize_requested_evidence(
        "google.identity.get", ["Connected Google account access"], ["account_identity"],
    ) == ["Connected Google account access"]
    assert canonicalize_requested_evidence(
        "calendar.list", ["Calendar list results for today"], ["event_state"],
    ) == ["event_state"]
    assert canonicalize_requested_evidence(
        "calendar.list", ["Calendar event items for 2026-09-25"], ["event_state"],
    ) == ["event_state"]
    assert canonicalize_requested_evidence(
        "calendar.get", ["Today's calendar event details"], ["event_state"],
    ) == ["event_state"]
    assert canonicalize_requested_evidence(
        "gmail.send", ["Calendar results to summarize"], ["write_receipt"],
    ) == ["Calendar results to summarize"]
    plan = WorkflowPlan(name="Doc", interpretation="Create doc", steps=[PlanStep(
        key="doc", agent="Docs", tool_slug="google", operation="docs.create",
        arguments={"title": "Story", "body": "Text"}, reason="Create doc",
        expected_output="Doc receipt", required_evidence=["created Google Doc receipt"],
    )])
    manifests = {"google": native_manifest("google")}
    _normalize_planned_steps(plan, manifests)
    assert plan.steps[0].required_evidence == ["write_receipt"]
    assert compile_contracts(plan, manifests)["doc"]["provides"] == ["write_receipt"]
    plan.steps[0].required_evidence = ["document_body"]
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, manifests)


def test_calendar_email_input_labels_require_bound_source_before_compilation():
    manifest = native_manifest("google")
    plan = WorkflowPlan(name="Daily summary", interpretation="Email today's events", steps=[
        PlanStep(key="events", agent="reader", tool_slug="google", operation="calendar.list",
                 reason="Read events", expected_output="Today's events",
                 required_evidence=["Calendar event items for 2026-09-25"]),
        PlanStep(key="send", agent="sender", tool_slug="google", operation="gmail.send",
                 reason="Send summary", expected_output="Email receipt", consequential=True,
                 arguments={"to": "me", "body": "Today's events: {{steps.events.items}}"},
                 depends_on=["events"], required_evidence=[
                     "Connected recipient email", "Today’s calendar event details", "write_receipt",
                 ]),
    ])
    _normalize_planned_steps(plan, {"google": manifest})
    assert plan.steps[0].required_evidence == ["event_state"]
    assert plan.steps[1].required_evidence == ["write_receipt"]
    assert set(compile_contracts(plan, {"google": manifest})) == {"events", "send"}

    # A description must not authorize a body that does not actually use the read.
    plan.steps[1].arguments["body"] = "A made-up summary"
    plan.steps[1].required_evidence = ["Today’s calendar event details"]
    _normalize_planned_steps(plan, {"google": manifest})
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, {"google": manifest})

    # Nor may a read result be claimed as the Gmail send's output guarantee.
    plan.steps[1].arguments["body"] = "{{steps.events.items}}"
    plan.steps[1].required_evidence = ["page_body"]
    _normalize_planned_steps(plan, {"google": manifest})
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, {"google": manifest})


def test_planner_evidence_descriptions_do_not_loop_on_real_read_bindings():
    google = native_manifest("google")
    calendar = {
        "capabilities": [
            {"name": operation, "permission_scope": "read",
             "input_schema": {"type": "object", "additionalProperties": True},
             "output_schema": {"type": "object"}}
            for operation in ("google-calendar.get-current-user", "google-calendar.list-events")
        ],
    }
    manifests = {"google-calendar": calendar, "google": google}
    plan = WorkflowPlan(name="Meetings", interpretation="Summarize today's meetings", steps=[
        PlanStep(key="context", agent="calendar", tool_slug="google-calendar",
                 operation="google-calendar.get-current-user", arguments={},
                 reason="Read calendar context", expected_output="Calendar account context",
                 required_evidence=["Provider-local calendar context"]),
        PlanStep(key="events", agent="calendar", tool_slug="google-calendar",
                 operation="google-calendar.list-events", arguments={},
                 reason="Read meetings", expected_output="Today's meetings",
                 required_evidence=["Today's calendar events"]),
        PlanStep(key="gmail_context", agent="gmail", tool_slug="google",
                 operation="gmail.list", arguments={"query": "meeting"},
                 reason="Check Gmail access", expected_output="Gmail read check",
                 required_evidence=["Gmail read access discovery result"]),
    ])
    _normalize_planned_steps(plan, manifests)
    assert all(not step.required_evidence for step in plan.steps)
    assert "Provider-local calendar context" in plan.steps[0].expected_output
    assert "Today's calendar events" in plan.steps[1].expected_output
    assert "Gmail read access discovery result" in plan.steps[2].expected_output
    assert set(compile_contracts(plan, manifests)) == {"context", "events", "gmail_context"}


def test_planner_input_names_and_bound_references_are_not_output_guarantees():
    manifest = native_manifest("google")
    plan = WorkflowPlan(name="Mail", interpretation="Email calendar summary", steps=[
        PlanStep(key="events", agent="calendar", tool_slug="google",
                 operation="calendar.list", arguments={
                     "time_min": "2026-09-25T00:00:00Z", "time_max": "2026-09-26T00:00:00Z",
                 }, reason="Read meetings", expected_output="Events",
                 required_evidence=["time_min", "time_max"]),
        PlanStep(key="send", agent="gmail", tool_slug="google", operation="gmail.send",
                 arguments={"to": "me", "body": "{{steps.events.items}}"},
                 depends_on=["events"], consequential=True,
                 reason="Send summary", expected_output="Sent email",
                 required_evidence=["{{steps.events.items}}", "write_receipt"]),
    ])
    _normalize_planned_steps(plan, {"google": manifest})
    assert plan.steps[0].required_evidence == []
    assert plan.steps[1].required_evidence == ["write_receipt"]
    assert set(compile_contracts(plan, {"google": manifest})) == {"events", "send"}

    # Never erase a claimed dependency that is absent from the approved body.
    plan.steps[1].arguments["body"] = "No provider data here"
    plan.steps[1].required_evidence = ["{{steps.events.items}}"]
    _normalize_planned_steps(plan, {"google": manifest})
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, {"google": manifest})


def test_typed_read_descriptions_and_complete_email_preview_compile_without_replanning():
    manifest = native_manifest("google")
    plan = WorkflowPlan(name="Meeting summary", interpretation="Email today's meeting summary", steps=[
        PlanStep(key="events", agent="calendar", tool_slug="google", operation="calendar.list",
                 arguments={"time_min": "2026-09-25T00:00:00Z"},
                 reason="Read today's meetings", expected_output="Today's meetings",
                 required_evidence=["provider-local date boundary used for today"]),
        PlanStep(key="messages", agent="gmail", tool_slug="google", operation="gmail.list",
                 arguments={"query": "meeting"}, reason="Find messages",
                 expected_output="Messages", required_evidence=["gmail discovery candidates from read-only list"]),
        PlanStep(key="detail", agent="gmail", tool_slug="google", operation="gmail.get",
                 arguments={"message_id": "{{steps.messages.messages.0.id}}"}, depends_on=["messages"],
                 reason="Read message", expected_output="Message",
                 required_evidence=["message content"]),
        PlanStep(key="send", agent="gmail", tool_slug="google", operation="gmail.send",
                 arguments={"to": "me", "subject": "Today’s meetings",
                            "body": "{{steps.events.items}}\n{{steps.detail.payload}}"},
                 depends_on=["events", "detail"], consequential=True,
                 reason="Send reviewed email", expected_output="Delivery receipt",
                 required_evidence=["full recipient, subject, and body included for approval", "write_receipt"]),
    ])
    _normalize_planned_steps(plan, {"google": manifest})
    assert not plan.steps[0].required_evidence
    assert not plan.steps[1].required_evidence
    assert plan.steps[2].required_evidence == ["message_content"]
    assert "provider-local date boundary" in plan.steps[0].expected_output
    assert plan.steps[3].required_evidence == ["write_receipt"]
    assert len(compile_contracts(plan, {"google": manifest})) == 4

    plan.steps[3].arguments["subject"] = ""
    plan.steps[3].required_evidence = ["complete recipient, subject, and body"]
    _normalize_planned_steps(plan, {"google": manifest})
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, {"google": manifest})


@pytest.mark.parametrize("slug,operation,arguments,narrative", [
    ("google", "calendar.list", {}, "Calendar items with local meeting context"),
    ("notion", "notion.search", {"query": "project"}, "Relevant project pages discovered"),
    ("jira", "jira.issues.search", {"jql": "project = DEMO"}, "Current issue metadata to summarize"),
    ("slack", "slack.post", {"channel": "C123", "text": "Update"},
     "Complete channel and text included for approval"),
    ("google", "docs.create", {"title": "Report", "body": "Finished text"},
     "Complete title and body included for approval"),
])
def test_narrative_goals_across_connectors_do_not_impersonate_output_guarantees(
    slug, operation, arguments, narrative,
):
    plan = WorkflowPlan(name="Cross-provider contract", interpretation="Perform requested action", steps=[
        PlanStep(key="action", agent="agent", tool_slug=slug, operation=operation,
                 arguments=arguments, reason="Use the provider", expected_output="Provider result",
                 required_evidence=[narrative]),
    ])
    manifests = {slug: native_manifest(slug)}
    _normalize_planned_steps(plan, manifests)
    assert plan.steps[0].required_evidence == []
    assert narrative in plan.steps[0].expected_output
    assert "action" in compile_contracts(plan, manifests)


def test_narrative_goals_never_waive_missing_inputs_or_unbound_source_data():
    plan = WorkflowPlan(name="Summary", interpretation="Post issue summary", steps=[
        PlanStep(key="issues", agent="reader", tool_slug="jira", operation="jira.issues.search",
                 arguments={"jql": "project = DEMO"}, reason="Read issues", expected_output="Issues"),
        PlanStep(key="post", agent="sender", tool_slug="slack", operation="slack.post",
                 arguments={"channel": "C123", "text": "An invented summary"},
                 depends_on=["issues"], reason="Post summary", expected_output="Receipt",
                 required_evidence=["Jira results included in the Slack text"]),
    ])
    manifests = {slug: native_manifest(slug) for slug in ("jira", "slack")}
    _normalize_planned_steps(plan, manifests)
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, manifests)

    plan.steps[1].arguments["text"] = "{{steps.issues.issues}}"
    _normalize_planned_steps(plan, manifests)
    assert not plan.steps[1].required_evidence
    assert "Jira results" in plan.steps[1].expected_output
    assert "post" in compile_contracts(plan, manifests)

    plan.steps[1].required_evidence = ["Complete channel and text included for approval"]
    plan.steps[1].arguments["text"] = ""
    with pytest.raises(Exception, match="text"):
        _normalize_planned_steps(plan, manifests)


def test_untyped_connector_prose_uses_the_same_boundary():
    manifest = {"capabilities": [{
        "name": "records.lookup", "permission_scope": "read", "input_schema": None,
        "output_schema": {"type": "object"},
    }]}
    plan = WorkflowPlan(name="CRM lookup", interpretation="Read a customer record", steps=[
        PlanStep(key="lookup", agent="crm", tool_slug="crm-plugin", operation="records.lookup",
                 reason="Find customer", expected_output="Customer record",
                 required_evidence=["Latest customer record with account context"]),
    ])
    from app.operation_contracts import normalize_planner_evidence_roles

    normalize_planner_evidence_roles(plan, {"crm-plugin": manifest})
    assert not plan.steps[0].required_evidence
    assert "account context" in plan.steps[0].expected_output
    assert "lookup" in compile_contracts(plan, {"crm-plugin": manifest})


def test_unavailable_structural_guarantees_remain_rejected_or_require_readback():
    for slug, operation, arguments, requested in (
        ("notion", "notion.page.get", {"page_id": "p"}, "Full page body"),
        ("google", "docs.create", {"title": "Story", "body": "Full story"}, "Full document body"),
    ):
        plan = WorkflowPlan(name="Read full content", interpretation="Verify content", steps=[
            PlanStep(key="step", agent="agent", tool_slug=slug, operation=operation,
                     arguments=arguments, reason="Verify content", expected_output="Content",
                     required_evidence=[requested]),
        ])
        manifests = {slug: native_manifest(slug)}
        _normalize_planned_steps(plan, manifests)
        assert plan.steps[0].required_evidence == [
            "page_body" if slug == "notion" else "document_body"
        ]
        with pytest.raises(ValueError, match="cannot supply"):
            compile_contracts(plan, manifests)


@pytest.mark.parametrize("prompt_text,required", [
    ("Send today's meeting summary to me via Gmail", {"gmail.send"}),
    ("Email me the calendar summary", {"gmail.send"}),
    ("Use Gmail to send the email", {"gmail.send"}),
    ("Do not send the draft. Email me the final summary", {"gmail.send"}),
    ("Draft an email for me to review, but do not send it", set()),
    ("Prepare an email to me summarizing meetings. Show me the complete recipient, subject, and email body for approval before sending it.", {"gmail.send"}),
    ("Prepare an email to me. Show it before sending it, but do not send it.", set()),
    ("Summarize emails and send a Slack message", set()),
    ("Find customers I have not followed up with this week and send personalized check-in emails via Gmail", {"gmail.send"}),
    ("Follow up with my customers via Gmail", {"gmail.send"}),
    ("Find customers I have not followed up with this week; draft emails but do not send them", set()),
    ("Find customers I haven't followed up with this week and draft a personalized check-in email for each one", set()),
    ("Draft a follow-up email to customers via Gmail", set()),
    ("Draft a follow up with customers via Gmail", set()),
])
def test_explicit_email_delivery_is_a_required_external_action(prompt_text, required):
    assert requested_external_operations(prompt_text) == required


def test_draft_only_customer_request_cannot_send_even_when_old_plan_contains_send():
    prompt = ("Find customers I haven't followed up with this week and draft a "
              "personalized check-in email for each one")
    revision = (prompt + "\n\nThe user reviewed the proposed workflow and requested this change: "
                "For ‘Identify overdue follow-ups’: Use gmail instead of AURA Intelligence"
                "\nCurrent reviewed steps (preserve unchanged steps and dependencies): "
                '[{"operation":"gmail.send","reason":"Send follow-up"}]'
                "\nReturn the complete revised executable plan.")
    assert draft_only_email_request(revision)
    assert requested_external_operations(revision) == set()
    repair = (prompt + "\n\nThe user reviewed the proposed workflow and requested this change: "
              "AURA backend authorization rejected the previous plan. Resolve every issue: "
              "gmail.send transmits emails; remove every send step. "
              "Preserve the user's requested external actions and final review.")
    assert draft_only_email_request(repair)
    assert requested_external_operations(repair) == set()
    manifest = native_manifest("google")
    inventory = [{"slug": "google", "name": "Google Workspace", "allowed_operations": [
        module["name"] for module in manifest["capabilities"]]}]
    read = PlanStep(key="search", agent="gmail", tool_slug="google", operation="gmail.list",
                    arguments={"query": "in:sent"}, reason="Find messages", expected_output="IDs")
    get = PlanStep(key="message", agent="gmail", tool_slug="google", operation="gmail.get",
                   arguments={"message_id": "{{steps.search.messages.0.id}}"},
                   depends_on=["search"], reason="Read conversation", expected_output="Context")
    plan = WorkflowPlan(name="Follow-up drafts", interpretation=prompt, steps=[read, get])
    validate_requested_operations(revision, plan, set(inventory[0]["allowed_operations"]),
                                  inventory, {"google": manifest})
    plan.steps.append(PlanStep(key="send", agent="gmail", tool_slug="google",
                               operation="gmail.send", consequential=True,
                               arguments={"to": "customer@example.test", "body": "Message"},
                               reason="Send message", expected_output="Receipt"))
    with pytest.raises(ValueError, match="drafts only"):
        validate_requested_operations(revision, plan, set(inventory[0]["allowed_operations"]),
                                      inventory, {"google": manifest})
    plan.steps.pop()
    plan.steps.pop()
    with pytest.raises(ValueError, match="gmail.get"):
        validate_requested_operations(revision, plan, set(inventory[0]["allowed_operations"]),
                                      inventory, {"google": manifest})


def test_read_only_calendar_plan_cannot_erase_requested_email_delivery():
    read_only = WorkflowPlan(name="Summary", interpretation="Email a summary", steps=[
        PlanStep(key="events", agent="calendar", tool_slug="google",
                 operation="calendar.list", reason="Read events", expected_output="Events"),
        PlanStep(key="inbox", agent="gmail", tool_slug="google",
                 operation="gmail.list", reason="Read messages", expected_output="Messages"),
    ])
    with pytest.raises(ValueError, match="gmail.send"):
        validate_requested_operations(
            "Send today's meeting summary to me via Gmail", read_only,
            {"calendar.list", "gmail.list", "gmail.send"},
        )
    read_only.steps.append(PlanStep(
        key="send", agent="gmail", tool_slug="google", operation="gmail.send",
        reason="Send the summary", expected_output="Email receipt", consequential=True,
        depends_on=["events"], arguments={"to": "me", "body": "{{steps.events.items}}"},
    ))
    validate_requested_operations(
        "Send today's meeting summary to me via Gmail", read_only,
        {"calendar.list", "gmail.list", "gmail.send"},
    )


def test_gmail_followup_requires_delivery_and_message_content():
    prompt = (
        "Find customers I have not followed up with this week and send "
        "personalized check-in emails to each via Gmail"
    )
    plan = WorkflowPlan(name="Follow-ups", interpretation=prompt, steps=[
        PlanStep(key="search", agent="gmail", tool_slug="google", operation="gmail.list",
                 arguments={"query": "newer_than:7d"}, reason="Find conversations",
                 expected_output="Message IDs"),
    ])
    available = {"gmail.list", "gmail.get", "gmail.send"}
    with pytest.raises(ValueError, match="gmail.send"):
        validate_requested_operations(prompt, plan, available)
    plan.steps.append(PlanStep(key="send", agent="gmail", tool_slug="google",
                               operation="gmail.send", arguments={"to": "me", "body": "Draft"},
                               depends_on=["search"], consequential=True,
                               reason="Send follow-up", expected_output="Receipt"))
    with pytest.raises(ValueError, match="gmail.get"):
        validate_requested_operations(prompt, plan, available)
    plan.steps.insert(1, PlanStep(key="read", agent="gmail", tool_slug="google",
                                  operation="gmail.get", arguments={"message_id": "{{steps.search.messages.0.id}}"},
                                  depends_on=["search"], reason="Read context",
                                  expected_output="Full message"))
    with pytest.raises(ValueError, match="depend on"):
        validate_requested_operations(prompt, plan, available)
    plan.steps[-1].depends_on = ["read"]
    with pytest.raises(ValueError, match="resolved customers"):
        validate_requested_operations(prompt, plan, available)
    plan.steps[-1].arguments["to"] = "customer@example.test"
    validate_requested_operations(prompt, plan, available)


def test_gmail_get_output_fields_use_verified_evidence_tags():
    plan = WorkflowPlan(name="Email context", interpretation="Read message", steps=[
        PlanStep(key="message", agent="gmail", tool_slug="google",
                 operation="gmail.get", arguments={"message_id": "message-1"},
                 reason="Read the full message and its thread", expected_output="Message context",
                 required_evidence=["payload", "threadId"]),
    ])
    manifests = {"google": native_manifest("google")}
    _normalize_planned_steps(plan, manifests)
    assert plan.steps[0].required_evidence == ["message_content", "message_metadata"]
    compile_contracts(plan, manifests)
    from app.operation_contracts import output_errors

    assert output_errors("gmail.get", {"id": "message-1"})
    assert output_errors("gmail.get", {
        "id": "message-1", "threadId": "thread-1", "payload": {},
    }) == []


def test_review_before_sending_requires_email_action_with_real_catalog():
    prompt = ("Read my Google Calendar meetings for today and any Gmail messages relevant to "
              "those meetings. Prepare an email to me summarizing the meetings, including their "
              "times and useful context from the messages. Show me the complete recipient, "
              "subject, and email body for approval before sending it.")
    plan = WorkflowPlan(name="Summary", interpretation=prompt, steps=[
        PlanStep(key="events", agent="calendar", tool_slug="google", operation="calendar.list",
                 reason="Read events", expected_output="Events"),
        PlanStep(key="messages", agent="gmail", tool_slug="google", operation="gmail.list",
                 reason="Read messages", expected_output="Messages"),
    ])
    manifests = {"google": native_manifest("google")}
    inventory = [{"slug": "google", "name": "Google Workspace", "allowed_operations": [
        module["name"] for module in manifests["google"]["capabilities"]]}]
    with pytest.raises(ValueError, match="gmail send"):
        validate_requested_operations(prompt, plan, set(inventory[0]["allowed_operations"]),
                                      inventory, manifests)


@pytest.mark.parametrize("prompt_text,effect", [
    ("Send today's meeting summary to me via Gmail", "gmail send"),
    ("Send personalized follow-up emails to customers via Gmail", "gmail send"),
    ("Summarize emails and send a Slack message", "slack send"),
    ("Use Slack to post the summary", "slack send"),
    ("Schedule an event in Google Calendar", "calendar create"),
    ("Create a Jira issue", "jira create"),
    ("Create a Google Doc", "docs create"),
    ("Create a report from Jira issues", None),
    ("Read Slack messages and summarize them", None),
    ("Draft an email but do not send it", None),
    ("Draft a personalized email to each customer via Gmail", None),
])
def test_explicit_provider_effects_survive_replanning_across_apps(prompt_text, effect):
    slugs = ("google", "slack", "jira")
    inventory = [
        {"slug": slug, "name": {"google": "Google Workspace", "slack": "Slack",
                                "jira": "Jira"}[slug],
         "allowed_operations": [m["name"] for m in native_manifest(slug)["capabilities"]]}
        for slug in slugs
    ]
    effects = requested_effects(prompt_text, inventory, {
        slug: native_manifest(slug) for slug in slugs
    })
    assert [item["effect"] for item in effects] == ([effect] if effect else [])


def test_a_required_effect_needs_a_nonoptional_step_and_an_accepted_receipt():
    inventory = [{"slug": "slack", "name": "Slack", "allowed_operations": [
        "slack.channels.list", "slack.post",
    ]}]
    manifests = {"slack": native_manifest("slack")}
    prompt = "Send a Slack message"
    plan = WorkflowPlan(name="Notify", interpretation=prompt, steps=[
        PlanStep(key="channels", agent="reader", tool_slug="slack",
                 operation="slack.channels.list", reason="List channels",
                 expected_output="Channels"),
    ])
    with pytest.raises(ValueError, match="slack.post"):
        validate_requested_operations(prompt, plan, set(inventory[0]["allowed_operations"]),
                                      inventory, manifests)
    plan.steps.append(PlanStep(
        key="notify", agent="sender", tool_slug="slack", operation="slack.post",
        reason="Post the message", expected_output="Post receipt", optional=True,
    ))
    with pytest.raises(ValueError, match="required approved operation"):
        validate_requested_operations(prompt, plan, set(inventory[0]["allowed_operations"]),
                                      inventory, manifests)
    plan.steps[-1].optional = False
    effects = validate_requested_operations(prompt, plan, set(inventory[0]["allowed_operations"]),
                                            inventory, manifests)
    assert not missing_requested_operations(prompt, {"slack.post"}, effects, [{
        "tool": "slack", "operation": "slack.post",
    }])
    assert missing_requested_operations(prompt, {"slack.channels.list"}, effects, [{
        "tool": "slack", "operation": "slack.channels.list",
    }]) == {"slack send"}


def test_dynamic_sender_can_fulfill_a_provider_effect_without_native_route():
    inventory = [
        {"slug": "google", "name": "Google Workspace", "allowed_operations": ["gmail.send"]},
        {"slug": "pipedream-gmail", "name": "Gmail", "allowed_operations": ["send-email"]},
    ]
    manifests = {
        "google": native_manifest("google"),
        "pipedream-gmail": {"capabilities": [{
            "name": "send-email", "permission_scope": "write", "description": "Send an email",
        }]},
    }
    prompt = "Send this message via Gmail"
    plan = WorkflowPlan(name="Email", interpretation=prompt, steps=[
        PlanStep(key="mail", agent="sender", tool_slug="pipedream-gmail",
                 operation="send-email", reason="Send message", expected_output="Receipt"),
    ])
    effects = validate_requested_operations(prompt, plan, {"gmail.send", "send-email"},
                                            inventory, manifests)
    assert len(effects) == 1
    assert {target["operation"] for target in effects[0]["targets"]} == {
        "gmail.send", "send-email",
    }


def test_invalid_output_reference_rejected_but_metadata_alias_compiles():
    plan = WorkflowPlan(name="Read", interpretation="Read page", steps=[
        step("search", "notion.search"),
        step("page", "notion.page.get", arguments={"page_id": "{{steps.search.page_id}}"}, depends_on=["search"])])
    compile_contracts(plan, {"notion": native_manifest("notion")})
    plan.steps[1].arguments = {"page_id": "{{steps.search.body}}"}
    with pytest.raises(ValueError, match="outside the source contract"):
        compile_contracts(plan, {"notion": native_manifest("notion")})


@pytest.mark.parametrize("operation", sorted(KNOWN))
def test_typed_outputs_reject_missing_receipts_without_leaking_content(operation):
    errors = output_errors(operation, {"private": "secret customer content"})
    assert errors
    assert "secret" not in str(errors)


@pytest.mark.parametrize("status,retryable,category", [(400, False, "invalid_request"),
    (401, False, "authorization_required"), (403, False, "authorization_required"),
    (429, True, "rate_limited"), (503, True, "provider_unavailable")])
def test_failure_categories_and_write_uncertainty(status, retryable, category):
    request = httpx.Request("GET", "https://fixture.invalid")
    response = httpx.Response(status, request=request, headers={"Retry-After": "120"})
    error = httpx.HTTPStatusError("fixture failure", request=request, response=response)
    failure = classify_failure(error, read=True)
    assert (failure.retryable, failure.category) == (retryable, category)
    assert not classify_failure(error, read=False).retryable
    if status == 429:
        assert failure.retry_after == 120


@pytest.mark.parametrize(
    "status,category",
    [
        (400, "invalid_request"),
        (404, "invalid_request"),
        (422, "invalid_request"),
        (409, "uncertain_write"),
        (500, "uncertain_write"),
    ],
)
def test_write_failures_distinguish_definitive_rejection_from_uncertainty(
    status, category
):
    request = httpx.Request("POST", "https://provider.example/items")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError("fixture failure", request=request, response=response)
    assert classify_failure(error, read=False).category == category


async def test_model_budget_prevents_additional_calls_and_isolated_contexts():
    called = []
    async def result():
        called.append(True)
        return "ok"
    token = model_budget.set(CallBudget(monotonic() + 1, 1))
    try:
        assert await bounded_model_call(result, 1) == "ok"
        with pytest.raises(BudgetExceeded):
            await bounded_model_call(result, 1)
        assert len(called) == 1
    finally:
        model_budget.reset(token)


@pytest.fixture
def scheduler_state():
    previous = dict(dispatch.scheduler_observation)
    dispatch.scheduler_observation.update(
        last_tick_at=None,
        last_success_at=None,
        last_error_at=None,
        last_error_type=None,
        last_error_code=None,
        consecutive_failures=0,
        leader=False,
        tick_in_progress=False,
        tick_started_at=None,
        active_stage="idle",
    )
    yield dispatch.scheduler_observation
    dispatch.scheduler_observation.clear()
    dispatch.scheduler_observation.update(previous)


async def test_scheduler_cycle_records_live_progress_and_completion(
    scheduler_state, monkeypatch
):
    async def completed_tick():
        assert scheduler_state["tick_in_progress"] is True
        assert scheduler_state["last_tick_at"] is not None
        dispatch._mark_scheduler_progress("fixture_stage")
        return {"leader": True, "engineered": 1}

    monkeypatch.setattr(dispatch, "recovery_tick", completed_tick)

    result = await dispatch.run_recovery_cycle(timeout_seconds=1)

    assert result == {"leader": True, "engineered": 1}
    assert scheduler_state["last_success_at"] is not None
    assert scheduler_state["last_error_type"] is None
    assert scheduler_state["consecutive_failures"] == 0
    assert scheduler_state["tick_in_progress"] is False
    assert scheduler_state["active_stage"] == "idle"


async def test_scheduler_cycle_exposes_safe_failure_metadata(scheduler_state, monkeypatch):
    class ProviderFailure(RuntimeError):
        status_code = 503

    async def failed_tick():
        dispatch._mark_scheduler_progress("recovery_engineer")
        raise ProviderFailure("private provider detail")

    monkeypatch.setattr(dispatch, "recovery_tick", failed_tick)

    result = await dispatch.run_recovery_cycle(timeout_seconds=1)

    assert result == {"leader": False, "error_type": "ProviderFailure"}
    assert scheduler_state["last_error_type"] == "ProviderFailure"
    assert scheduler_state["last_error_code"] == 503
    assert scheduler_state["active_stage"] == "recovery_engineer"
    assert scheduler_state["consecutive_failures"] == 1
    assert "private provider detail" not in str(scheduler_state)


async def test_scheduler_cycle_times_out_instead_of_hanging(scheduler_state, monkeypatch):
    async def stalled_tick():
        dispatch._mark_scheduler_progress("autonomous_recovery")
        await asyncio.Event().wait()

    monkeypatch.setattr(dispatch, "recovery_tick", stalled_tick)

    result = await dispatch.run_recovery_cycle(timeout_seconds=0.01)

    assert result == {"leader": False, "error_type": "TimeoutError"}
    assert scheduler_state["last_error_type"] == "TimeoutError"
    assert scheduler_state["active_stage"] == "autonomous_recovery"
    assert scheduler_state["tick_in_progress"] is False


async def test_api_recovery_tick_dispatches_due_schedules_without_separate_beat(
    monkeypatch,
):
    calls = []

    @asynccontextmanager
    async def elected(*args, **kwargs):
        yield True

    async def due():
        calls.append("due")
        return [("scheduled-run", "workspace")]

    async def none(*args, **kwargs):
        return []

    async def publish(*args, **kwargs):
        return 0

    async def no_processes():
        return {"triggered": 0, "dispatched": 0, "advanced": 0, "attention": 0}

    monkeypatch.setattr(dispatch, "execution_lock", elected)
    monkeypatch.setattr(process_runtime, "dispatch_due_processes", no_processes)
    monkeypatch.setattr(scheduler_runtime, "dispatch_due_schedules", due)
    monkeypatch.setattr(scheduler_runtime, "recover_stale_runs", none)
    monkeypatch.setattr(scheduler_runtime, "recover_recorded_jira_readbacks", none)
    monkeypatch.setattr(scheduler_runtime, "recover_waiting_runs", none)
    monkeypatch.setattr(scheduler_runtime, "recover_engineer_runs", none)
    monkeypatch.setattr(dispatch, "dispatch_pending", publish)

    result = await dispatch.recovery_tick()

    assert calls == ["due"]
    assert result["scheduled"] == 1


async def test_readiness_exposes_only_safe_scheduler_diagnostics(
    scheduler_state, monkeypatch
):
    from fastapi import HTTPException

    from app import main

    class StubConnection:
        async def execute(self, *args, **kwargs):
            return None

    class StubEngine:
        @asynccontextmanager
        async def connect(self):
            yield StubConnection()

    class StubCache:
        async def ping(self):
            return True

        async def aclose(self):
            return None

    now = datetime.now(UTC).isoformat()
    scheduler_state.update(
        started_at=now,
        last_tick_at=now,
        last_error_at=now,
        last_error_type="ProgrammingError",
        last_error_code="42P01",
        consecutive_failures=3,
        active_stage="recovery_engineer",
    )
    monkeypatch.setattr(main, "engine", StubEngine())
    monkeypatch.setattr(main.redis, "from_url", lambda *args, **kwargs: StubCache())
    monkeypatch.setattr(main, "production_configuration_checks", lambda: {"config": True})
    monkeypatch.setattr(main.settings, "recovery_scheduler_enabled", True)
    monkeypatch.setattr("app.worker_health.worker_responds", AsyncMock(return_value=True))

    with pytest.raises(HTTPException) as raised:
        await main.readiness()

    assert raised.value.status_code == 503
    details = raised.value.detail["recovery_scheduler"]
    assert details["last_error_type"] == "ProgrammingError"
    assert details["last_error_code"] == "42P01"
    assert details["active_stage"] == "recovery_engineer"
    assert "private" not in str(raised.value.detail)

    scheduler_state.update(consecutive_failures=0, last_error_type=None)
    monkeypatch.setattr("app.worker_health.worker_responds", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as missing_worker:
        await main.readiness()
    assert missing_worker.value.detail["checks"]["execution_worker"] is False
    assert missing_worker.value.detail["checks"]["recovery_scheduler"] is True


async def test_worker_readiness_checks_a_real_worker_and_caches_reply(monkeypatch):
    from app import worker_health

    calls = []

    def reply(*, timeout):
        calls.append(timeout)
        return [{"celery@worker": {"ok": "pong"}}]

    monkeypatch.setattr(worker_health.celery.control, "ping", reply)
    monkeypatch.setattr(worker_health, "_last_check", 0.0)

    assert await worker_health.worker_responds() is True
    assert await worker_health.worker_responds() is True
    assert calls == [1.0]


async def test_worker_readiness_fails_closed_on_missing_or_unreachable_worker(monkeypatch):
    from app import worker_health

    monkeypatch.setattr(worker_health, "_last_check", 0.0)
    monkeypatch.setattr(worker_health.celery.control, "ping", lambda **kwargs: [])
    assert await worker_health.worker_responds() is False

    def unavailable(**kwargs):
        raise ConnectionError("private broker URL")

    monkeypatch.setattr(worker_health.celery.control, "ping", unavailable)
    monkeypatch.setattr(worker_health, "_last_check", 0.0)
    assert await worker_health.worker_responds() is False


@pytest.fixture
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dispatch, "SessionLocal", factory)
    monkeypatch.setattr(scheduler_runtime, "SessionLocal", factory)
    async with factory() as session:
        session.add(Workspace(id="w", name="Dedicated fixture"))
        await session.commit()
    yield factory
    await engine.dispose()


async def test_outbox_is_atomic_and_survives_broker_failure(database, monkeypatch):
    async with database() as session:
        session.add(WorkflowRun(id="rolled-back", workspace_id="w", prompt="Fixture"))
        await session.flush()
        await session.rollback()
        assert not (await session.scalars(select(DispatchIntent))).all()
        session.add(WorkflowRun(id="run", workspace_id="w", prompt="Fixture"))
        await session.commit()
    def unavailable(*args):
        raise ConnectionError("Broker offline")
    monkeypatch.setattr(worker.plan_run_task, "delay", unavailable)
    assert await dispatch.dispatch_pending("w") == 0
    async with database() as session:
        intent = await session.scalar(select(DispatchIntent))
        assert intent.status == "pending" and intent.attempts == 1
        intent.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    sent = []
    monkeypatch.setattr(worker.plan_run_task, "delay", lambda *args: sent.append(args))
    assert await dispatch.dispatch_pending("w") == 1
    assert await dispatch.dispatch_pending("w") == 0
    assert sent == [("run", "w")]


async def test_dispatch_never_resumes_approval_paused_or_completed_runs(database, monkeypatch):
    async with database() as session:
        for name, status in [("approval", RunStatus.awaiting_approval), ("complete", RunStatus.completed)]:
            session.add(WorkflowRun(id=name, workspace_id="w", prompt="Fixture", status=status))
            session.add(DispatchIntent(workspace_id="w", run_id=name, kind="execute"))
        await session.commit()
    def forbidden(*args):
        pytest.fail("Dispatch crossed an approval or terminal boundary")
    monkeypatch.setattr(worker.execute_run_task, "delay", forbidden)
    monkeypatch.setattr(worker.index_memory_task, "delay", lambda *args: None)
    await dispatch.dispatch_pending("w")
    async with database() as session:
        runs = (await session.scalars(select(WorkflowRun).order_by(WorkflowRun.id))).all()
        assert [run.status for run in runs] == [RunStatus.awaiting_approval, RunStatus.completed]


async def test_targeted_dispatch_does_not_publish_another_saved_run(database, monkeypatch):
    async with database() as session:
        for name in ("requested", "unrelated"):
            session.add(WorkflowRun(id=name, workspace_id="w", prompt="Fixture", status=RunStatus.running))
            session.add(DispatchIntent(workspace_id="w", run_id=name, kind="execute",
                                       available_at=datetime.now(UTC) - timedelta(seconds=1)))
        await session.commit()
    sent = []
    monkeypatch.setattr(worker.execute_run_task, "delay", lambda *args: sent.append(args))
    assert await dispatch.dispatch_pending("w", run_id="requested") == 1
    assert sent == [("requested", "w")]
    async with database() as session:
        unrelated = await session.scalar(select(DispatchIntent).where(
            DispatchIntent.run_id == "unrelated", DispatchIntent.kind == "execute"))
        assert unrelated.status == "pending"


async def test_worker_schedules_only_its_own_future_preflight_retry(database, monkeypatch):
    async with database() as session:
        for name in ("requested", "unrelated"):
            session.add(WorkflowRun(id=name, workspace_id="w", prompt="Fixture", status=RunStatus.running))
            session.add(DispatchIntent(
                workspace_id="w", run_id=name, kind="execute",
                available_at=datetime.now(UTC) + timedelta(seconds=20),
            ))
        await session.commit()
    sent = []
    monkeypatch.setattr(
        worker.execute_run_task,
        "apply_async",
        lambda *, args, countdown: sent.append((args, countdown)),
    )
    assert await dispatch.dispatch_pending(
        "w", run_id="requested", schedule_delayed_execute=True
    ) == 1
    assert len(sent) == 1
    assert sent[0][0] == ["requested", "w"]
    assert 0 < sent[0][1] <= 20
    async with database() as session:
        requested = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == "requested"))
        unrelated = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == "unrelated"))
        assert requested.status == "published"
        assert unrelated.status == "pending"


async def test_worker_schedules_only_its_own_future_planning_repair(database, monkeypatch):
    async with database() as session:
        for name in ("requested", "unrelated"):
            session.add(WorkflowRun(id=name, workspace_id="w", prompt="Fixture", status=RunStatus.planning))
            session.add(DispatchIntent(
                workspace_id="w", run_id=name, kind="plan",
                available_at=datetime.now(UTC) + timedelta(seconds=20),
            ))
        await session.commit()
    sent = []
    monkeypatch.setattr(
        worker.plan_run_task, "apply_async",
        lambda *, args, countdown: sent.append((args, countdown)),
    )
    assert await dispatch.dispatch_pending(
        "w", run_id="requested", schedule_delayed_plan=True
    ) == 1
    assert len(sent) == 1
    assert sent[0][0] == ["requested", "w"]
    assert 0 < sent[0][1] <= 20
    async with database() as session:
        requested = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == "requested"))
        unrelated = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == "unrelated"))
        assert requested.status == "published"
        assert unrelated.status == "pending"


@pytest.mark.skipif(not __import__('os').getenv('AURA_TEST_POSTGRES_URL'), reason="Requires PostgreSQL")
async def test_postgres_scheduler_and_dispatch_concurrency(monkeypatch):
    import os
    import uuid

    from app import migrations
    from app.execution_lock import execution_lock
    engine = create_async_engine(os.environ['AURA_TEST_POSTGRES_URL'])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(migrations, "engine", engine)
    await migrations.migrate_database()
    for module in (dispatch, scheduler_runtime):
        monkeypatch.setattr(module, "SessionLocal", factory)
        monkeypatch.setattr(module, "engine", engine)
    tenant = str(uuid.uuid4())
    async def tenants():
        return [tenant]
    monkeypatch.setattr(scheduler_runtime, "_workspace_ids", tenants)
    old = datetime.now(UTC) - timedelta(hours=1)
    statuses = [RunStatus.queued, RunStatus.planning, RunStatus.running, RunStatus.recovering,
                RunStatus.awaiting_approval, RunStatus.completed, RunStatus.cancelled, RunStatus.waiting_for_action]
    identifiers = {status: str(uuid.uuid4()) for status in statuses}
    sent = []
    for task in (worker.plan_run_task, worker.execute_run_task, worker.index_memory_task):
        monkeypatch.setattr(task, "delay", lambda *args: sent.append(args))
    try:
        async with factory() as session:
            session.add(Workspace(id=tenant, name="Isolated release fixture"))
            await session.commit()
            for status, run_id in identifiers.items():
                session.add(WorkflowRun(id=run_id, workspace_id=tenant, prompt="Fixture", status=status, updated_at=old))
            await session.commit()
        await dispatch.dispatch_pending(tenant)  # Simulate already delivered/lost jobs.
        async with execution_lock(engine, tenant, identifiers[RunStatus.running]) as owned:
            assert owned
            recovered = await scheduler_runtime.recover_stale_runs(stale_after_seconds=600)
            assert identifiers[RunStatus.running] not in [row[0] for row in recovered]
            assert len(recovered) == 3
        async with factory() as session:
            for state in (RunStatus.awaiting_approval, RunStatus.completed, RunStatus.cancelled, RunStatus.waiting_for_action):
                assert (await session.get(WorkflowRun, identifiers[state])).status == state
        # Concurrent publishers cannot claim the same outbox row.
        await asyncio.gather(dispatch.dispatch_pending(tenant), dispatch.dispatch_pending(tenant))
        async with factory() as session:
            published = (await session.scalars(select(DispatchIntent).where(DispatchIntent.workspace_id == tenant, DispatchIntent.status == "published"))).all()
            assert len(sent) == len(published)
        # A single elected scheduler executes each tick; other API replicas skip.
        async with execution_lock(engine, "system", "recovery-scheduler") as owned:
            assert owned
            assert await dispatch.recovery_tick() == {"leader": False}
        # Repeated abandonment consumes a durable budget, then pauses.
        for _ in range(4):
            await dispatch.dispatch_pending(tenant)
            async with factory() as session:
                run = await session.get(WorkflowRun, identifiers[RunStatus.planning])
                run.updated_at = old
                await session.commit()
            await scheduler_runtime.recover_stale_runs(stale_after_seconds=600)
        async with factory() as session:
            run = await session.get(WorkflowRun, identifiers[RunStatus.planning])
            assert run.status == RunStatus.waiting_for_action
            assert run.execution_context["restart_recoveries"] == 3
    finally:
        from sqlalchemy import delete

        from app.models import AuditEvent
        async with factory() as session:
            await session.execute(delete(DispatchIntent).where(DispatchIntent.workspace_id == tenant))
            await session.execute(delete(AuditEvent).where(AuditEvent.workspace_id == tenant))
            await session.execute(delete(WorkflowRun).where(WorkflowRun.workspace_id == tenant))
            await session.execute(delete(Workspace).where(Workspace.id == tenant))
            await session.commit()
        await engine.dispose()


async def test_parallel_reads_checkpoint_before_io_and_do_not_replay(database, monkeypatch):
    from app import orchestrator, parallel_reads
    from app.config import get_settings
    from app.models import (
        CapabilityManifest,
        RunStep,
        StepAttempt,
        StepStatus,
        ToolConnection,
        ToolKind,
    )
    from app.native_connectors import native_operations
    from app.policy import DEFAULT_POLICY
    monkeypatch.setattr(get_settings(), "parallel_reads_enabled", True)
    monkeypatch.setattr(get_settings(), "agent_managed_execution_enabled", False)
    monkeypatch.setattr(orchestrator.CredentialVault, "decrypt", lambda self, value: {"access_token": "fixture"})
    async def credentials(*args):
        return {"access_token": "fixture"}, False
    monkeypatch.setattr(parallel_reads, "refresh_oauth_credentials", credentials)
    async def trust(*args):
        return SimpleNamespace(score=1.0)
    monkeypatch.setattr(orchestrator, "_trust_state", trust)
    monkeypatch.setattr(orchestrator, "_update_trust", lambda *args, **kwargs: None)
    operations = native_operations("notion")
    snapshot = SimpleNamespace(policy_snapshot=DEFAULT_POLICY,
        permission_snapshot={"notion": operations}, cost_snapshot={"estimated_cost_usd": 0})
    async with database() as session:
        run = WorkflowRun(id="parallel", workspace_id="w", prompt="Read fixture pages", status=RunStatus.running)
        session.add(run)
        tool = ToolConnection(id="notion", workspace_id="w", slug="notion", display_name="Fixture",
            kind=ToolKind.oauth, allowed_operations=operations, encrypted_credentials="fixture", config={})
        session.add(tool)
        session.add(CapabilityManifest(workspace_id="w", tool_id="notion", status="verified",
            provider_type="oauth", manifest=native_manifest("notion")))
        steps = [RunStep(id=f"s{i}", run_id="parallel", position=i, step_key=f"s{i}", agent="read",
            tool_slug="notion", operation="notion.page.get", arguments={"page_id": f"p{i}"},
            status=StepStatus.pending, idempotency_key=f"fixture{i}") for i in range(2)]
        session.add_all(steps)
        await session.commit()
        # Revoked permissions exclude work from the fast path.
        tool.allowed_operations = []
        await session.commit()
        await parallel_reads.prefetch_ready_reads(session, run, steps, 0, snapshot, {}, [])
        assert not (await session.scalars(select(StepAttempt))).all()
        tool.allowed_operations = operations
        await session.commit()
        entered = asyncio.Event()
        active = []
        async def provider(self, operation, arguments):
            active.append(arguments["page_id"])
            if len(active) == 2:
                entered.set()
            await asyncio.wait_for(entered.wait(), 1)
            # The second connection sees both attempts committed before IO.
            async with database() as read_session:
                assert len((await read_session.scalars(select(StepAttempt))).all()) == 2
            return {"id": arguments["page_id"], "properties": {}}
        monkeypatch.setattr(parallel_reads.ProviderExecutor, "execute", provider)
        await parallel_reads.prefetch_ready_reads(session, run, steps, 0, snapshot, {}, [])
        assert len(active) == 2
        assert all(item.output["provider_result"]["id"] for item in steps)
        await parallel_reads.prefetch_ready_reads(session, run, steps, 0, snapshot, {}, [])
        assert len(active) == 2


async def test_plan_reuse_checks_owner_inputs_and_contracts(database, monkeypatch):
    from app import plan_reuse
    from app.native_connectors import native_operations
    manifests = {"notion": native_manifest("notion")}
    plan = WorkflowPlan(name="Saved read", interpretation="Read fixture", steps=[
        step("page", "notion.page.get", arguments={"page_id": "fixture"})])
    plan.planning_artifacts["compiled_contracts"] = compile_contracts(plan, manifests)
    owners = {"previous": "alice", "next": "bob"}
    async def owner(session, workspace, run_id):
        return owners[run_id]
    monkeypatch.setattr(plan_reuse, "source_owner", owner)
    inventory = [{"slug": "notion", "allowed_operations": native_operations("notion")}]
    async with database() as session:
        previous = WorkflowRun(id="previous", workspace_id="w", workflow_id="saved", prompt="Read fixture",
            status=RunStatus.completed, inputs={}, plan=plan.model_dump(mode="json"),
            result={"verification": {"status": "verified"}})
        session.add(previous)
        await session.commit()
        run = SimpleNamespace(id="next", workspace_id="w", workflow_id="saved", prompt="Read fixture", inputs={})
        assert await plan_reuse.reuse_saved_plan(session, run, inventory, manifests) is None
        owners["next"] = "alice"
        reused = await plan_reuse.reuse_saved_plan(session, run, inventory, manifests)
        assert reused.planning_artifacts["structure_reused"] is True
        run.inputs = {"changed": True}
        assert await plan_reuse.reuse_saved_plan(session, run, inventory, manifests) is None
        run.inputs = {}
        assert await plan_reuse.reuse_saved_plan(session, run, [{"slug": "notion", "allowed_operations": []}], manifests) is None


async def test_live_release_runner_resumes_receipt_without_duplicate_write(tmp_path, monkeypatch):
    from app import release_evaluation
    monkeypatch.setenv("FIXTURE_CREDS", '{"access_token":"fixture"}')
    async def identity(*args):
        return {"identity": {"id": "dedicated-account"}}
    monkeypatch.setattr(release_evaluation, "verify_oauth_credentials", identity)
    calls = []
    async def execute(self, operation, arguments):
        calls.append(operation)
        return {"id": "page", "properties": {}, "parent": {"page_id": "fixture-parent"}, "archived": False}
    monkeypatch.setattr(release_evaluation.ProviderExecutor, "execute", execute)
    fixtures = [{"id": "case", "connector": "notion", "operation": "notion.page.create",
        "dedicated_test_account": True, "expected_account_id": "dedicated-account",
        "credentials_env": "FIXTURE_CREDS", "arguments": {"parent": {"page_id": "fixture-parent"}, "properties": {}}}]
    ledger, report = tmp_path / "ledger.json", tmp_path / "report.json"
    assert await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert calls == ["notion.page.create", "notion.page.get", "notion.page.get"]
    fixtures[0]["expected_account_id"] = "customer-account"
    assert not await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert len(calls) == 3


async def test_live_release_runner_does_not_repeat_uncertain_write(tmp_path, monkeypatch):
    from app import release_evaluation
    monkeypatch.setenv("FIXTURE_CREDS", '{"access_token":"fixture"}')
    async def identity(*args):
        return {"identity": {"id": "dedicated-account"}}
    monkeypatch.setattr(release_evaluation, "verify_oauth_credentials", identity)
    calls = []
    async def execute(*args):
        calls.append(True)
        raise TimeoutError("Provider may have committed")
    monkeypatch.setattr(release_evaluation.ProviderExecutor, "execute", execute)
    fixtures = [{"id": "uncertain", "connector": "notion", "operation": "notion.page.create",
        "dedicated_test_account": True, "expected_account_id": "dedicated-account",
        "credentials_env": "FIXTURE_CREDS", "arguments": {"parent": {"page_id": "fixture-parent"}, "properties": {}}}]
    ledger, report = tmp_path / "ledger.json", tmp_path / "report.json"
    assert not await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert not await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert len(calls) == 1
