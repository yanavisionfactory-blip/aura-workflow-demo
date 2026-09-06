import asyncio

from app import agent_runtime
from app.agent_runtime import (
    create_plan,
    critique_step,
    deterministic_plan_fixes,
    normalize_plan_graph,
    synthesize_result,
)
from app.schemas import PlanStep, WorkflowPlan


def plan(*steps: PlanStep) -> WorkflowPlan:
    return WorkflowPlan(name="Test", interpretation="Test", steps=list(steps))


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
    assert decision.action == "accept"


def test_synthesis_outage_preserves_successful_workflow(monkeypatch) -> None:
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

    assert result.validation_passed is True
    assert result.summary == "Workflow completed successfully."
    assert result.traceability[0]["step_id"] == "weather-step"


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
    assert result.steps[0].operation == "records.read"
    assert result.planning_artifacts["connection_requirements"] == ["crm"]
    assert result.planning_artifacts["preflight_evaluation"]["passed"] is True


def test_combined_planner_allows_flexible_workflow_arguments() -> None:
    planner = agent_runtime.build_agents()["planner"]

    assert planner.output_type.is_strict_json_schema() is False


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
