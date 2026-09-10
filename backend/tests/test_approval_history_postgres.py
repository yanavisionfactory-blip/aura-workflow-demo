import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app import main, migrations
from app.models import Approval, ApprovalSnapshot, PlanVersion, RunStatus, RunStep, StepStatus, ToolConnection, ToolKind, WorkflowRun, Workspace
from app.schemas import ApprovalDecision


@pytest.mark.skipif(not os.getenv('AURA_TEST_POSTGRES_URL'), reason='Requires immutable PostgreSQL governance triggers')
async def test_edited_approval_appends_history_without_mutating_approved_version(monkeypatch):
    engine = create_async_engine(os.environ['AURA_TEST_POSTGRES_URL'])
    monkeypatch.setattr(migrations, 'engine', engine)
    await migrations.migrate_database()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    wid, rid, sid, aid, vid = [str(uuid4()) for _ in range(5)]
    original = {'steps': [{'operation': 'gmail.send', 'arguments': {'to': 'me', 'body': 'Original'}}]}
    edited = {'to': 'me', 'body': 'Reviewed message'}
    dispatched = []
    async def dispatch(workspace_id):
        dispatched.append(workspace_id)
    monkeypatch.setattr(main, 'dispatch_pending', dispatch)
    try:
        async with factory() as session:
            session.add(Workspace(id=wid, name='Approval regression'))
            await session.flush()
            session.add(WorkflowRun(id=rid, workspace_id=wid, prompt='Email me', plan=original, status=RunStatus.awaiting_approval))
            session.add(ToolConnection(workspace_id=wid, slug='google', display_name='Google', kind=ToolKind.oauth, allowed_operations=['gmail.send', 'gmail.get']))
            await session.flush()
            session.add(RunStep(id=sid, run_id=rid, position=0, step_key='send', agent='email', tool_slug='google', operation='gmail.send', arguments=original['steps'][0]['arguments'], status=StepStatus.awaiting_approval, consequential=True, approval_id=aid, idempotency_key=str(uuid4())))
            session.add(PlanVersion(id=vid, workspace_id=wid, run_id=rid, version=1, status='approved', plan=original, plan_hash=main.canonical_plan_hash(original)))
            await session.flush()
            session.add(Approval(id=aid, run_id=rid, step_id=sid))
            session.add(ApprovalSnapshot(workspace_id=wid, run_id=rid, plan_version_id=vid, plan_hash=main.canonical_plan_hash(original), approver_subject='tester', approver_role='owner', policy_snapshot={}, permission_snapshot={'google':['gmail.send','gmail.get']}, risk_snapshot={}, cost_snapshot={}))
            await session.commit()
            result = await main.decide_approval(aid, ApprovalDecision(approved=True, edited_arguments=edited), SimpleNamespace(workspace_id=wid, subject='tester', role='owner'), session)
            assert result['status'] == 'approved'
            versions = (await session.scalars(select(PlanVersion).where(PlanVersion.run_id == rid).order_by(PlanVersion.version))).all()
            assert len(versions) == 2
            assert versions[0].status == 'approved' and versions[0].plan == original
            assert versions[1].derived_from_id == vid and versions[1].plan['steps'][0]['arguments'] == edited
            snapshots = (await session.scalars(select(ApprovalSnapshot).where(ApprovalSnapshot.run_id == rid))).all()
            assert len(snapshots) == 2
            assert (await session.get(RunStep, sid)).arguments == edited
            assert dispatched == [wid]
    finally:
        await engine.dispose()
