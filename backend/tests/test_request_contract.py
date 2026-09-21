import pytest

from app import agent_runtime
from app.request_contract import (
    attach_request_graph_proof,
    derive_request_requirements,
    missing_runtime_requirement_evidence,
    persisted_request_contract_fixes,
    prove_request_graph,
)
from app.schemas import PlanStep, ResultContract, WorkflowPlan


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
