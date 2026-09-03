import pytest
from fastapi import HTTPException

from app.main import UI_RECORD_TYPES, _record_type
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
