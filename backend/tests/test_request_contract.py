import json
from pathlib import Path

import pytest

from app import agent_runtime
from app.request_contract import (
    attach_request_graph_proof,
    derive_request_constraints,
    derive_request_requirements,
    missing_runtime_requirement_evidence,
    persisted_request_contract_fixes,
    prove_request_graph,
)
from app.schemas import PlanStep, ResultContract, WorkflowPlan

_HOLDOUTS = json.loads(
    (Path(__file__).parent / "fixtures" / "novel_workflow_holdouts.json").read_text()
)


def _inventory() -> list[dict]:
    return [
        {
            "slug": "transcriber",
            "name": "Voice Lens",
            "allowed_operations": ["audio.transcribe"],
        },
        {
            "slug": "nebula-vault",
            "name": "Nebula Vault",
            "allowed_operations": ["objects.upload", "objects.list"],
        },
        {
            "slug": "pulsechat",
            "name": "PulseChat",
            "allowed_operations": ["messages.send", "messages.list"],
        },
    ]


def _step(
    key: str,
    tool: str,
    operation: str,
    reason: str,
    *,
    depends_on: list[str] | None = None,
    optional: bool = False,
    consequential: bool = False,
    arguments: dict | None = None,
) -> PlanStep:
    return PlanStep(
        key=key,
        agent="workflow",
        tool_slug=tool,
        operation=operation,
        arguments=arguments or {},
        reason=reason,
        expected_output=reason,
        depends_on=depends_on or [],
        optional=optional,
        consequential=consequential,
    )


def _future_app_plan(*, include_notification: bool = True) -> WorkflowPlan:
    steps = [
        _step(
            "transcribe",
            "transcriber",
            "audio.transcribe",
            "Transcribe the launch recording",
        ),
        _step(
            "store",
            "nebula-vault",
            "objects.upload",
            "Store the transcript in Nebula Vault",
            depends_on=["transcribe"],
            consequential=True,
            arguments={"content": "{{steps.transcribe.text}}"},
        ),
    ]
    if include_notification:
        steps.append(
            _step(
                "notify",
                "pulsechat",
                "messages.send",
                "Notify the team through PulseChat",
                depends_on=["store"],
                consequential=True,
                arguments={"body": "{{steps.store.url}}"},
            )
        )
    return WorkflowPlan(
        name="Launch transcript",
        interpretation="Transcribe, store, and notify",
        steps=steps,
    )


def test_prompt_contract_splits_shared_verb_requirements() -> None:
    requirements = derive_request_requirements(
        "Check tomorrow's weather in Berlin and the latest ECB exchange rates.",
        [],
    )

    assert [requirement.action for requirement in requirements] == ["read", "read"]
    assert "weather" in requirements[0].statement.casefold()
    assert "ecb" in requirements[1].statement.casefold()


@pytest.mark.parametrize("case", _HOLDOUTS, ids=lambda case: case["name"])
def test_unfamiliar_holdouts_preserve_semantics_without_special_cases(case) -> None:
    inventory = [
        {
            "slug": "aura",
            "name": "AURA Intelligence",
            "allowed_operations": [
                "web.search",
                "web.page.read",
                "weather.forecast",
            ],
        },
        {
            "slug": "google",
            "name": "Google Workspace",
            "allowed_operations": ["calendar.events.list", "gmail.send"],
        },
    ]

    requirements = derive_request_requirements(case["prompt"], inventory)
    constraints = derive_request_constraints(case["prompt"], inventory)

    assert [item.action for item in requirements] == case["actions"]
    assert not any(_is_exclusion_text(item.statement) for item in requirements)
    assert sorted(
        operation
        for constraint in constraints
        for operation in constraint.forbidden_operations
    ) == sorted(case["forbidden_operations"])


def _is_exclusion_text(value: str) -> bool:
    lowered = value.casefold()
    return any(marker in lowered for marker in ("do not", "never", "avoid", "without"))


def test_exclusions_are_not_promoted_to_required_provider_steps() -> None:
    inventory = [
        {
            "slug": "aura",
            "name": "AURA Intelligence",
            "allowed_operations": [
                "web.search",
                "web.page.read",
                "weather.forecast",
            ],
        }
    ]
    prompt = (
        "Find two official astronomy sources and produce a comparison table. "
        "Do not use weather tools."
    )

    requirements = derive_request_requirements(prompt, inventory)
    constraints = derive_request_constraints(prompt, inventory)

    assert [item.action for item in requirements] == ["read", "synthesize"]
    assert all("Do not" not in item.statement for item in requirements)
    assert len(constraints) == 1
    assert constraints[0].forbidden_provider_slugs == []
    assert constraints[0].forbidden_operations == ["weather.forecast"]


def test_inline_exclusion_does_not_forbid_the_positive_provider() -> None:
    inventory = [
        {
            "slug": "google",
            "name": "Google",
            "allowed_operations": ["gmail.send", "drive.files.create"],
        }
    ]

    constraints = derive_request_constraints(
        "Send the brief through Gmail without saving it to Drive.", inventory
    )

    assert constraints[0].forbidden_operations == ["drive.files.create"]


def test_chat_native_table_is_synthesis_grounded_in_read_steps() -> None:
    inventory = [
        {
            "slug": "aura",
            "name": "AURA Intelligence",
            "allowed_operations": ["web.search", "web.page.read", "weather.forecast"],
        }
    ]
    prompt = (
        "Find the next two total solar eclipses using official astronomy sources. "
        "Extract their dates and durations, calculate the exact difference, and produce "
        "a concise comparison table with source links. Do not use weather tools."
    )
    plan = WorkflowPlan(
        name="Eclipse comparison",
        interpretation="Research and compare the next eclipses",
        steps=[
            _step(
                "search",
                "aura",
                "web.search",
                "Find official astronomy sources for the next two total solar eclipses",
            ),
            _step(
                "read",
                "aura",
                "web.page.read",
                "Read exact eclipse dates and maximum totality durations",
                depends_on=["search"],
                arguments={"url": "{{steps.search.results.0.url}}"},
            ),
        ],
        result_contract=ResultContract(
            primary_step_key="read",
            supporting_step_keys=["search"],
        ),
    )

    proof = prove_request_graph(prompt, plan, inventory)

    assert proof.fixes == []
    assert [item.action for item in proof.requirements] == [
        "read",
        "synthesize",
        "synthesize",
        "synthesize",
    ]
    assert proof.constraints[0].forbidden_operations == ["weather.forecast"]


def test_explicit_exclusion_rejects_a_forbidden_operation() -> None:
    inventory = [
        {
            "slug": "aura",
            "name": "AURA Intelligence",
            "allowed_operations": ["web.search", "weather.forecast"],
        }
    ]
    plan = WorkflowPlan(
        name="Wrong tool",
        interpretation="Use a forbidden tool",
        steps=[
            _step(
                "weather",
                "aura",
                "weather.forecast",
                "Use weather for astronomy research",
            )
        ],
    )

    proof = prove_request_graph(
        "Find an astronomy source. Do not use weather tools.",
        plan,
        inventory,
    )

    assert any("explicit exclusion" in fix for fix in proof.fixes)


def test_source_backed_canva_creation_requires_grounded_upstream_reads() -> None:
    inventory = [
        {
            "slug": "aura",
            "name": "AURA Intelligence",
            "allowed_operations": ["web.search", "web.page.read"],
        },
        {
            "slug": "canva",
            "name": "Canva",
            "allowed_operations": ["canva.designs.list", "canva.presentation.create"],
            "operation_contracts": [
                {
                    "name": "canva.designs.list",
                    "description": "Find Canva designs.",
                    "capability_tags": ["design_metadata"],
                },
                {
                    "name": "canva.presentation.create",
                    "description": "Create a populated Canva presentation.",
                    "capability_tags": ["write_receipt"],
                },
            ],
        },
    ]
    prompt = (
        "Using official NASA sources, create a concise 3-slide Canva presentation "
        "comparing Voyager 1 and Voyager 2 launch dates and primary destinations. "
        "Include source links."
    )
    incomplete = WorkflowPlan(
        name="Voyager comparison",
        interpretation="Create a sourced comparison in Canva",
        steps=[
            _step(
                "search_canva",
                "canva",
                "canva.designs.list",
                "Find Canva designs even though this cannot retrieve NASA sources",
            ),
            _step(
                "create_deck",
                "canva",
                "canva.presentation.create",
                "Create a Canva comparison with NASA source-link placeholders",
                depends_on=["search_canva"],
                consequential=True,
            )
        ],
    )

    incomplete_proof = prove_request_graph(prompt, incomplete, inventory)

    assert incomplete_proof.requirements[0].action == "read"
    assert "create" in [item.action for item in incomplete_proof.requirements]
    assert any("no compatible read action" in fix for fix in incomplete_proof.fixes)

    complete = WorkflowPlan(
        name="Voyager comparison",
        interpretation="Research NASA and create a sourced comparison in Canva",
        steps=[
            _step(
                "search_sources",
                "aura",
                "web.search",
                "Find official NASA Voyager launch and destination sources",
            ),
            _step(
                "read_source",
                "aura",
                "web.page.read",
                "Read NASA Voyager launch dates, destinations, and source links",
                depends_on=["search_sources"],
            ),
            _step(
                "create_deck",
                "canva",
                "canva.presentation.create",
                "Create the sourced Canva Voyager comparison presentation",
                depends_on=["read_source"],
                consequential=True,
            ),
        ],
        result_contract=ResultContract(
            primary_step_key="create_deck",
            supporting_step_keys=["search_sources", "read_source"],
        ),
    )

    inventory[0]["operation_contracts"] = [
        {
            "name": "web.search",
            "description": "Search public sources.",
            "capability_tags": ["public_search_results"],
        },
        {
            "name": "web.page.read",
            "description": "Read a public source page.",
            "capability_tags": ["public_page_content"],
        },
    ]

    assert prove_request_graph(prompt, complete, inventory).fixes == []


def test_future_connectors_receive_provider_agnostic_graph_proof() -> None:
    prompt = (
        "Transcribe the launch recording, store the transcript in Nebula Vault, "
        "and notify the team through PulseChat."
    )
    plan = _future_app_plan()

    assert attach_request_graph_proof(prompt, plan, _inventory()) == []
    contract = plan.planning_artifacts["request_contract"]
    assert len(contract["requirements"]) == 3
    assert {item["requirement_key"] for item in contract["evidence"]} == {
        "requirement_1",
        "requirement_2",
        "requirement_3",
    }


def test_future_provider_delivery_cannot_disappear_from_plan() -> None:
    prompt = (
        "Transcribe the launch recording, store the transcript in Nebula Vault, "
        "and notify the team through PulseChat."
    )

    proof = prove_request_graph(prompt, _future_app_plan(include_notification=False), _inventory())

    assert any("PulseChat" in fix for fix in proof.fixes)
    assert any("requested provider destination" in fix for fix in proof.fixes)


def test_wrong_provider_action_does_not_count_as_coverage() -> None:
    prompt = "Publish the launch transcript in Nebula Vault."
    plan = WorkflowPlan(
        name="Read vault",
        interpretation="Read instead of publish",
        steps=[
            _step(
                "read",
                "nebula-vault",
                "objects.list",
                "Read the launch transcript from Nebula Vault",
            )
        ],
    )

    proof = prove_request_graph(prompt, plan, _inventory())

    assert any("compatible publish action" in fix for fix in proof.fixes)


def test_explicit_quality_constraints_cannot_silently_disappear() -> None:
    prompt = "Create an editable report with exact values in Nebula Vault."
    plan = WorkflowPlan(
        name="Generic report",
        interpretation="Create a report",
        steps=[
            _step(
                "store",
                "nebula-vault",
                "objects.upload",
                "Create and store the report in Nebula Vault",
                consequential=True,
            )
        ],
    )

    proof = prove_request_graph(prompt, plan, _inventory())

    assert any("drops explicit constraints" in fix for fix in proof.fixes)
    assert any("editable" in fix and "exact" in fix for fix in proof.fixes)


def test_optional_or_disconnected_steps_cannot_prove_required_outcomes() -> None:
    prompt = "Notify the team through PulseChat."
    optional = WorkflowPlan(
        name="Optional notice",
        interpretation="Optional notice",
        steps=[
            _step(
                "read",
                "transcriber",
                "audio.transcribe",
                "Transcribe the launch recording",
            ),
            _step(
                "notify",
                "pulsechat",
                "messages.send",
                "Notify the team through PulseChat",
                optional=True,
                consequential=True,
            ),
        ],
        result_contract=ResultContract(primary_step_key="read"),
    )

    proof = prove_request_graph(prompt, optional, _inventory())

    assert any("optional steps" in fix for fix in proof.fixes)
    assert any("disconnected from the final result graph" in fix for fix in proof.fixes)


def test_runtime_verification_requires_every_proof_step_receipt() -> None:
    prompt = (
        "Transcribe the launch recording, store the transcript in Nebula Vault, "
        "and notify the team through PulseChat."
    )
    plan = _future_app_plan()
    assert attach_request_graph_proof(prompt, plan, _inventory()) == []
    artifacts = [
        {"step_key": "transcribe", "critic": {"action": "accept"}},
        {"step_key": "store", "critic": {"action": "accept"}},
    ]

    assert missing_runtime_requirement_evidence(
        plan.model_dump(mode="json"), artifacts
    ) == ["requirement_3"]


def test_persisted_proof_cannot_survive_a_dropped_graph_step() -> None:
    prompt = (
        "Transcribe the launch recording, store the transcript in Nebula Vault, "
        "and notify the team through PulseChat."
    )
    plan = _future_app_plan()
    assert attach_request_graph_proof(prompt, plan, _inventory()) == []
    plan.steps = plan.steps[:-1]

    fixes = persisted_request_contract_fixes(plan)

    assert any("missing steps for requirement_3" in fix for fix in fixes)


def test_original_multi_app_failure_has_complete_generic_proof() -> None:
    prompt = (
        "Check tomorrow's weather in Berlin and the latest ECB exchange rates. "
        "Create an editable Canva report with the exact values, export it as a PDF "
        "to Google Drive, publish the report in Notion, create a Jira issue, and "
        "email the final result through Gmail."
    )
    inventory = [
        {
            "slug": "aura",
            "name": "AURA",
            "allowed_operations": ["weather.forecast", "web.search"],
        },
        {
            "slug": "canva",
            "name": "Canva",
            "allowed_operations": [
                "canva.presentation.create",
                "canva.export.create",
            ],
        },
        {
            "slug": "google",
            "name": "Google Workspace",
            "allowed_operations": ["drive.files.create", "gmail.send"],
        },
        {
            "slug": "notion",
            "name": "Notion",
            "allowed_operations": ["notion.page.create"],
        },
        {
            "slug": "jira",
            "name": "Jira",
            "allowed_operations": ["jira.issue.create"],
        },
    ]
    plan = WorkflowPlan(
        name="Berlin report",
        interpretation="Complete every requested report destination",
        steps=[
            _step(
                "weather",
                "aura",
                "weather.forecast",
                "Check tomorrow's weather in Berlin",
            ),
            _step(
                "ecb",
                "aura",
                "web.search",
                "Check the latest ECB exchange rates",
            ),
            _step(
                "canva",
                "canva",
                "canva.presentation.create",
                "Create an editable Canva report with the exact values",
                depends_on=["weather", "ecb"],
                consequential=True,
            ),
            _step(
                "pdf",
                "canva",
                "canva.export.create",
                "Export the report as a PDF",
                depends_on=["canva"],
                arguments={"format": "pdf"},
            ),
            _step(
                "drive",
                "google",
                "drive.files.create",
                "Upload the exported PDF to Google Drive",
                depends_on=["pdf"],
                consequential=True,
            ),
            _step(
                "notion",
                "notion",
                "notion.page.create",
                "Publish the report in Notion",
                depends_on=["canva"],
                consequential=True,
            ),
            _step(
                "jira",
                "jira",
                "jira.issue.create",
                "Create the requested Jira issue",
                depends_on=["notion"],
                consequential=True,
            ),
            _step(
                "gmail",
                "google",
                "gmail.send",
                "Email the final result through Gmail",
                depends_on=["drive", "notion", "jira"],
                consequential=True,
            ),
        ],
    )

    proof = prove_request_graph(prompt, plan, inventory)

    assert proof.fixes == []
    assert len(proof.requirements) == 7
    assert len(proof.evidence) == 7


@pytest.mark.asyncio
async def test_final_verifier_fails_closed_before_model_when_receipt_is_missing(
    monkeypatch,
) -> None:
    prompt = (
        "Transcribe the launch recording, store the transcript in Nebula Vault, "
        "and notify the team through PulseChat."
    )
    plan = _future_app_plan()
    assert attach_request_graph_proof(prompt, plan, _inventory()) == []

    async def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("Missing deterministic proof must stop before model review")

    monkeypatch.setattr(agent_runtime, "_run", unexpected_model_call)
    result = await agent_runtime.verify_outcome(
        prompt,
        plan.model_dump(mode="json"),
        [
            {
                "step_id": "receipt-1",
                "step_key": "transcribe",
                "critic": {"action": "accept"},
            },
            {
                "step_id": "receipt-2",
                "step_key": "store",
                "critic": {"action": "accept"},
            },
        ],
    )

    assert result.status == "unverified"
    assert result.required_fixes == [
        "Complete preserved requirement evidence for: requirement_3"
    ]
