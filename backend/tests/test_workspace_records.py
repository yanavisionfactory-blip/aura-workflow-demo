import pytest
from fastapi import HTTPException

from app.main import (
    UI_RECORD_TYPES,
    TenantContext,
    _record_type,
    get_workspace_record,
    production_configuration_checks,
)
from app.migrations import DIRECT_TENANT_TABLES
from app.models import WorkspaceRecord


def test_all_frontend_record_types_are_workspace_scoped() -> None:
    assert UI_RECORD_TYPES == {
        "workflow",
        "workflow_run",
        "schedule",
        "access_request",
        "creator",
    }
    assert "workspace_id" in WorkspaceRecord.__table__.columns
    assert "workspace_records" in DIRECT_TENANT_TABLES


def test_unknown_record_type_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        _record_type("other-customer-data")
    assert exc.value.status_code == 404


def test_production_checks_require_legacy_tokens_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    monkeypatch.setattr(main.settings, "clerk_jwt_key", "public-key")
    monkeypatch.setattr(main.settings, "clerk_issuer", "https://clerk.example")
    monkeypatch.setattr(main.settings, "clerk_authorized_parties", "https://app.example")
    monkeypatch.setattr(main.settings, "openai_api_key", "configured")
    monkeypatch.setattr(main.settings, "allow_legacy_workspace_tokens", True)
    assert production_configuration_checks()["legacy_tokens_disabled"] is False


@pytest.mark.asyncio
async def test_workspace_record_cannot_be_read_from_another_workspace() -> None:
    record = WorkspaceRecord(
        id="workflow-1",
        workspace_id="workspace-a",
        record_type="workflow",
        data={"name": "Private workflow"},
    )

    class FakeSession:
        async def get(self, _model, _record_id):
            return record

    with pytest.raises(HTTPException) as error:
        await get_workspace_record(
            "workflow",
            "workflow-1",
            TenantContext(
                workspace_id="workspace-b",
                subject="user-b",
                role="member",
            ),
            FakeSession(),
        )

    assert error.value.status_code == 404
