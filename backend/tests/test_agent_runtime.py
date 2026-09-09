import asyncio
from types import SimpleNamespace

from app import agent_runtime
from app.agent_runtime import (
    autonomous_resource_resolution_context,
    create_plan,
    critique_step,
    deterministic_plan_fixes,
    materialize_action_arguments,
    normalize_plan_graph,
    prepare_execution_directive,
    supervise_execution,
    supervise_plan,
    synthesize_result,
)
from app.schemas import (
    ExecutionDirective,
    ExecutionSupervision,
    ObjectiveSpec,
    PlanStep,
    PlanSupervisionDecision,
    StepDelegation,
    ToolSelection,
    ToolsetProposal,
    WorkflowPlan,
)


def plan(*steps: PlanStep) -> WorkflowPlan:
    return WorkflowPlan(name="Test", interpretation="Test", steps=list(steps))


def agent_settings() -> SimpleNamespace:
    return SimpleNamespace(
        agent_managed_execution_enabled=True,
        openai_api_key="configured",
        openai_model="test-model",
    )


def approved_read_plan() -> dict:
    return plan(
        PlanStep(
            key="read_records",
            agent="data",
            tool_slug="crm",
            operation="records.read",
            arguments={"limit": 10},
            reason="Retrieve records",
            expected_output="CRM records",
        )
    ).model_dump(mode="json")


def test_senior_orchestrator_assigns_every_incomplete_step(monkeypatch) -> None:
    async def fake_run(*_args, **_kwargs):
        return ExecutionSupervision(
            action="continue",
            reason="The approved work is ready",
            delegations=[
                StepDelegation(
                    step_key="read_records",
                    execution_agent="CRM Execution Agent",
                    tool_slug="crm",
                    operation="records.read",
                )
            ],
        )

    monkeypatch.setattr(agent_runtime, "get_settings", agent_settings)
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    decision, source = asyncio.run(
        supervise_execution(
            "Read CRM records",
            approved_read_plan(),
            [{"key": "read_records", "status": "pending"}],
        )
    )

    assert source == "agent"
    assert [item.step_key for item in decision.delegations] == ["read_records"]
    assert decision.delegations[0].execution_agent == "CRM Execution Agent"


def test_senior_orchestrator_cannot_retarget_an_approved_step(monkeypatch) -> None:
    async def fake_run(*_args, **_kwargs):
        return ExecutionSupervision(
            action="continue",
            reason="Use another connector",
            delegations=[
                StepDelegation(
                    step_key="read_records",
                    execution_agent="Other Execution Agent",
                    tool_slug="unapproved-crm",
                    operation="records.read",
                )
            ],
        )

    monkeypatch.setattr(agent_runtime, "get_settings", agent_settings)
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    decision, source = asyncio.run(
        supervise_execution(
            "Read CRM records",
            approved_read_plan(),
            [{"key": "read_records", "status": "pending"}],
        )
    )

    assert source == "deterministic_fallback"
    assert decision.delegations[0].tool_slug == "crm"
    assert decision.delegations[0].operation == "records.read"


def test_execution_agent_triggers_the_exact_approved_call(monkeypatch) -> None:
    async def fake_run(*_args, **_kwargs):
        return ExecutionDirective(
            action="execute",
            step_key="read_records",
            tool_slug="crm",
            operation="records.read",
            arguments={"limit": 10},
            reason="The call matches the approved step",
        )

    monkeypatch.setattr(agent_runtime, "get_settings", agent_settings)
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    directive, source = asyncio.run(
        prepare_execution_directive(
            "Read CRM records",
            approved_read_plan()["steps"][0],
            {"limit": 10},
            "CRM Execution Agent",
        )
    )

    assert source == "agent"
    assert directive.action == "execute"
    assert directive.arguments == {"limit": 10}


def test_execution_agent_cannot_expand_approved_arguments(monkeypatch) -> None:
    async def fake_run(*_args, **_kwargs):
        return ExecutionDirective(
            action="execute",
            step_key="read_records",
            tool_slug="crm",
            operation="records.read",
            arguments={"limit": 1000},
            reason="Read more",
        )

    monkeypatch.setattr(agent_runtime, "get_settings", agent_settings)
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    directive, source = asyncio.run(
        prepare_execution_directive(
            "Read CRM records",
            approved_read_plan()["steps"][0],
            {"limit": 10},
            "CRM Execution Agent",
        )
    )

    assert source == "deterministic_fallback"
    assert directive.action == "execute"
    assert directive.arguments == {"limit": 10}


def test_execution_agent_can_escalate_instead_of_dispatching(monkeypatch) -> None:
    async def fake_run(*_args, **_kwargs):
        return ExecutionDirective(
            action="escalate",
            step_key="read_records",
            tool_slug="crm",
            operation="records.read",
            arguments={"limit": 10},
            reason="The destination is ambiguous",
        )

    monkeypatch.setattr(agent_runtime, "get_settings", agent_settings)
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    directive, source = asyncio.run(
        prepare_execution_directive(
            "Read CRM records",
            approved_read_plan()["steps"][0],
            {"limit": 10},
            "CRM Execution Agent",
        )
    )

    assert source == "agent"
    assert directive.action == "escalate"


def test_senior_orchestrator_reviews_a_valid_plan(monkeypatch) -> None:
    async def fake_run(*_args, **_kwargs):
        return PlanSupervisionDecision(
            action="approve",
            reason="The plan is bounded and executable",
        )

    monkeypatch.setattr(agent_runtime, "get_settings", agent_settings)
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    workflow = WorkflowPlan.model_validate(approved_read_plan())
    decision, source = asyncio.run(
        supervise_plan(
            "Read CRM records",
            ObjectiveSpec(goal="Read CRM records"),
            ToolsetProposal(
                tools=[
                    ToolSelection(
                        slug="crm",
                        role="source",
                        rationale="Contains the requested records",
                    )
                ]
            ),
            workflow,
        )
    )

    assert source == "agent"
    assert decision.action == "approve"


def test_synthesizer_schema_is_accepted_by_the_real_agents_sdk():
    from agents import AgentOutputSchema
    agent = agent_runtime.build_agents()["synthesizer"]
    schema = AgentOutputSchema(agent.output_type).json_schema()
    assert schema["$defs"]["ClaimEvidence"]["additionalProperties"] is False


def test_deterministic_validator_accepts_allow_listed_read() -> None:
    workflow = plan(
        PlanStep(
            agent="data",
            tool_slug="crm",
            operation="records.read",
            reason="Retrieve records",
            expected_output="A list of records",
        )
    )
    inventory = [{"slug": "crm", "allowed_operations": ["records.read"]}]

    assert deterministic_plan_fixes(workflow, inventory) == []


def test_resource_resolution_context_prefers_safe_discovery_over_user_ids() -> None:
    workflow = plan(
        PlanStep(
            key="read_sheet",
            agent="data",
            tool_slug="google",
            operation="sheets.read",
            arguments={"spreadsheet_id": "{{inputs.creator_outreach_sheet_id}}"},
            reason="Read the named sheet",
            expected_output="Spreadsheet rows",
        )
    )
    inventory = [
        {
            "slug": "google",
            "allowed_operations": ["drive.files.search"],
            "operation_contracts": [
                {
                    "name": "drive.files.search",
                    "permission_scope": "read",
                    "input_schema": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ],
        }
    ]

    context = autonomous_resource_resolution_context(workflow, inventory, set())

    assert context["unavailable_input_references"] == [
        "inputs.creator_outreach_sheet_id"
    ]
    assert context["eligible_read_only_discovery_operations"] == [
        {
            "tool_slug": "google",
            "operation": "drive.files.search",
            "required_arguments": ["query"],
        }
    ]
    assert "do not invent an input" in context["required_behavior"]


def test_create_plan_repairs_named_resource_ids_with_discovery(monkeypatch) -> None:
    calls = []

    async def fake_run(agent, payload, max_turns=8):
        calls.append(payload)
        if len(calls) == 1:
            return {
                "objective": {"goal": "Read Creator Outreach"},
                "toolset": {
                    "tools": [
                        {
                            "slug": "google",
                            "role": "source",
                            "rationale": "Find and read the sheet",
                        },
                    ]
                },
                "plan": {
                    "name": "Read Creator Outreach",
                    "interpretation": "Read the named spreadsheet",
                    "steps": [
                        {
                            "key": "read_sheet",
                            "agent": "data",
                            "tool_slug": "google",
                            "operation": "sheets.read",
                            "arguments": {
                                "spreadsheet_id": "{{inputs.creator_outreach_sheet_id}}"
                            },
                            "reason": "Read the named spreadsheet",
                            "expected_output": "Spreadsheet rows",
                        }
                    ],
                },
            }

        resolution = payload["autonomous_resource_resolution"]
        assert resolution["unavailable_input_references"] == [
            "inputs.creator_outreach_sheet_id"
        ]
        assert resolution["eligible_read_only_discovery_operations"][0]["operation"] == (
            "drive.files.search"
        )
        return {
            "objective": {"goal": "Read Creator Outreach"},
            "toolset": {
                "tools": [
                    {
                        "slug": "google",
                        "role": "source",
                        "rationale": "Find and read the sheet",
                    },
                ]
            },
            "plan": {
                "name": "Read Creator Outreach",
                "interpretation": "Discover and read the named spreadsheet",
                "steps": [
                    {
                        "key": "find_sheet",
                        "agent": "data",
                        "tool_slug": "google",
                        "operation": "drive.files.search",
                        "arguments": {"query": "Creator Outreach"},
                        "reason": "Resolve the named spreadsheet",
                        "expected_output": "Matching files with IDs",
                    },
                    {
                        "key": "read_sheet",
                        "agent": "data",
                        "tool_slug": "google",
                        "operation": "sheets.read",
                        "arguments": {
                            "spreadsheet_id": "{{steps.find_sheet.files.0.id}}"
                        },
                        "reason": "Read the exact discovered spreadsheet",
                        "expected_output": "Spreadsheet rows",
                    },
                ],
            },
        }

    inventory = [
        {
            "slug": "google",
            "allowed_operations": ["drive.files.search", "sheets.read"],
            "connected": True,
            "operation_contracts": [
                {
                    "name": "drive.files.search",
                    "permission_scope": "read",
                    "input_schema": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ],
        },
    ]

    monkeypatch.setattr(agent_runtime, "build_agents", lambda: {"planner": object()})
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    result = asyncio.run(create_plan("Read Creator Outreach", inventory, set()))

    assert len(calls) == 2
    assert result.steps[0].operation == "drive.files.search"
    assert result.steps[1].depends_on == ["find_sheet"]
    assert "inputs." not in str(result.model_dump(mode="json"))


def test_preflight_rejects_narrative_placeholder_assigned_to_real_provider():
    workflow = plan(PlanStep(key="summarize_blocks", agent="reader", tool_slug="notion",
        operation="notion.page.get", arguments={"page_id": "page-1"},
        reason="Internal summary only", optional=True,
        expected_output="No tool call; summary will be produced from retrieved blocks only in post-processing."))
    fixes = deterministic_plan_fixes(workflow, [{"slug": "notion", "allowed_operations": ["notion.page.get"]}])
    assert any("narrative placeholder" in fix for fix in fixes)


def test_preflight_does_not_treat_quoted_record_content_as_a_placeholder():
    workflow = plan(PlanStep(key="read", agent="reader", tool_slug="notion",
        operation="notion.page.get", arguments={"page_id": "page-1"},
        reason="Read a page named No tool call", expected_output="A page titled No tool call"))
    assert deterministic_plan_fixes(workflow, [{"slug": "notion", "allowed_operations": ["notion.page.get"]}]) == []


def test_deterministic_validator_blocks_unavailable_operation() -> None:
    workflow = plan(
        PlanStep(
            agent="communications",
            tool_slug="slack",
            operation="slack.delete",
            reason="Remove a message",
            expected_output="Deleted message receipt",
            consequential=True,
        )
    )
    inventory = [{"slug": "slack", "allowed_operations": ["slack.post"]}]

    fixes = deterministic_plan_fixes(workflow, inventory)

    assert any("not allow-listed" in fix for fix in fixes)


def test_deterministic_validator_requires_write_approval() -> None:
    workflow = plan(
        PlanStep(
            agent="communications",
            tool_slug="slack",
            operation="slack.post",
            reason="Post an update",
            expected_output="Posted message receipt",
            consequential=False,
        )
    )
    inventory = [{"slug": "slack", "allowed_operations": ["slack.post"]}]

    assert deterministic_plan_fixes(workflow, inventory) == [
        "Step 1 must be marked consequential"
    ]


def test_deterministic_validator_rejects_unavailable_fallback() -> None:
    workflow = plan(
        PlanStep(
            agent="data",
            tool_slug="crm",
            operation="records.read",
            reason="Read records",
            expected_output="Records",
            fallback_tool_slug="backup",
            fallback_operation="records.read",
        )
    )
    inventory = [{"slug": "crm", "allowed_operations": ["records.read"]}]

    assert any(
        "unavailable fallback" in fix
        for fix in deterministic_plan_fixes(workflow, inventory)
    )


def test_output_variable_references_infer_prior_step_dependencies() -> None:
    workflow = plan(
        PlanStep(
            key="weather",
            agent="data",
            tool_slug="aura",
            operation="weather.forecast",
            reason="Check the weather",
            expected_output="Forecast",
        ),
        PlanStep(
            key="email",
            agent="communications",
            tool_slug="google",
            operation="gmail.send",
            reason="Send the forecast",
            expected_output="Sent message",
            consequential=True,
            output_variables={"forecast": "{{steps.weather.output}}"},
        ),
    )

    normalized = normalize_plan_graph(workflow)

    assert normalized.steps[1].depends_on == ["weather"]


def test_output_variable_self_reference_does_not_require_dependency() -> None:
    workflow = plan(
        PlanStep(
            key="weather",
            agent="data",
            tool_slug="aura",
            operation="weather.forecast",
            reason="Check the weather",
            expected_output="Forecast",
            output_variables={"forecast": "{{steps.weather.output}}"},
        )
    )
    inventory = [{"slug": "aura", "allowed_operations": ["weather.forecast"]}]

    assert deterministic_plan_fixes(workflow, inventory) == []


def test_critic_outage_does_not_repeat_a_successful_provider_action(monkeypatch) -> None:
    calls = 0

    async def fail_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary structured-output outage")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_runtime, "_run", fail_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)

    decision = asyncio.run(
        critique_step(
            {"operation": "gmail.send", "expected_output": "message id"},
            {"id": "sent-message"},
        )
    )

    assert calls == 3
    assert decision.action == "escalate"


def test_synthesis_outage_preserves_evidence_without_claiming_success(monkeypatch) -> None:
    async def fail_run(*_args, **_kwargs):
        raise RuntimeError("temporary structured-output outage")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_runtime, "_run", fail_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)

    result = asyncio.run(
        synthesize_result(
            "Send tomorrow's weather to me",
            [
                {
                    "step_id": "weather-step",
                    "operation": "weather.forecast",
                    "provider_result": {"summary": "Sunny, 18°C"},
                }
            ],
        )
    )

    assert result.validation_passed is False
    assert result.required_fixes
    assert result.summary == "Sunny, 18°C"
    assert result.deliverable == "• Sunny, 18°C"
    assert result.traceability[0].step_id == "weather-step"


def test_synthesis_outage_returns_readable_provider_content(monkeypatch) -> None:
    async def fail_run(*_args, **_kwargs):
        raise RuntimeError("temporary structured-output outage")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_runtime, "_run", fail_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)

    result = asyncio.run(
        synthesize_result(
            "Summarize my most recently edited Notion page",
            [
                {
                    "step_id": "page-blocks",
                    "operation": "notion.blocks.children.list",
                    "provider_result": {
                        "object": "list",
                        "request_id": "internal-id",
                        "results": [
                            {
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [
                                        {"plain_text": "Launch the customer pilot next week."}
                                    ]
                                },
                            },
                            {
                                "type": "bulleted_list_item",
                                "bulleted_list_item": {
                                    "rich_text": [
                                        {"plain_text": "Confirm the onboarding checklist."}
                                    ]
                                },
                            },
                        ],
                    },
                }
            ],
        )
    )

    assert result.summary == "Launch the customer pilot next week."
    assert "• Launch the customer pilot next week." in result.deliverable
    assert "• Confirm the onboarding checklist." in result.deliverable
    assert "internal-id" not in result.deliverable


def test_materializer_retries_and_returns_concrete_approval_arguments(monkeypatch) -> None:
    calls = 0

    async def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"arguments": {"summary": "{{steps.notes.item_1_summary}}"}}
        return {
            "arguments": {
                "project_key": "AURA",
                "summary": "Confirm onboarding checklist",
                "description": "Prepare the checklist from the accepted Notion notes.",
            }
        }

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_runtime, "_run", fake_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)

    arguments = asyncio.run(
        materialize_action_arguments(
            "Turn my research notes into Jira tasks",
            {"key": "create_task_1", "operation": "jira.issue.create"},
            {
                "steps": {
                    "notes": {"results": [{"plain_text": "Confirm onboarding checklist"}]},
                    "projects": {"results": [{"key": "AURA"}]},
                }
            },
        )
    )

    assert calls == 2
    assert arguments["project_key"] == "AURA"
    assert "{{" not in str(arguments)


def test_materializer_exhausts_recovery_without_exposing_model_output(monkeypatch) -> None:
    async def fake_run(*_args, **_kwargs):
        return {"arguments": {"to": "{{inputs.recipient}}"}}

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_runtime, "_run", fake_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)

    try:
        asyncio.run(
            materialize_action_arguments(
                "Send it",
                {"key": "send", "operation": "gmail.send"},
                {"steps": {}},
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "Approval argument recovery exhausted"
    else:
        raise AssertionError("Expected bounded recovery to stop")


def test_materializer_accepts_direct_argument_object_and_indexes_text(monkeypatch) -> None:
    captured = {}

    async def fake_run(_agent, payload, **_kwargs):
        captured.update(payload)
        return {"project_key": "AURA", "summary": "Confirm onboarding checklist"}

    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    arguments = asyncio.run(
        materialize_action_arguments(
            "Create a Jira task from the first action item",
            {
                "key": "create_task",
                "tool_slug": "jira",
                "operation": "jira.issue.create",
            },
            {
                "steps": {
                    "notes": {
                        "results": [
                            {"plain_text": "Confirm onboarding checklist"}
                        ]
                    }
                }
            },
        )
    )

    assert arguments == {
        "project_key": "AURA",
        "summary": "Confirm onboarding checklist",
    }
    assert captured["accepted_text_evidence"] == ["Confirm onboarding checklist"]
    assert captured["required_argument_contract"]["required"] == [
        "project_key",
        "summary",
    ]


def test_create_plan_uses_one_model_round_trip_for_valid_plan(monkeypatch) -> None:
    calls = []

    async def fake_run(agent, payload, max_turns=8):
        calls.append((agent, payload, max_turns))
        return {
            "objective": {"goal": "Read CRM records"},
            "toolset": {
                "tools": [
                    {
                        "slug": "crm",
                        "role": "source",
                        "rationale": "Contains the requested records",
                        "required_permissions": ["records.read"],
                    }
                ]
            },
            "plan": {
                "name": "Read CRM",
                "interpretation": "Read the requested CRM records",
                "steps": [
                    {
                        "key": "read_records",
                        "agent": "data",
                        "tool_slug": "crm",
                        "operation": "records.read",
                        "reason": "Retrieve the records",
                        "expected_output": "CRM records",
                    }
                ],
            },
        }

    monkeypatch.setattr(agent_runtime, "build_agents", lambda: {"planner": object()})
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    result = asyncio.run(
        create_plan(
            "Read CRM records",
            [
                {
                    "slug": "crm",
                    "allowed_operations": ["records.read"],
                    "connected": False,
                }
            ],
        )
    )

    assert len(calls) == 1
    assert calls[0][1]["temporal_context"]["current_time_utc"]
    assert calls[0][1]["temporal_context"]["user_timezone"] is None
    assert result.steps[0].operation == "records.read"
    assert result.planning_artifacts["connection_requirements"] == ["crm"]
    assert result.planning_artifacts["preflight_evaluation"]["passed"] is True


def test_combined_planner_allows_flexible_workflow_arguments() -> None:
    planner = agent_runtime.build_agents()["planner"]

    assert planner.output_type.is_strict_json_schema() is False


def test_staged_planner_agents_allow_flexible_workflow_schemas() -> None:
    agents = agent_runtime.build_agents()

    for key in ("intent", "router", "builder"):
        assert agents[key].output_type.is_strict_json_schema() is False


def test_combined_planner_retries_invalid_json_once(monkeypatch) -> None:
    calls = []

    async def fake_run(agent, payload, max_turns=8):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("Invalid JSON when parsing model output")
        return {
            "objective": {"goal": "Read CRM records"},
            "toolset": {
                "tools": [
                    {"slug": "crm", "role": "source", "rationale": "Reads records"}
                ]
            },
            "plan": {
                "name": "Read CRM",
                "interpretation": "Read the requested CRM records",
                "steps": [
                    {
                        "key": "read_records",
                        "agent": "data",
                        "tool_slug": "crm",
                        "operation": "records.read",
                        "reason": "Retrieve the records",
                        "expected_output": "CRM records",
                    }
                ],
            },
        }

    monkeypatch.setattr(agent_runtime, "build_agents", lambda: {"planner": object()})
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    result = asyncio.run(create_plan("Read CRM records", [
        {"slug": "crm", "allowed_operations": ["records.read"], "connected": True}
    ]))

    assert len(calls) == 2
    assert "response_recovery" in calls[1]
    assert result.steps[0].operation == "records.read"


def test_combined_planner_retries_schema_validation_failure(monkeypatch) -> None:
    calls = []

    async def no_sleep(_delay):
        return None

    async def fake_run(agent, payload, max_turns=8):
        calls.append(payload)
        if len(calls) == 1:
            return {"not": "a planning bundle"}
        return {
            "objective": {"goal": "Read CRM records"},
            "toolset": {
                "tools": [
                    {"slug": "crm", "role": "source", "rationale": "Reads records"}
                ]
            },
            "plan": {
                "name": "Read CRM",
                "interpretation": "Read the requested CRM records",
                "steps": [
                    {
                        "key": "read_records",
                        "agent": "data",
                        "tool_slug": "crm",
                        "operation": "records.read",
                        "reason": "Retrieve the records",
                        "expected_output": "CRM records",
                    }
                ],
            },
        }

    monkeypatch.setattr(agent_runtime, "build_agents", lambda: {"planner": object()})
    monkeypatch.setattr(agent_runtime, "_run", fake_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)

    result = asyncio.run(create_plan("Read CRM records", [
        {"slug": "crm", "allowed_operations": ["records.read"], "connected": True}
    ]))

    assert len(calls) == 2
    assert result.steps[0].operation == "records.read"


def test_create_plan_falls_back_to_staged_agents_after_combined_recovery(monkeypatch) -> None:
    planner = object()
    intent = object()
    router = object()
    builder = object()
    calls = []

    async def no_sleep(_delay):
        return None

    async def fake_run(agent, payload, max_turns=8):
        calls.append(agent)
        if agent is planner:
            raise RuntimeError("combined structured output failed")
        if agent is intent:
            return {"goal": "Turn research notes into Jira tasks"}
        if agent is router:
            return {
                "tools": [
                    {"slug": "notion", "role": "source", "rationale": "Find notes"},
                    {"slug": "jira", "role": "destination", "rationale": "Create tasks"},
                ]
            }
        return {
            "name": "Research notes to Jira",
            "interpretation": "Turn research notes into reviewed Jira tasks",
            "steps": [
                {
                    "key": "find_notes",
                    "agent": "research",
                    "tool_slug": "notion",
                    "operation": "notion.search",
                    "arguments": {"query": "research notes"},
                    "reason": "Find the research notes",
                    "expected_output": "Matching research notes",
                },
                {
                    "key": "create_task",
                    "agent": "delivery",
                    "tool_slug": "jira",
                    "operation": "jira.issue.create",
                    "arguments": {
                        "project_key": "{{inputs.project_key}}",
                        "summary": "{{steps.find_notes.title}}",
                    },
                    "reason": "Create a reviewed Jira task",
                    "expected_output": "Created Jira task",
                    "consequential": True,
                    "depends_on": ["find_notes"],
                },
            ],
        }

    monkeypatch.setattr(
        agent_runtime,
        "build_agents",
        lambda: {"planner": planner, "intent": intent, "router": router, "builder": builder},
    )
    monkeypatch.setattr(agent_runtime, "_run", fake_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)

    result = asyncio.run(
        create_plan(
            "Turn action items from my research notes into Jira tasks",
            [
                {
                    "slug": "notion",
                    "allowed_operations": ["notion.search"],
                    "connected": True,
                },
                {
                    "slug": "jira",
                    "allowed_operations": ["jira.issue.create"],
                    "connected": False,
                },
            ],
        )
    )

    assert calls.count(planner) == 3
    assert calls[-3:] == [intent, router, builder]
    assert result.planning_artifacts["planner_recovery_mode"] == "staged"
    assert result.planning_artifacts["connection_requirements"] == ["jira"]


def test_normalizer_infers_prior_step_dependencies_and_write_safety() -> None:
    workflow = plan(
        PlanStep(
            key="draft_emails",
            agent="writer",
            tool_slug="openai",
            operation="text.generate",
            reason="Draft emails",
            expected_output="Email drafts",
        ),
        PlanStep(
            key="send_emails",
            agent="communications",
            tool_slug="gmail",
            operation="gmail.send",
            arguments={"drafts": "{{steps.draft_emails.items}}"},
            reason="Send approved drafts",
            expected_output="Send receipts",
        ),
    )

    normalized = normalize_plan_graph(workflow)

    assert normalized.steps[1].depends_on == ["draft_emails"]
    assert normalized.steps[1].consequential is True


def test_create_plan_does_not_reprompt_for_mechanical_graph_repairs(monkeypatch) -> None:
    calls = []

    async def fake_run(agent, payload, max_turns=8):
        calls.append(payload)
        return {
            "objective": {"goal": "Draft and send email"},
            "toolset": {
                "tools": [
                    {"slug": "writer", "role": "draft", "rationale": "Writes the draft"},
                    {"slug": "gmail", "role": "send", "rationale": "Sends the email"},
                ]
            },
            "plan": {
                "name": "Draft and send",
                "interpretation": "Draft and send an email",
                "steps": [
                    {
                        "key": "draft_emails", "agent": "writer", "tool_slug": "writer",
                        "operation": "text.generate", "reason": "Draft it", "expected_output": "Drafts",
                    },
                    {
                        "key": "send_emails", "agent": "communications", "tool_slug": "gmail",
                        "operation": "gmail.send", "arguments": {"drafts": "{{steps.draft_emails.items}}"},
                        "reason": "Send it", "expected_output": "Receipts",
                    },
                ],
            },
        }

    monkeypatch.setattr(agent_runtime, "build_agents", lambda: {"planner": object()})
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    result = asyncio.run(create_plan("Draft and send", [
        {"slug": "writer", "allowed_operations": ["text.generate"], "connected": True},
        {"slug": "gmail", "allowed_operations": ["gmail.send"], "connected": True},
    ]))

    assert len(calls) == 1
    assert result.steps[1].depends_on == ["draft_emails"]
    assert result.steps[1].consequential is True
    assert result.planning_artifacts["timings_ms"]["repair"] == 0


def test_planning_clock_resolves_weekdays_across_year_boundary():
    from datetime import datetime, timezone
    context = agent_runtime.planning_temporal_context(datetime(2026, 12, 31, 12, tzinfo=timezone.utc))
    assert context["this_week_dates"]["friday"] == "2027-01-01"
    assert context["next_occurrence_dates"]["monday"] == "2027-01-04"
    assert context["user_timezone"] is None


def test_materializer_repairs_layout_contract_before_returning_for_approval(monkeypatch):
    calls = []
    async def fake_run(agent, payload, **kwargs):
        calls.append(dict(payload))
        items = ["Grounded milestone"] * (6 if len(calls) == 1 else 5)
        return {"arguments": {"title": "Roadmap", "phases": [{"period": "Days 1–30", "title": "Foundation", "items": items}]}}
    async def no_sleep(delay):
        pass
    monkeypatch.setattr(agent_runtime, "_run", fake_run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)
    result = asyncio.run(materialize_action_arguments("Create one roadmap slide",
        {"tool_slug": "canva", "operation": "canva.presentation.create"}, {"steps": {}}))
    assert len(calls) == 2
    assert "at most 5 items" in calls[1]["argument_validation_error"]
    assert len(result["phases"][0]["items"]) == 5
