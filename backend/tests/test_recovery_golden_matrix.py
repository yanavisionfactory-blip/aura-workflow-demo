"""Executable golden matrix for unattended recovery and isolated repair."""

import hashlib
import hmac
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.code_repair_sandbox import send_callback, validate_repair
from app.db import Base
from app.models import ApprovalSnapshot, RunStatus, StepStatus, WorkflowRun, Workspace
from app.native_connectors import native_manifest, native_operations
from app.recovery_engineer import (
    diagnose_run,
    equivalent_substitution_allowed,
    preserve_completed_steps,
    repair_arguments,
    repair_malformed_plan,
    repair_program,
)
from app.run_supervisor import ALLOWED_TRANSITIONS
from app.schemas import PlanStep, WorkflowPlan

MATRIX_PATH = Path(__file__).parent / "golden" / "recovery_matrix.json"


def _matrix():
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def test_diagnostic_and_typed_action_matrix_is_complete():
    cases = _matrix()
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["phase"] for case in cases} == {
        "planning",
        "connection",
        "execution",
        "verification",
        "delivery",
    }
    assert {
        "malformed_plan",
        "invalid_arguments",
        "capability_drift",
        "authorization_required",
        "rate_limited",
        "timeout",
        "provider_unavailable",
        "verification_incomplete",
        "uncertain_external_effect",
        "internal_defect",
    } <= {case["expected_category"] for case in cases}

    for case in cases:
        blocker = None
        if case.get("blocker_code"):
            blocker = {
                "kind": "human_action",
                "code": case["blocker_code"],
                "message": "fixture",
                "action": "fixture",
            }
        run = WorkflowRun(
            id=f"run-{case['id']}",
            prompt="golden recovery fixture",
            status=RunStatus.blocked,
            plan_approved=case["phase"] != "planning",
            result={
                "verification": {"status": "unverified"} if case["phase"] == "verification" else {}
            },
            execution_context={
                "__aura_supervisor__": {
                    "version": 2,
                    "phase": case["phase"],
                    "attempts": {case["phase"]: case["attempts"]},
                },
                **({"__aura_blocker__": blocker} if blocker else {}),
            },
        )
        steps = [
            SimpleNamespace(
                id="completed",
                step_key="completed",
                status=StepStatus.completed,
                tool_slug="notion",
                operation="notion.search",
            ),
            SimpleNamespace(
                id="failed",
                step_key="failed",
                status=StepStatus.failed,
                tool_slug="notion",
                operation="notion.search",
            ),
        ]

        diagnostic = diagnose_run(run, steps, category=case["category"])
        program = repair_program(diagnostic)

        assert diagnostic.category.value == case["expected_category"], case["id"]
        assert diagnostic.human_action_required is case["expected_human"], case["id"]
        assert diagnostic.code_repair_required is case["expected_code_repair"], case["id"]
        assert diagnostic.completed_step_keys == ["completed"], case["id"]
        assert [action.tool.value for action in program.actions] == case["expected_actions"], case[
            "id"
        ]
        assert all(action.preserves_completed_steps for action in program.actions)


def test_every_persisted_run_state_is_owned_by_the_transition_matrix():
    assert set(ALLOWED_TRANSITIONS) == set(RunStatus)
    assert not ALLOWED_TRANSITIONS[RunStatus.completed]
    assert not ALLOWED_TRANSITIONS[RunStatus.cancelled]


async def test_legacy_direct_transition_is_rejected_at_flush():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            session.add(Workspace(id="w", name="Golden matrix"))
            session.add(
                WorkflowRun(
                    id="run",
                    workspace_id="w",
                    prompt="fixture",
                    status=RunStatus.running,
                )
            )
            await session.commit()
            run = await session.get(WorkflowRun, "run")
            run.status = RunStatus.failed
            with pytest.raises(RuntimeError, match="only be changed by Run Supervisor"):
                await session.commit()
    finally:
        await engine.dispose()


def test_malformed_plan_and_argument_aliases_are_repaired_before_validation():
    manifest = native_manifest("notion")
    raw = json.dumps(
        {
            "name": "Find the report",
            "steps": {
                "lookup": {
                    "tool_slug": "notion",
                    "operation": "notion.search",
                    "arguments": {"query": "quarterly report", "limit": 3},
                }
            },
        }
    )

    repaired = repair_malformed_plan(
        f"```json\n{raw}\n```",
        [{"slug": "notion", "allowed_operations": native_operations("notion")}],
        {"notion": manifest},
    )

    assert {"json_envelope", "steps_object_to_array", "steps[0].arguments"} <= set(
        repaired.repaired_fields
    )
    assert repaired.plan["steps"][0]["arguments"] == {
        "query": "quarterly report",
        "page_size": 3,
    }
    assert repair_arguments(
        manifest,
        "notion.search",
        {"maxResults": 5, "cursor": "next-page"},
    ) == {"page_size": 5, "start_cursor": "next-page"}


def test_replan_restores_completed_steps_byte_for_byte():
    completed = PlanStep(
        key="write",
        agent="writer",
        tool_slug="gmail",
        operation="gmail.send",
        arguments={"to": "approved@example.com", "subject": "Report", "body": "Done"},
        reason="Send the approved report",
        expected_output="Sent-message receipt",
        consequential=True,
    )
    remaining = PlanStep(
        key="read",
        agent="reader",
        tool_slug="notion",
        operation="notion.search",
        arguments={"query": "report"},
        reason="Confirm the report exists",
        expected_output="Report metadata",
        depends_on=["write"],
    )
    original = WorkflowPlan(
        name="Report", interpretation="Send and verify", steps=[completed, remaining]
    ).model_dump(mode="json")
    modified_completed = completed.model_copy(
        update={"arguments": {"to": "attacker@example.com", "body": "Changed"}}
    )
    repaired_remaining = remaining.model_copy(update={"arguments": {"query": "quarterly report"}})
    candidate = WorkflowPlan(
        name="Report",
        interpretation="Send and verify",
        steps=[modified_completed, repaired_remaining],
    ).model_dump(mode="json")

    repaired = preserve_completed_steps(original, candidate, {"write"})

    assert repaired.plan["steps"][0] == original["steps"][0]
    assert repaired.plan["steps"][1]["arguments"] == {"query": "quarterly report"}
    assert repaired.completed_step_keys == ["write"]


def test_equivalent_provider_requires_read_contract_and_prior_permission():
    manifests = {
        "notion": native_manifest("notion"),
        "google": native_manifest("google"),
    }
    approved = {
        "tool_slug": "notion",
        "operation": "notion.search",
        "arguments": {"query": "quarterly report"},
    }
    replacement = SimpleNamespace(
        tool_slug="google",
        operation="drive.files.search",
        arguments={"query": "quarterly report"},
        consequential=False,
    )
    snapshot = SimpleNamespace(permission_snapshot={"google": ["drive.files.search"]})

    assert equivalent_substitution_allowed(approved, replacement, snapshot, manifests)
    snapshot.permission_snapshot = {"google": []}
    assert not equivalent_substitution_allowed(approved, replacement, snapshot, manifests)
    replacement.consequential = True
    assert not equivalent_substitution_allowed(approved, replacement, snapshot, manifests)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _sandbox_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / "backend" / "app" / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_isolated_gate_includes_and_allows_safe_untracked_source(tmp_path):
    repo, base_sha = _sandbox_repo(tmp_path)
    (repo / "backend" / "app" / "repair.py").write_text(
        "def repaired():\n    return True\n", encoding="utf-8"
    )

    report = validate_repair(base_sha, root=repo)

    assert report.passed is True
    assert report.changed_files == ["backend/app/repair.py"]
    assert report.added_lines == 2


@pytest.mark.parametrize(
    "path,content,reason",
    [
        ("backend/fixtures/escape.py", "ESCAPE = True\n", "outside repair allowlist"),
        ("backend/app/main.py", "# bypass\n", "protected path changed"),
        (
            "backend/app/worker.py",
            "RECOVERY_GITHUB_TOKEN = 'exfiltrate'\n",
            "forbidden addition matched",
        ),
    ],
)
def test_isolated_gate_rejects_boundary_changes(tmp_path, path, content, reason):
    repo, base_sha = _sandbox_repo(tmp_path)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    report = validate_repair(base_sha, root=repo)

    assert report.passed is False
    assert any(reason in violation for violation in report.violations)


def test_pipeline_callback_is_timestamped_and_hmac_signed(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status":"accepted"}'

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("app.code_repair_sandbox.urlopen", open_request)
    payload = {"status": "promoted", "workspace_id": "workspace"}

    assert send_callback("https://api.example", "incident", "secret", payload) == {
        "status": "accepted"
    }
    request = captured["request"]
    timestamp = request.headers["X-aura-recovery-timestamp"]
    expected = hmac.new(
        b"secret",
        timestamp.encode() + b"." + request.data,
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(request.headers["X-aura-recovery-signature"], expected)
    assert captured["timeout"] == 20
