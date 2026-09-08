import copy
import hashlib
from types import SimpleNamespace
import pytest
from app.outcome_checks import build_outcome_check, evaluate_outcome_check, READBACK_OPERATIONS
from app.extended_outcomes import leaves, observe_check, required_reads
from app.native_connectors import NATIVE_CONNECTORS, native_manifest
from app.policy import operation_scope
from test_system_reliability import database


def cases():
    for entity in ("contact", "company"):
        yield (f"hubspot.{entity}.update", {f"{entity}_id": "42", "properties": {"name": "Fixture"}}, {"id": "42"}, {"id": "42", "properties": {"name": "Fixture"}, "archived": False})
    yield ("airtable.create", {"base_id": "b", "table_id": "t", "records": [{"fields": {"Name": "One"}}, {"fields": {"Name": "Two"}}]},
        {"records": [{"id": "r1"}, {"id": "r2"}]}, {"checks": [{"id": "r1", "fields": {"Name": "One"}}, {"id": "r2", "fields": {"Name": "Two"}}]})
    yield ("slack.post", {"channel": "C1", "text": "Fixture"}, {"channel": "C1", "ts": "123.456"}, {"channel": "C1", "messages": [{"ts": "123.456", "text": "Fixture"}]})
    member = hashlib.md5(b"test@example.com", usedforsecurity=False).hexdigest()
    yield ("mailchimp.member.upsert", {"list_id": "l", "email_address": "test@example.com", "merge_fields": {"FNAME": "Fixture"}},
        {"id": member, "status": "subscribed"}, {"id": member, "list_id": "l", "email_address": "test@example.com", "merge_fields": {"FNAME": "Fixture"}, "status": "subscribed"})
    yield ("mailchimp.campaign.create", {"type": "regular", "recipients": {"list_id": "l"}, "settings": {"subject_line": "Fixture"}},
        {"id": "c"}, {"id": "c", "type": "regular", "recipients": {"list_id": "l"}, "settings": {"subject_line": "Fixture"}})
    yield ("mailchimp.campaign.send", {"campaign_id": "c"}, {"status_code": 204}, {"id": "c", "status": "sent"})
    yield ("canva.design.create", {"title": "Fixture", "design_type": {"type": "preset", "name": "presentation"}}, {"design": {"id": "d"}}, {"design": {"id": "d", "title": "Fixture", "design_types": ["presentation"]}})
    yield ("canva.export.create", {"design_id": "d", "format": "pdf"}, {"job": {"id": "j"}}, {"job": {"id": "j", "status": "success", "urls": ["https://example.test/fixture.pdf"]}})
    for operation, status in [("tiktok.video.upload.init", "SEND_TO_USER_INBOX"), ("tiktok.video.publish.init", "PUBLISH_COMPLETE")]:
        yield (operation, {"source_info": {"source": "PULL_FROM_URL", "video_url": "https://example.test/v"}, "post_info": {}},
            {"data": {"publish_id": "p"}}, {"_aura_requested_publish_id": "p", "data": {"status": status}, "error": {"code": "ok"}})
    yield ("sheets.append", {"spreadsheet_id": "s", "values": [["Fixture"]]}, {"spreadsheetId": "s", "updates": {"updatedRange": "Sheet1!A1:A1"}}, {"range": "Sheet1!A1:A1", "values": [["Fixture"]]})
    child = {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "Fixture"}}]}}
    tree = {"results": [{"id": "block", **child}], "_aura_completeness": {"complete": True}, "nested_children": {}}
    yield ("notion.blocks.children.append", {"block_id": "page", "children": [child]}, {"results": [{"id": "block"}]}, tree)
    yield ("notion.page.create", {"parent": {"page_id": "parent"}, "properties": {}, "children": [child]}, {"id": "page"},
        {"checks": [{"id": "page", "parent": {"page_id": "parent"}, "properties": {}, "archived": False}, tree]})


@pytest.mark.parametrize("operation,arguments,receipt,observed", list(cases()))
async def test_write_evidence_requires_all_readbacks_and_never_executes_a_write(operation, arguments, receipt, observed):
    check = build_outcome_check(operation, arguments, receipt)
    assert evaluate_outcome_check(check, observed)["status"] == "verified"
    assert evaluate_outcome_check(check, {})["status"] != "verified"
    calls = []
    rows = iter(observed["checks"] if check.kind == "compound" else [observed])
    async def execute(op, args):
        calls.append(op)
        assert operation_scope(op) == "read"
        return next(rows)
    actual = await observe_check(SimpleNamespace(execute=execute), check)
    assert evaluate_outcome_check(check, actual)["status"] == "verified"
    assert len(calls) == len(leaves(check))


def test_every_native_write_has_a_readback_with_read_only_permission():
    for slug in NATIVE_CONNECTORS:
        modules = {m["name"]: m for m in native_manifest(slug)["capabilities"]}
        for name, module in modules.items():
            if module["permission_scope"] == "read":
                assert operation_scope(name) == "read"
                continue
            assert name in READBACK_OPERATIONS, name
            assert modules[READBACK_OPERATIONS[name]]["permission_scope"] == "read"
    assert operation_scope("mailchimp.member.upsert") == "write"
    assert operation_scope("tiktok.video.upload.init") == "write"


def test_wrong_resource_and_incomplete_jobs_cannot_pass():
    for operation, args, receipt, observed in cases():
        check = build_outcome_check(operation, args, receipt)
        if check.kind == "compound":
            observed["checks"] = observed["checks"][:-1]
        elif "id" in observed:
            observed["id"] = "wrong"
        elif check.kind == "slack":
            observed["messages"][0]["ts"] = "wrong"
        elif check.kind == "notion_blocks":
            observed["_aura_completeness"]["complete"] = False
        elif check.kind == "sheets":
            observed["values"] = [["Wrong"]]
        elif check.kind == "canva_design":
            observed["design"]["id"] = "wrong"
        elif check.kind == "canva_export":
            observed["job"]["status"] = "in_progress"
        else:
            observed["data"]["status"] = "PROCESSING_UPLOAD"
        assert evaluate_outcome_check(check, observed)["status"] != "verified", operation


def test_batch_receipts_and_permissions_cover_all_resources():
    args = {"base_id": "b", "table_id": "t", "records": [{"fields": {}}, {"fields": {}}]}
    with pytest.raises(ValueError):
        build_outcome_check("airtable.create", args, {"records": [{"id": "r"}]})
    with pytest.raises(ValueError):
        build_outcome_check("airtable.create", args, {"records": [{"id": "r"}, {"id": "r"}]})
    assert required_reads("notion.page.create", {"children": [{}]}) == {"notion.page.get", "notion.blocks.children.list"}


def test_notion_nested_children_and_custom_design_omissions_are_not_hidden():
    child = {"type": "toggle", "toggle": {"rich_text": [], "children": [{"type": "paragraph", "paragraph": {"rich_text": []}}]}}
    check = build_outcome_check("notion.blocks.children.append", {"block_id": "p", "children": [child]}, {"results": [{"id": "b"}]})
    observed = {"results": [{"id": "b", "type": "toggle", "has_children": True, "toggle": {"rich_text": []}}],
        "nested_children": {"b": [{"id": "c", "type": "paragraph", "paragraph": {"rich_text": []}}]}, "_aura_completeness": {"complete": True}}
    assert evaluate_outcome_check(check, observed)["status"] == "verified"
    observed["nested_children"] = {}
    assert evaluate_outcome_check(check, observed)["status"] != "verified"
    check = build_outcome_check("canva.design.create", {"design_type": {"type": "custom", "width": 100, "height": 100}}, {"design": {"id": "d"}})
    assert evaluate_outcome_check(check, {"design": {"id": "d", "design_types": ["custom"]}})["status"] == "unverified"


async def test_suite_collects_live_scenarios_but_does_not_certify_missing_operations(tmp_path, monkeypatch):
    from app import release_evaluation
    from app.certification_suite import run_suite
    monkeypatch.setenv("FIXTURE_CREDS", '{"access_token":"fixture"}')
    async def identity(*args): return {"identity": {"id": "dedicated"}}
    monkeypatch.setattr(release_evaluation, "verify_oauth_credentials", identity)
    calls = []
    async def execute(self, op, args):
        calls.append(op)
        return {"id": "page", "parent": {"page_id": "parent"}, "properties": {}, "archived": False}
    monkeypatch.setattr(release_evaluation.ProviderExecutor, "execute", execute)
    fixtures = [{"id": "create", "connector": "notion", "operation": "notion.page.create",
        "dedicated_test_account": True, "expected_account_id": "dedicated", "credentials_env": "FIXTURE_CREDS",
        "arguments": {"parent": {"page_id": "parent"}, "properties": {}}}]
    report = await run_suite(fixtures, tmp_path, allow_writes=True)
    assert report["operation_results"][0]["passed"]
    assert report["passed"] is False  # Other advertised writes have no fixtures.
    assert calls.count("notion.page.create") == 2  # Normal and deliberately lost-response cases.
    await run_suite(fixtures, tmp_path, allow_writes=True)
    assert calls.count("notion.page.create") == 2  # Reinvoking the entire suite is safe.
    fixtures[0]["dedicated_test_account"] = False
    with pytest.raises(ValueError):
        await run_suite(fixtures, tmp_path, allow_writes=True)


def test_load_runner_rejects_production_database_names():
    from app.load_evaluation import validate_database
    for url in ("postgresql+psycopg://host/production", "postgresql+psycopg://host/aura", "sqlite+aiosqlite:///production.db"):
        with pytest.raises(ValueError): validate_database(url)
    assert validate_database("postgresql+psycopg://host/aura_test")


@pytest.mark.parametrize("operation,args,expected_path", [
    ("airtable.record.get", {"base_id": "b", "table_id": "t", "record_id": "r"}, "/b/t/r"),
    ("slack.message.get", {"channel": "C", "ts": "1.2"}, "/conversations.history"),
    ("hubspot.contact.get", {"contact_id": "42", "properties": ["email"]}, "/contacts/42"),
    ("hubspot.company.get", {"company_id": "42", "properties": ["name"]}, "/companies/42"),
    ("mailchimp.member.get", {"list_id": "l", "subscriber_hash": "hash"}, "/lists/l/members/hash"),
    ("mailchimp.campaign.get", {"campaign_id": "c"}, "/campaigns/c"),
])
async def test_new_resource_checks_use_exact_get_routes(monkeypatch, operation, args, expected_path):
    from app.providers import ProviderExecutor
    requests = []
    async def request(self, method, url, **kwargs):
        requests.append((method, url, kwargs))
        return {"ok": True, "messages": []}
    monkeypatch.setattr(ProviderExecutor, "_request", request)
    executor = ProviderExecutor({"api_endpoint": "https://fixture.api.mailchimp.com"})
    await executor.execute(operation, args)
    assert len(requests) == 1
    assert requests[0][0] == "GET" and requests[0][1].endswith(expected_path)
    if operation == "slack.message.get":
        assert requests[0][2]["params"] == {"channel": "C", "oldest": "1.2", "latest": "1.2", "inclusive": "true", "limit": 1}


async def test_pending_jobs_create_one_delayed_dispatch_and_exhaust_the_budget(database):
    from app.models import WorkflowRun, RunStep, RunStatus, StepStatus, DispatchIntent
    from app.verification_recovery import defer_verification, verification_due
    from sqlalchemy import select
    from datetime import datetime, timezone, timedelta
    async with database() as session:
        run = WorkflowRun(id="pending-job", workspace_id="w", prompt="Export", status=RunStatus.running)
        step = RunStep(id="pending-step", run_id=run.id, position=0, step_key="export", agent="exporter", tool_slug="canva",
            operation="canva.export.create", arguments={}, status=StepStatus.running, idempotency_key="fixture",
            output={"provider_result": {"job": {"id": "j"}}, "outcome_check": {"status": "pending"}})
        session.add_all([run, step]); await session.commit()
        now = datetime.now(timezone.utc)
        assert await defer_verification(session, run, step, now)
        assert not verification_due(step, now)
        assert verification_due(step, now+timedelta(seconds=16))
        assert len((await session.scalars(select(DispatchIntent).where(DispatchIntent.run_id == run.id))).all()) == 1
        step.output = {**step.output, "verification_poll_count": 6}
        assert not await defer_verification(session, run, step, now+timedelta(seconds=20))
        assert step.output["outcome_check"]["status"] == "unverified"
        assert step.output["provider_result"]["job"]["id"] == "j"


@pytest.mark.skipif(not __import__('os').getenv('AURA_TEST_POSTGRES_URL'), reason="Requires real PostgreSQL concurrency")
async def test_simultaneous_first_runs_share_one_trust_record():
    import asyncio, os, uuid
    from sqlalchemy import select, func
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app import orchestrator
    from app.models import Workspace, ToolConnection, ToolKind, ToolTrustState
    engine = create_async_engine(os.environ['AURA_TEST_POSTGRES_URL'])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    workspace, tool_id = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        async with factory() as session:
            session.add(Workspace(id=workspace, name="Concurrent trust fixture"))
            await session.flush()
            session.add(ToolConnection(id=tool_id, workspace_id=workspace, slug="fixture", display_name="Fixture", kind=ToolKind.api_key, config={}))
            await session.commit()
        ready = asyncio.Event()
        entered = 0
        async def initialize():
            nonlocal entered
            async with factory() as session:
                tool = await session.get(ToolConnection, tool_id)
                entered += 1
                if entered == 8: ready.set()
                await ready.wait()
                state = await orchestrator._trust_state(session, workspace, tool)
                await session.commit()
                return state.id
        identifiers = await asyncio.gather(*(initialize() for _ in range(8)))
        assert len(set(identifiers)) == 1
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(ToolTrustState).where(ToolTrustState.workspace_id == workspace)) == 1
    finally:
        await engine.dispose()
