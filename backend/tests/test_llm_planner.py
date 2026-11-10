"""Direct planning repairs serialization once and never bypasses preflight."""

import json
from pathlib import Path
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
async def test_supplied_content_review_compiles_with_only_aura(malformed_plan_client, monkeypatch):
    from app.native_connectors import planning_catalog

    _, parse = malformed_plan_client
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    prompt = (Path(__file__).parent / "fixtures/content_review_comments.txt").read_text()
    tools = planning_catalog({"aura"}) + [{
        "slug": "segment", "name": "Segment", "connected": False,
        "allowed_operations": ["segment.page"],
    }]
    arguments = {
        "title": "Northstar Learn v03 revision brief", "instructions": prompt,
        "sources": [{"id": "comments", "title": "Supplied fictional review comments", "content": prompt}],
        "synthetic": True,
    }
    compact = CompactWorkflowPlan.model_validate({
        "name": "Content revision brief", "interpretation": "Review supplied comments inside AURA",
        "steps": [{"key": "brief", "agent": "reviewer", "tool_slug": "aura",
                   "operation": "report.compose", "arguments_json": json.dumps(arguments),
                   "reason": "Prepare the requested brief from supplied evidence",
                   "expected_output": "Revision brief with unresolved decisions preserved",
                   "consequential": False, "depends_on": [], "required_evidence": []}],
    })
    parse.return_value = SimpleNamespace(output_parsed=compact)
    result = await orchestrator._create_compiled_plan(prompt, tools, set(), {})

    assert parse.await_count == 1
    payload = json.loads(parse.await_args.kwargs["input"])
    assert {item["slug"] for item in payload["operations"]} == {"aura"}
    assert [(step.tool_slug, step.operation) for step in result.steps] == [("aura", "report.compose")]
    assert result.steps[0].arguments == arguments
    assert result.planning_artifacts["contract_repair_attempts"] == 0
    assert orchestrator.complete_connection_requirements(prompt, [], tools, compiled_plan=result) == []


def json_entries(value):
    def node(item):
        return {"scalar": item if not isinstance(item, (dict, list)) else None,
                "items": [node(child) for child in item] if isinstance(item, list) else None,
                "entries": json_entries(item) if isinstance(item, dict) else None}
    return [{"key": key, "value": node(item)} for key, item in value.items()]


@pytest.fixture
def malformed_plan_client(monkeypatch):
    compact = CompactWorkflowPlan.model_validate({
        "name": "Draft review", "interpretation": "Read and update a draft", "steps": [
            {"key": "read", "agent": "WordPress", "tool_slug": "wordpress",
             "operation": "post.get", "arguments_json": '{"post_id":107}',
             "reason": "Read draft", "expected_output": "Draft", "consequential": False,
             "depends_on": [], "required_evidence": []},
            {"key": "save", "agent": "WordPress", "tool_slug": "wordpress",
             "operation": "post.update", "arguments_json": '{"post_id":107, title:"Demo"}',
             "reason": "Update draft", "expected_output": "Saved draft", "consequential": True,
             "depends_on": ["read"], "required_evidence": []},
        ],
    })
    parse = AsyncMock()

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
    return compact, parse


@pytest.mark.asyncio
async def test_malformed_arguments_get_one_scoped_serialization_repair(malformed_plan_client):
    compact, parse = malformed_plan_client
    repair = llm_planner.PlanJSONRepairs(repairs=[llm_planner.ArgumentJSONRepair(
        step_key="save", arguments=json_entries({"post_id": 107, "title": "Demo"}),
    )])
    parse.side_effect = [SimpleNamespace(output_parsed=compact), SimpleNamespace(output_parsed=repair)]
    schema = {"type": "object", "properties": {"post_id": {"type": "integer"}}}
    result = await llm_planner.create_llm_plan("Update my draft", [{
        "slug": "wordpress", "connected": True,
        "allowed_operations": ["post.get", "post.update"],
        "operation_contracts": [{"name": "post.update", "input_schema": schema}],
    }], set())
    assert parse.await_count == 2
    second = parse.await_args_list[1].kwargs
    assert second["text_format"] is llm_planner.PlanJSONRepairs
    assert json.loads(second["input"])["malformed_arguments"] == [{
        "step_key": "save", "arguments_json": compact.steps[1].arguments_json,
        "input_schema": schema,
    }]
    assert result.steps[0].arguments == {"post_id": 107}
    assert result.steps[1].arguments == {"post_id": 107, "title": "Demo"}
    assert result.steps[1].depends_on == ["read"]
    assert result.steps[1].consequential is True
    assert result.steps[1].operation == "post.update"
    assert compact.steps[1].arguments_json == '{"post_id":107, title:"Demo"}'
    assert result.planning_artifacts["argument_json_repaired_steps"] == ["save"]
    assert "preflight_evaluation" not in result.planning_artifacts


@pytest.mark.asyncio
@pytest.mark.parametrize("graph_error", ["missing", "later", "duplicate", "cycle"])
async def test_compact_graph_failure_uses_compiler_retry_with_rejected_candidate(
    malformed_plan_client, monkeypatch, graph_error,
):
    compact, parse = malformed_plan_client
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    compact.steps[1].arguments_json = '{"post_id":107,"title":"Demo"}'
    rejected = compact.model_copy(deep=True)
    if graph_error == "missing":
        # The production regression: expansion failed before the compiler
        # could provide the omitted dependency to its existing retry.
        rejected.steps[0].key = "meta_campaign_insights"
        rejected.steps[0].depends_on = ["meta_accounts"]
    elif graph_error == "later":
        rejected.steps.reverse()
    elif graph_error == "duplicate":
        rejected.steps[1].key = "read"
    else:
        rejected.steps[0].depends_on = ["save"]
    parse.side_effect = [SimpleNamespace(output_parsed=rejected), SimpleNamespace(output_parsed=compact)]
    manifest = {"capabilities": [{
        "name": operation, "permission_scope": scope,
        "input_schema": {"type": "object", "required": ["post_id"],
                         "properties": {"post_id": {"type": "integer"}, "title": {"type": "string"}}},
    } for operation, scope in [("post.get", "read"), ("post.update", "write")]]}
    inventory = [{"slug": "wordpress", "name": "WordPress", "connected": True,
                  "allowed_operations": ["post.get", "post.update"]}]

    result = await orchestrator._create_compiled_plan(
        "Review my WordPress draft", inventory, {"draft_id"}, {"wordpress": manifest},
    )

    assert parse.await_count == 2
    repair = json.loads(parse.await_args_list[1].kwargs["input"])["reference_repair"]
    assert repair["validation_error"]
    assert repair["available_input_references"] == ["{{inputs.draft_id}}"]
    assert [step["key"] for step in repair["rejected_steps"]] == [step.key for step in rejected.steps]
    assert repair["rejected_steps"][0]["depends_on"] == rejected.steps[0].depends_on
    assert repair["rejected_steps"][0]["arguments"] == json.loads(rejected.steps[0].arguments_json)
    assert result.planning_artifacts["contract_repair_attempts"] == 1
    assert result.steps[1].depends_on == ["read"]
    assert result.steps[1].consequential is True
    assert preflight_plan(result, inventory, {"wordpress": manifest}, {"draft_id"}).fixes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("second_failure", ["graph", "connector"])
async def test_compact_graph_repair_is_bounded_and_still_requires_preflight(
    malformed_plan_client, monkeypatch, second_failure,
):
    compact, parse = malformed_plan_client
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    compact.steps[1].arguments_json = '{"post_id":107,"title":"Demo"}'
    rejected = compact.model_copy(deep=True)
    rejected.steps[0].depends_on = ["missing_read"]
    if second_failure == "connector":
        compact.steps[1].arguments_json = '{"title":"Missing required target"}'
    parse.side_effect = [SimpleNamespace(output_parsed=rejected), SimpleNamespace(
        output_parsed=rejected if second_failure == "graph" else compact,
    )]
    manifest = {"capabilities": [{
        "name": operation, "permission_scope": scope,
        "input_schema": {"type": "object", "required": ["post_id"],
                         "properties": {"post_id": {"type": "integer"}, "title": {"type": "string"}}},
    } for operation, scope in [("post.get", "read"), ("post.update", "write")]]}
    inventory = [{"slug": "wordpress", "name": "WordPress", "connected": True,
                  "allowed_operations": ["post.get", "post.update"]}]

    expected = llm_planner.PlanGraphValidationError if second_failure == "graph" else NativeConnectorError
    with pytest.raises(expected):
        await orchestrator._create_compiled_plan(
            "Review my WordPress draft", inventory, set(), {"wordpress": manifest},
        )
    assert parse.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("repairs", [
    [],
    [{"step_key": "other", "arguments": []}],
    [{"step_key": "save", "arguments": []},
     {"step_key": "save", "arguments": []}],
    [{"step_key": "save", "arguments": json_entries({"title": "First"}) + json_entries({"title": "Second"})}],
])
async def test_invalid_repairs_stop_after_one_attempt(malformed_plan_client, repairs):
    compact, parse = malformed_plan_client
    parse.side_effect = [SimpleNamespace(output_parsed=compact), SimpleNamespace(
        output_parsed=llm_planner.PlanJSONRepairs.model_validate({"repairs": repairs}),
    )]
    with pytest.raises((ValueError, TypeError)):
        await llm_planner.create_llm_plan("Update my draft", [], set())
    assert parse.await_count == 2


@pytest.mark.asyncio
async def test_json_repair_cannot_bypass_normal_schema_validation(malformed_plan_client):
    compact, parse = malformed_plan_client
    parse.side_effect = [SimpleNamespace(output_parsed=compact), SimpleNamespace(
        output_parsed=llm_planner.PlanJSONRepairs.model_validate({"repairs": [{
            "step_key": "save", "arguments": json_entries({"unexpected": "still invalid"}),
        }]}),
    )]
    plan = await llm_planner.create_llm_plan("Update my draft", [], set())
    manifest = {"capabilities": [{
        "name": "post.get", "permission_scope": "read", "input_schema": {"type": "object"},
    }, {
        "name": "post.update", "permission_scope": "write", "input_schema": {
            "type": "object", "required": ["post_id"],
            "properties": {"post_id": {"type": "integer"}}, "additionalProperties": False,
        },
    }]}
    evaluation = preflight_plan(plan, [{
        "slug": "wordpress", "connected": True,
        "allowed_operations": ["post.get", "post.update"],
    }], {"wordpress": manifest}, set())
    assert evaluation.fixes


def test_long_workflow_keeps_supporting_reads_with_a_shared_finite_bound():
    assert CompactWorkflowPlan.model_json_schema()["properties"]["steps"]["maxItems"] == 40
    assert WorkflowPlan.model_json_schema()["properties"]["steps"]["maxItems"] == 40
    steps = [{
        "key": f"read_{index}", "agent": "weather", "tool_slug": "aura",
        "operation": "weather.forecast", "arguments_json": '{"location":"Berlin"}',
        "reason": "Read", "expected_output": "Forecast", "consequential": False,
        "depends_on": [f"read_{prior}" for prior in range(index)], "required_evidence": [],
    } for index in range(40)]
    compact = CompactWorkflowPlan(name="Agency", interpretation="Full workflow", steps=steps)
    expanded = llm_planner._expand_compact_plan(compact)
    assert len(expanded.steps) == 40
    assert len(expanded.result_contract.supporting_step_keys) == 39
    assert len(expanded.steps[-1].depends_on) == 39
    with pytest.raises(ValueError):
        CompactWorkflowPlan(name="Too long", interpretation="Bounded", steps=steps + [steps[0]])


def test_planner_schema_only_describes_a_plan():
    assert set(CompactWorkflowPlan.model_json_schema()["required"]) == {
        "name", "interpretation", "steps",
    }
    assert CompactWorkflowPlan.model_json_schema()["$defs"]["CompactPlanStep"]["properties"]["key"]["pattern"] == r"^[a-z][a-z0-9_]{0,119}$"


@pytest.mark.asyncio
async def test_structured_repair_preserves_sheet_formulas_sources_and_targets(malformed_plan_client):
    compact, parse = malformed_plan_client
    expected = {"sheetId": "{{steps.create.ret.spreadsheetId}}", "worksheetId": 346,
                "rows": [["Revenue", None, 0, '=IF(COUNT(B3:C3)<2,"",C3-B3)'],
                         ["Source", "https://example.com/serum", 'Quoted "name"\nNext line']],
                "options": {"enabled": True, "ratio": 0.026, "empty": [], "object": {}}}
    compact.steps[1].arguments_json = '{"sheetId":"{{steps.create.ret.spreadsheetId}}", rows:[]}'
    parse.side_effect = [SimpleNamespace(output_parsed=compact), SimpleNamespace(
        output_parsed=llm_planner.PlanJSONRepairs.model_validate({"repairs": [{
            "step_key": "save", "arguments": json_entries(expected),
        }]}))]
    result = await llm_planner.create_llm_plan("Prepare a sheet", [], set())
    assert result.steps[1].arguments == expected
    assert parse.await_count == 2
    assert isinstance(result.steps[1].arguments["options"]["enabled"], bool)
    assert isinstance(result.steps[1].arguments["worksheetId"], int)


def test_repair_output_schema_cannot_repeat_malformed_serialized_arguments():
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(llm_planner.PlanJSONRepairs)
    repair = schema["$defs"]["ArgumentJSONRepair"]
    assert repair["properties"]["arguments"]["type"] == "array"
    assert "arguments_json" not in repair["properties"]
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
    with pytest.raises(ValueError, match="one representation"):
        llm_planner.JSONValue(scalar="text", items=[], entries=None)


def test_planning_sheet_rows_are_structured_and_provider_contract_stays_unchanged():
    from copy import deepcopy

    from app.native_connectors import normalize_planned_module_arguments

    module = {"name": "google-sheets.update-multiple-rows", "input_schema": {
        "type": "object", "properties": {"sheetId": {"type": "string"}, "rows": {"type": "string"}},
        "required": ["sheetId", "rows"],
    }}
    original = deepcopy(module)
    payload = {"operations": [{"slug": "google-sheets", "operation_contracts": [module]}]}
    projected = llm_planner._bounded_planning_catalog(payload)
    rows_schema = projected["operations"][0]["operation_contracts"][0]["input_schema"]["properties"]["rows"]
    assert rows_schema["anyOf"][0]["type"] == "array"
    assert rows_schema["anyOf"][1]["pattern"] == r"^\{\{[^{}]+\}\}$"
    rows = [["Revenue", 'A "quoted" label', '=IF(COUNT(B3:C3)<2;"";C3-B3)'],
            ["Source", "https://example.com/report", 0.026]]
    compiled = normalize_planned_module_arguments({"capabilities": [module]}, module["name"],
                                                  {"sheetId": "existing-workbook", "rows": rows})
    assert json.loads(compiled["rows"]) == rows
    assert module == original
    assert payload["operations"][0]["operation_contracts"][0] is module


def test_catalog_format_preserves_mcp_connection_identity_and_rejects_vendor_alias():
    slug = 'agent-semrush-0123456789'
    response_format = llm_planner._catalog_plan_format([
        {'slug': slug, 'name': 'Semrush', 'canonical_provider': 'semrush'},
        {'slug': 'aura', 'name': 'AURA'},
    ])
    schema = response_format.model_json_schema()
    route_schema = schema['$defs']['CatalogPlanStep']['properties']['tool_slug']
    assert set(route_schema['enum']) == {slug, 'aura'}
    payload = {
        'name': 'SEO research', 'interpretation': 'Read Semrush evidence', 'steps': [{
            'key': 'read', 'agent': 'Semrush', 'tool_slug': slug,
            'operation': 'mcp.get_report', 'arguments_json': '{}',
            'reason': 'Read the approved source', 'expected_output': 'Source evidence',
            'consequential': False, 'depends_on': [], 'required_evidence': [],
        }],
    }
    assert response_format.model_validate(payload).steps[0].tool_slug == slug
    payload['steps'][0]['tool_slug'] = 'semrush'
    with pytest.raises(ValueError, match='tool_slug'):
        response_format.model_validate(payload)


@pytest.mark.asyncio
async def test_live_planning_uses_catalog_scoped_route_format(malformed_plan_client):
    compact, parse = malformed_plan_client
    compact.steps = compact.steps[:1]
    parse.return_value = SimpleNamespace(output_parsed=compact)
    await llm_planner.create_llm_plan('Read my WordPress draft', [{
        'slug': 'wordpress', 'name': 'WordPress', 'allowed_operations': ['post.get'],
        'operation_contracts': [],
    }], set())
    response_format = parse.call_args.kwargs['text_format']
    schema = response_format.model_json_schema()
    assert schema['$defs']['CatalogPlanStep0']['properties']['tool_slug']['const'] == 'wordpress'
    assert schema['$defs']['CatalogPlanStep0']['properties']['operation']['const'] == 'post.get'
    assert schema['properties']['steps']['maxItems'] == 40


def test_catalog_format_keeps_each_action_on_its_declared_connector():
    from openai.lib._pydantic import to_strict_json_schema

    inventory = [
        {'slug': 'aura', 'allowed_operations': ['report.compose']},
        {'slug': 'google', 'allowed_operations': ['sheets.read', 'sheets.kpi.create']},
        {'slug': 'google-sheets', 'allowed_operations': ['google-sheets.get-values-in-range']},
        {'slug': 'agent-semrush-0123456789', 'allowed_operations': ['mcp.get_report']},
        {'slug': 'empty', 'allowed_operations': []},
    ]
    response_format = llm_planner._catalog_plan_format(inventory)
    schema = to_strict_json_schema(response_format)
    assert len(schema['properties']['steps']['items']['anyOf']) == 4
    assert schema['additionalProperties'] is False
    payload = {
        'name': 'Pilot', 'interpretation': 'Generate and save feedback', 'steps': [{
            'key': 'compose', 'agent': 'AURA', 'tool_slug': 'aura',
            'operation': 'report.compose', 'arguments_json': '{}',
            'reason': 'Generate feedback', 'expected_output': 'Feedback body',
            'consequential': False, 'depends_on': [], 'required_evidence': [],
        }],
    }
    for item in inventory:
        for operation in item['allowed_operations']:
            payload['steps'][0].update(tool_slug=item['slug'], operation=operation)
            assert response_format.model_validate(payload).steps[0].operation == operation
    # These were valid individual strings but invalid executable pairs in the
    # failed live pilot. Unknown actions and display-name routes also stay out.
    for slug, operation in [
        ('google', 'report.compose'), ('google-sheets', 'sheets.read'),
        ('aura', 'sheets.kpi.create'), ('google', 'get-values-in-range'),
        ('semrush', 'mcp.get_report'), ('empty', 'report.compose'),
    ]:
        payload['steps'][0].update(tool_slug=slug, operation=operation)
        with pytest.raises(ValueError):
            response_format.model_validate(payload)


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
            "name": "Create file", "interpretation": "Create one file", "steps": [{
                "key": "create", "agent": "Google Drive", "tool_slug": "google-drive",
                "operation": "google-drive.create-file",
                "arguments_json": '{"name":"Notes","content":"Project notes."}',
                "reason": "Save the notes", "expected_output": "A Drive file",
                "consequential": True, "depends_on": [], "required_evidence": [],
            }],
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
    # The response schema uses the same reduced catalog, so dropped operations
    # cannot be selected without their argument contract being visible.
    catalog = llm_planner._bounded_planning_catalog(data)["operations"]
    schema = llm_planner._catalog_plan_format(catalog).model_json_schema()
    offered = schema['$defs']['CatalogPlanStep0']['properties']['operation']['enum']
    assert set(offered) == set(item["allowed_operations"])


def test_named_report_platforms_survive_catalog_packing_without_manual_selection():
    google = [{"name": f"google-ads.campaign-report-performance-{i}",
               "description": str(i) + "G" * 4000, "permission_scope": "read",
               "input_schema": {"type": "object", "properties": {}}} for i in range(50)]
    others = [{"slug": slug, "name": label, "canonical_provider": provider, "connected": connected,
               "allowed_operations": [operation], "operation_contracts": [{
                   "name": operation, "description": label + "M" * 30000,
                   "permission_scope": "read", "input_schema": {"type": "object", "properties": {}}}]}
              for slug, label, provider, connected, operation in [
                  ("agent-meta", "Meta Ads — Pipeboard", "meta-ads", True, "get_insights"),
                  ("reddit-ads", "Reddit Ads", "reddit-ads", False, "reddit-ads.campaigns.list"),
              ]]
    packed = llm_planner._bounded_planning_catalog({
        "request": "Compare Google Ads, Meta Ads, and Reddit Ads campaign performance in a report",
        "selected_tools": [], "required_actions": [],
        "operations": [{"slug": "google-ads", "name": "Google Ads", "connected": True,
                        "allowed_operations": [m["name"] for m in google], "operation_contracts": google}, *others],
    })
    assert all(item["allowed_operations"] for item in packed["operations"])
    assert next(item for item in packed["operations"] if item["slug"] == "agent-meta")["connected"] is True
    assert next(item for item in packed["operations"] if item["slug"] == "reddit-ads")["connected"] is False


def test_large_selected_catalog_retains_exact_requested_generation_and_reads():
    distractors = [{
        "name": f"connector.report.read.compose-{index}",
        "description": str(index) + "X" * 5000,
        "permission_scope": "read",
        "input_schema": {"type": "object", "properties": {}},
    } for index in range(80)]
    named = [
        {"slug": slug, "allowed_operations": [operation], "operation_contracts": [{
            "name": operation, "description": operation + "Y" * 6000,
            "permission_scope": "read", "input_schema": {"type": "object", "properties": {}},
        }]}
        for slug, operation in [("aura", "report.compose"), ("google", "sheets.read")]
    ]
    data = {
        "request": "Call aura:report.compose. Then call google:sheets.read.",
        "required_actions": [],
        "operations": [{"slug": "connector", "allowed_operations": [
            module["name"] for module in distractors
        ], "operation_contracts": distractors}, *named],
    }
    packed = llm_planner._bounded_planning_catalog(data)
    offered = {(item["slug"], operation) for item in packed["operations"]
               for operation in item["allowed_operations"]}
    assert {("aura", "report.compose"), ("google", "sheets.read")} <= offered
    assert len(offered) < 82


def test_selected_sheets_catalog_cannot_crowd_out_required_internet_research():
    distractors = [{
        "name": f"google-sheets.dashboard-template-{index}", "description": str(index) + "X" * 5000,
        "permission_scope": "write", "input_schema": {"type": "object", "properties": {}},
    } for index in range(60)]
    distractors.append({"name": "google-sheets.get-spreadsheet-by-id", "description": "Full metadata including locale",
                        "permission_scope": "read", "input_schema": {"type": "object", "properties": {"sheetId": {"type": "string"}}}})
    research = [{"name": operation, "description": "Research evidence", "permission_scope": "read",
                 "input_schema": {"type": "object", "properties": {}}}
                for operation in ["web.search", "web.page.read", "report.compose"]]
    packed = llm_planner._bounded_planning_catalog({
        "request": "Create a KPI dashboard template in Google Sheets. Find values on the internet.",
        "selected_tools": ["Google Sheets"], "required_actions": [],
        "operations": [
            {"slug": "google-sheets", "name": "Google Sheets", "allowed_operations": [m["name"] for m in distractors],
             "operation_contracts": distractors},
            {"slug": "aura", "allowed_operations": [m["name"] for m in research], "operation_contracts": research},
        ],
    })
    offered = {(item["slug"], operation) for item in packed["operations"]
               for operation in item["allowed_operations"]}
    assert {("aura", operation) for operation in ["web.search", "web.page.read", "report.compose"]} <= offered
    assert ("google-sheets", "google-sheets.get-spreadsheet-by-id") in offered
    assert any(slug == "google-sheets" for slug, _ in offered)
    assert len(offered) < 63


def test_exact_requested_contract_that_cannot_fit_fails_instead_of_substituting():
    from app.model_inputs import ModelInputTooLarge

    data = {
        "request": "Use aura:report.compose to produce the report.", "required_actions": [],
        "operations": [{"slug": "aura", "allowed_operations": ["report.compose"],
                        "operation_contracts": [{"name": "report.compose",
                            "description": "Required contract" + "X" * 100000,
                            "input_schema": {"type": "object", "properties": {}}}]}],
    }
    with pytest.raises(ModelInputTooLarge, match="Required action contracts"):
        llm_planner._bounded_planning_catalog(data)
    data["request"] = "Use aura:report.compose.extra only."
    packed = llm_planner._bounded_planning_catalog(data)
    assert packed["operations"][0]["allowed_operations"] == []


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
    assert issubclass(parse.await_args.kwargs["text_format"], CompactWorkflowPlan)
    assert plan.steps[0].arguments == {"location": "Berlin"}
    assert plan.planning_artifacts["planner_recovery_mode"] == "direct_llm"
    assert "preflight_evaluation" not in plan.planning_artifacts


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
        assert issubclass(schema, CompactWorkflowPlan)
        return SimpleNamespace(output_parsed=schema.model_validate({
            "name": "One Canva slide",
            "interpretation": "Create one slide in Canva",
            "steps": [{
                "key": "slide", "agent": "Canva", "tool_slug": "canva",
                "operation": "canva.presentation.create",
                "arguments_json": '{"title":"A slide","phases":[{"period":"Now","title":"Main point","items":["One idea"]}]}',
                "reason": "Create the requested slide", "expected_output": "Populated slide",
                "consequential": True, "depends_on": [], "required_evidence": [],
            }],
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
    assert calls.await_count == 2


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
async def test_direct_compiler_corrects_an_undeclared_action_before_review(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    valid = WorkflowPlan(name="Read issue", interpretation="Read Jira issue", steps=[
        PlanStep(key="issue", agent="Jira", tool_slug="jira", operation="jira.issue.get",
                 arguments={"issue_id_or_key": "DEMO-1"}, reason="Read the issue",
                 expected_output="Issue"),
    ])
    invalid = valid.model_copy(deep=True)
    invalid.steps[0].operation = "jira"
    calls = AsyncMock(side_effect=[invalid, valid])
    provider = AsyncMock()
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", provider)
    result = await orchestrator._create_compiled_plan(
        "Read Jira issue DEMO-1", [{"slug": "jira", "name": "Jira", "connected": True,
                                   "allowed_operations": ["jira.issue.get"]}],
        set(), {"jira": native_manifest("jira")},
    )
    assert result is valid
    assert calls.await_count == 2
    assert any("not declared" in message for message in calls.await_args_list[1].args[4])
    assert result.planning_artifacts["compiled_contracts"]
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_planner_rejects_omitted_action_after_one_correction(monkeypatch):
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
    assert calls.await_count == 2
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
    assert calls.await_count == 2


@pytest.mark.asyncio
async def test_direct_planner_stops_after_one_failed_correction(monkeypatch):
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
    assert calls.await_count == 2
