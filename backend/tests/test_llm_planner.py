"""The direct planner makes one model call and never bypasses preflight."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_planner, orchestrator
from app.agent_runtime import CompactWorkflowPlan
from app.config import get_settings
from app.native_connectors import NativeConnectorError, native_manifest
from app.plan_preflight import preflight_plan
from app.request_contracts import requested_effects
from app.schemas import PlanStep, WorkflowPlan


@pytest.mark.asyncio
async def test_large_catalog_is_packed_before_the_only_planning_call(monkeypatch):
    prompt = "Create a Google Drive file from my notes: " + "Project notes. " * 1100
    inventory = [{
        "slug": "google-drive", "name": "Google Drive", "connected": True,
        "allowed_operations": ["google-drive.create-file", "google-drive.list-files"],
        "operation_contracts": [
            {"name": "google-drive.create-file", "permission_scope": "write",
             "description": "Create a Drive file", "input_schema": {
                 "type": "object", "required": ["name"], "properties": {
                     "name": {"type": "string"}, "content": {"type": "string"},
                 },
             }, "output_schema": {"description": "receipt" * 12000}},
            {"name": "google-drive.list-files", "permission_scope": "read",
             "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
             "output_schema": {"description": "listing" * 12000}},
        ],
    }]
    captured = []

    async def parse(**kwargs):
        captured.append(json.loads(kwargs["input"]))
        return SimpleNamespace(output_parsed=kwargs["text_format"].model_validate({
            "name": "Create file", "interpretation": "Create one file", "steps": [],
            "required_action_0": {
                "key": "create", "agent": "Google Drive", "tool_slug": "google-drive",
                "operation": "google-drive.create-file",
                "arguments_json": '{"name":"Notes","content":"Project notes."}',
                "reason": "Save the notes", "expected_output": "A Drive file",
                "consequential": True, "depends_on": [], "required_evidence": [],
            },
        }))

    class Client:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(parse=parse)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm_planner, "AsyncOpenAI", Client)
    monkeypatch.setattr(llm_planner, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test", openai_model="test-model", model_call_timeout_seconds=30,
    ))
    effects = [{"effect": "drive create", "targets": [{
        "tool_slug": "google-drive", "operation": "google-drive.create-file",
    }]}]
    result = await llm_planner.create_llm_plan(prompt, inventory, set(), required_effects=effects)

    assert len(captured) == 1
    assert captured[0]["request"] == prompt
    assert captured[0]["required_actions"][0]["targets"] == effects[0]["targets"]
    operation = captured[0]["operations"][0]["operation_contracts"][0]
    assert operation["name"] == "google-drive.create-file"
    assert operation["input_schema"]["required"] == ["name"]
    assert "output_schema" not in operation
    assert result.steps[0].operation == "google-drive.create-file"


def test_huge_schema_annotations_do_not_remove_required_argument_names():
    properties = {f"field_{index}": {"type": "string", "description": str(index) + "D" * 1000}
                  for index in range(110)}
    data = {
        "request": "Create a file in Google Drive", "selected_tools": [],
        "temporal_context": {}, "available_input_names": [], "requirements": [],
        "required_actions": [{"effect": "drive create", "targets": [{
            "tool_slug": "google-drive", "operation": "google-drive.create-file",
        }]}],
        "operations": [{
            "slug": "google-drive", "allowed_operations": ["google-drive.create-file"],
            "operation_contracts": [{
                "name": "google-drive.create-file", "permission_scope": "write",
                "input_schema": {"type": "object", "required": ["field_0"],
                                 "properties": properties},
            }],
        }],
    }
    packed = json.loads(llm_planner._bounded_planning_payload(data))
    schema = packed["operations"][0]["operation_contracts"][0]["input_schema"]
    assert schema["required"] == ["field_0"]
    assert list(schema["properties"]) == list(properties)
    assert schema["properties"]["field_0"] == {"type": "string"}


def test_many_large_operations_keep_required_action_and_valid_catalog():
    modules = [{
        "name": f"connector.action-{index}", "description": str(index) + "X" * 4000,
        "permission_scope": "write", "input_schema": {"type": "object", "properties": {
            "name": {"type": "string"},
        }},
    } for index in range(80)]
    modules[-1]["name"] = "connector.create-file"
    data = {
        "request": "Create a file with connector", "selected_tools": [],
        "temporal_context": {}, "available_input_names": [], "requirements": [],
        "required_actions": [{"effect": "connector create", "targets": [{
            "tool_slug": "connector", "operation": "connector.create-file",
        }]}],
        "operations": [{
            "slug": "connector", "connected": True,
            "allowed_operations": [module["name"] for module in modules],
            "operation_contracts": modules,
        }],
    }
    result = json.loads(llm_planner._bounded_planning_payload(data))
    item = result["operations"][0]
    assert "connector.create-file" in item["allowed_operations"]
    assert set(item["allowed_operations"]) == {
        module["name"] for module in item["operation_contracts"]
    }
    assert len(item["allowed_operations"]) < len(modules)


@pytest.mark.asyncio
async def test_direct_planner_uses_one_structured_call(monkeypatch):
    response = CompactWorkflowPlan.model_validate({
        "name": "Check Berlin forecast", "interpretation": "Get Berlin weather",
        "steps": [{
            "key": "forecast", "agent": "weather", "tool_slug": "aura",
            "operation": "weather.forecast", "arguments_json": '{"location":"Berlin"}',
            "reason": "Read the public forecast", "expected_output": "Forecast",
            "consequential": False, "depends_on": [], "required_evidence": [],
        }],
    })
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=response))

    class Client:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(parse=parse)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm_planner, "AsyncOpenAI", Client)
    monkeypatch.setattr(llm_planner, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test", openai_model="test-model", model_call_timeout_seconds=30,
    ))
    plan = await llm_planner.create_llm_plan(
        "Read Berlin weather", [{"slug": "aura", "connected": True,
                                 "allowed_operations": ["weather.forecast"]}], set(),
    )
    assert parse.await_count == 1
    assert parse.await_args.kwargs["text_format"] is CompactWorkflowPlan
    assert plan.steps[0].arguments == {"location": "Berlin"}
    assert plan.planning_artifacts["planner_recovery_mode"] == "direct_llm"
    assert plan.planning_artifacts["preflight_evaluation"]["permission_scope"] == "read"


@pytest.mark.asyncio
async def test_one_llm_sukkot_plan_qualifies_bare_canva_and_attachment_references(monkeypatch):
    response = CompactWorkflowPlan.model_validate({
        "name": "Sukkot PDF", "interpretation": "Create and email a Sukkot slide",
        "steps": [
            {"key": "create_sukkot_slide", "agent": "Canva", "tool_slug": "canva",
             "operation": "canva.presentation.create",
             "arguments_json": '{"title":"Sukkot","phases":[{"period":"Now","title":"Sukkot","items":["Gather"]}]}',
             "reason": "Create slide", "expected_output": "Populated design", "consequential": True,
             "depends_on": [], "required_evidence": []},
            {"key": "export_sukkot_pdf", "agent": "Canva", "tool_slug": "canva",
             "operation": "canva.export.create",
             "arguments_json": '{"design_id":"{{create_sukkot_slide.job.id}}","format":"pdf"}',
             "reason": "Export PDF", "expected_output": "PDF URL", "consequential": False,
             "depends_on": [], "required_evidence": []},
            {"key": "send_sukkot_email", "agent": "Gmail", "tool_slug": "google",
             "operation": "gmail.send",
             "arguments_json": '{"to":"me","subject":"Sukkot","body":"Slide attached","attachments":[{"filename":"Sukkot.pdf","url":"{{export_sukkot_pdf.job.urls[0]}}"}]}',
             "reason": "Email PDF", "expected_output": "Sent message", "consequential": True,
             "depends_on": [], "required_evidence": []},
        ],
    })
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=response))

    class Client:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(parse=parse)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm_planner, "AsyncOpenAI", Client)
    monkeypatch.setattr(llm_planner, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test", openai_model="test-model", model_call_timeout_seconds=30,
    ))
    manifests = {slug: native_manifest(slug) for slug in ("canva", "google")}
    inventory = [{"slug": slug, "connected": True,
                  "allowed_operations": [item["name"] for item in manifest["capabilities"]]}
                 for slug, manifest in manifests.items()]
    plan = await llm_planner.create_llm_plan(
        "Create a Sukkot slide, export a PDF and email it to me", inventory, set(),
    )

    assert parse.await_count == 1
    assert plan.steps[1].arguments["design_id"] == "{{steps.create_sukkot_slide.job.id}}"
    assert plan.steps[2].arguments["attachments"][0]["url"] == "{{steps.export_sukkot_pdf.job.urls[0]}}"
    assert plan.steps[1].depends_on == ["create_sukkot_slide"]
    assert plan.steps[2].depends_on == ["export_sukkot_pdf"]
    assert preflight_plan(plan, inventory, manifests, set(), inventory).fixes == []


@pytest.mark.asyncio
async def test_connected_google_gmail_route_is_used_before_disconnected_gmail_pack(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    native = native_manifest("google")
    broker = {"capabilities": [{
        "name": "gmail.send-email", "description": "Send an email",
        "permission_scope": "write", "input_schema": {"type": "object"},
    }]}
    inventory = [
        {"slug": "google", "name": "Google Workspace", "connected": True,
         "allowed_operations": [item["name"] for item in native["capabilities"]]},
        {"slug": "gmail", "name": "Gmail", "connected": False,
         "allowed_operations": ["gmail.send-email"]},
    ]
    grants = [{"slug": "google", "allowed_operations": ["gmail.send", "gmail.get"]}]
    candidate = WorkflowPlan(name="Mail", interpretation="Send mail", steps=[
        PlanStep(key="send", agent="Gmail", tool_slug="google", operation="gmail.send",
                 arguments={"to": "me", "body": "Hello"}, reason="Send the message",
                 expected_output="Sent receipt", consequential=True),
    ])
    create = AsyncMock(return_value=candidate)
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)

    result = await orchestrator._create_compiled_plan(
        "Send an email to me through Gmail", inventory, set(),
        {"google": native, "gmail": broker}, connected_inventory=grants,
    )

    assert result is candidate
    assert [item["slug"] for item in create.await_args.args[1]] == ["google"]
    assert create.await_args.args[5] == [{"effect": "gmail send", "targets": [
        {"tool_slug": "google", "operation": "gmail.send"},
    ]}]
    assert preflight_plan(result, inventory, {"google": native, "gmail": broker},
                          set(), grants).missing_grants == {}


@pytest.mark.asyncio
async def test_gmail_pack_stays_available_without_native_send_and_read_grants(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    inventory = [
        {"slug": "google", "name": "Google Workspace", "connected": True,
         "allowed_operations": ["gmail.send", "gmail.get"]},
        {"slug": "gmail", "name": "Gmail", "connected": False,
         "allowed_operations": ["gmail.send-email"]},
    ]
    create = AsyncMock(side_effect=ValueError("Stop after selecting catalog"))
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    with pytest.raises(ValueError, match="Stop after selecting catalog"):
        await orchestrator._create_compiled_plan(
            "Send an email via Gmail", inventory, set(),
            {"google": native_manifest("google"), "gmail": {"capabilities": [{
                "name": "gmail.send-email", "description": "Send an email",
                "permission_scope": "write", "input_schema": {"type": "object"},
            }]}}, connected_inventory=[
                {"slug": "google", "allowed_operations": ["gmail.send"]},
            ],
        )
    assert "gmail" in {item["slug"] for item in create.await_args.args[1]}


@pytest.mark.asyncio
@pytest.mark.parametrize("ready_slug,expected_operation", [
    ("google", "docs.create"),
    ("google-docs", "google-docs.create-document"),
])
async def test_doc_writer_required_action_uses_granted_route(
    monkeypatch, ready_slug, expected_operation,
):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    broker = {"capabilities": [{
        "name": operation, "description": "Create or get a Google Doc",
        "permission_scope": "write" if "create" in operation else "read",
        "input_schema": {"type": "object"},
    } for operation in ("google-docs.create-document", "google-docs.get-document")]}
    inventory = [
        {"slug": "google", "name": "Google Workspace", "connected": True,
         "allowed_operations": ["docs.create", "docs.get", "gmail.send", "gmail.get"]},
        {"slug": "google-docs", "name": "Google Docs", "connected": ready_slug == "google-docs",
         "allowed_operations": ["google-docs.create-document", "google-docs.get-document"]},
    ]
    grants = [
        {"slug": "google", "allowed_operations": [
            "docs.create", "docs.get", "gmail.send", "gmail.get",
        ] if ready_slug == "google" else ["docs.get", "gmail.send", "gmail.get"]},
    ]
    if ready_slug == "google-docs":
        grants.append({"slug": "google-docs", "allowed_operations": [
            "google-docs.create-document", "google-docs.get-document",
        ]})
    create = AsyncMock(side_effect=ValueError("Catalog captured"))
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    with pytest.raises(ValueError, match="Catalog captured"):
        await orchestrator._create_compiled_plan(
            "Create a Google Doc about shorter meetings and email the link to me through Gmail",
            inventory, set(), {"google": native_manifest("google"), "google-docs": broker},
            connected_inventory=grants,
        )
    offered = {operation for item in create.await_args.args[1]
               for operation in item["allowed_operations"]}
    assert expected_operation in offered
    assert {target["operation"] for effect in create.await_args.args[5]
            if effect["effect"] == "docs create" for target in effect["targets"]} == {
        expected_operation,
    }


@pytest.mark.asyncio
async def test_broker_gmail_read_catalog_is_not_hidden_by_native_send_grants(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    inventory = [
        {"slug": "google", "name": "Google Workspace", "connected": True,
         "allowed_operations": ["gmail.send", "gmail.get"]},
        {"slug": "gmail", "name": "Gmail", "connected": False,
         "allowed_operations": ["gmail.list-labels"]},
    ]
    create = AsyncMock(side_effect=ValueError("Catalog captured"))
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    with pytest.raises(ValueError, match="Catalog captured"):
        await orchestrator._create_compiled_plan(
            "Read my Gmail labels", inventory, set(),
            {"google": native_manifest("google"), "gmail": {"capabilities": [{
                "name": "gmail.list-labels", "description": "List labels",
                "permission_scope": "read", "input_schema": {"type": "object"},
            }]}}, connected_inventory=[
                {"slug": "google", "allowed_operations": ["gmail.send", "gmail.get"]},
            ],
        )
    assert "gmail" in {item["slug"] for item in create.await_args.args[1]}


@pytest.mark.asyncio
async def test_single_llm_response_includes_required_canva_creation(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr(get_settings(), "openai_api_key", "test")
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        schema = kwargs["text_format"]
        assert "required_action_0" in schema.model_json_schema()["required"]
        return SimpleNamespace(output_parsed=schema.model_validate({
            "name": "One Canva slide",
            "interpretation": "Create one slide in Canva",
            "steps": [],
            "required_action_0": {
                "key": "slide", "agent": "Canva", "tool_slug": "canva",
                "operation": "canva.presentation.create",
                "arguments_json": '{"title":"A slide","phases":[{"period":"Now","title":"Main point","items":["One idea"]}]}',
                "reason": "Create the requested slide", "expected_output": "Populated slide",
                "consequential": True, "depends_on": [], "required_evidence": [],
            },
        }))

    class Client:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(parse=parse)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm_planner, "AsyncOpenAI", Client)
    manifest = native_manifest("canva")
    inventory = [{"slug": "canva", "name": "Canva", "connected": True,
                  "allowed_operations": [item["name"] for item in manifest["capabilities"]]}]
    assert requested_effects("Create one populated slide in Canva", inventory, {
        "canva": manifest,
    }) == [{"effect": "canva create", "targets": [
        {"tool_slug": "canva", "operation": "canva.presentation.create"},
    ]}]
    plan = await orchestrator._create_compiled_plan(
        "Create one populated slide in Canva",
        inventory,
        set(), {"canva": manifest},
    )
    assert len(calls) == 1
    assert [(step.key, step.operation) for step in plan.steps] == [
        ("slide", "canva.presentation.create")
    ]
    assert plan.planning_artifacts["compiled_contracts"]


@pytest.mark.asyncio
async def test_direct_planner_rejects_unavailable_operation_without_agent_fallback(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    calls = AsyncMock(return_value=WorkflowPlan(name="Wrong", interpretation="Wrong", steps=[
        PlanStep(key="wrong", agent="worker", tool_slug="aura", operation="invented.send",
                 arguments={}, reason="Send", expected_output="Sent", consequential=True)
    ]))
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    with pytest.raises(NativeConnectorError, match="not declared"):
        await orchestrator._create_compiled_plan(
            "Read Berlin weather", [{"slug": "aura", "connected": True,
                                      "allowed_operations": ["weather.forecast"]}],
            set(), {"aura": native_manifest("aura")},
        )
    assert calls.await_count == 1


@pytest.mark.asyncio
async def test_direct_candidate_passes_existing_compiler_and_approval_preflight(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    candidate = WorkflowPlan(name="Weather", interpretation="Read Berlin weather", steps=[
        PlanStep(key="forecast", agent="weather", tool_slug="aura",
                 operation="weather.forecast", arguments={"location": "Berlin"},
                 reason="Read the public forecast", expected_output="Forecast")
    ])
    calls = AsyncMock(return_value=candidate)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    result = await orchestrator._create_compiled_plan(
        "Read Berlin weather", [{"slug": "aura", "connected": True,
                                 "allowed_operations": ["weather.forecast"]}],
        set(), {"aura": native_manifest("aura")},
    )
    assert result is candidate
    assert result.planning_artifacts["compiled_contracts"]
    assert calls.await_count == 1


@pytest.mark.asyncio
async def test_direct_planner_rejects_omitted_requested_action_without_regenerating(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    incomplete = WorkflowPlan(name="Notice", interpretation="Send a Slack message", steps=[
        PlanStep(key="channels", agent="slack", tool_slug="slack",
                 operation="slack.channels.list", arguments={}, reason="Find channel",
                 expected_output="Channels"),
    ])
    calls = AsyncMock(return_value=incomplete)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    inventory = [{"slug": "slack", "name": "Slack", "connected": True,
                  "allowed_operations": ["slack.channels.list", "slack.post"]}]
    with pytest.raises(ValueError, match="slack.post"):
        await orchestrator._create_compiled_plan(
            "Send a Slack message", inventory, set(), {"slack": native_manifest("slack")},
        )
    assert calls.await_count == 1
    assert any("slack.post" in requirement for requirement in calls.await_args.args[4])


@pytest.mark.asyncio
async def test_canva_slide_creation_is_required_before_a_plan_can_start(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    incomplete = WorkflowPlan(name="Sukkot slide", interpretation="Create a Sukkot slide", steps=[
        PlanStep(key="lookup", agent="canva", tool_slug="canva",
                 operation="canva.import.get", arguments={"import_id": "unknown"},
                 reason="Read Canva", expected_output="Read"),
    ])
    calls = AsyncMock(return_value=incomplete)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    manifest = native_manifest("canva")
    with pytest.raises(ValueError, match="canva.presentation.create"):
        await orchestrator._create_compiled_plan(
            "Create a Sukkot slide in Canva",
            [{"slug": "canva", "name": "Canva", "connected": True,
              "allowed_operations": [item["name"] for item in manifest["capabilities"]]}],
            set(), {"canva": manifest},
        )
    assert calls.await_count == 1


@pytest.mark.asyncio
async def test_direct_planner_does_not_correct_failed_plan(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    incomplete = WorkflowPlan(name="Notice", interpretation="Send a Slack message", steps=[
        PlanStep(key="channels", agent="slack", tool_slug="slack",
                 operation="slack.channels.list", reason="Find channel",
                 expected_output="Channels"),
    ])
    calls = AsyncMock(return_value=incomplete)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    with pytest.raises(ValueError, match="slack.post"):
        await orchestrator._create_compiled_plan(
            "Send a Slack message",
            [{"slug": "slack", "name": "Slack", "connected": True,
              "allowed_operations": ["slack.channels.list", "slack.post"]}],
            set(), {"slack": native_manifest("slack")},
        )
    assert calls.await_count == 1
