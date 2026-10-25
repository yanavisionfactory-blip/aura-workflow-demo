from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import main
from app.model_evaluation import CASES, grade


async def test_canary_cannot_migrate_or_execute_customer_work(monkeypatch):
    monkeypatch.setattr(main, "settings", SimpleNamespace(canary_mode=True))
    migration = AsyncMock(side_effect=AssertionError("Canary must not migrate"))
    monkeypatch.setattr(main, "migrate_database", migration)
    await main.startup()
    migration.assert_not_awaited()
    next_handler = AsyncMock()
    response = await main.canary_read_only(SimpleNamespace(url=SimpleNamespace(path="/v1/runs")), next_handler)
    assert response.status_code == 503
    next_handler.assert_not_awaited()


def test_model_comparison_uses_identical_fixtures_and_strict_grading():
    import json
    assert len(CASES) == 8
    for _, _, expected in CASES:
        assert grade(json.dumps(expected), expected)
        assert not grade("not JSON", expected)
        assert not grade(json.dumps({**expected, "invented": "extra"}), expected)
    assert not grade('{"aov": true}', {"aov": 1})


async def test_isolated_canary_does_not_require_a_worker_but_production_does(monkeypatch):
    from contextlib import asynccontextmanager

    import pytest
    from fastapi import HTTPException

    from app import worker_health
    settings = SimpleNamespace(canary_mode=True, redis_url="redis://fixture", recovery_scheduler_enabled=False,
                               connector_engineer_enabled=False, connector_release_signing_key="")
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "production_configuration_checks", lambda: {"configuration": True})
    @asynccontextmanager
    async def connect():
        yield SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(main, "engine", SimpleNamespace(connect=connect))
    monkeypatch.setattr(main.redis, "from_url", lambda *_a, **_kw: SimpleNamespace(ping=AsyncMock(return_value=True), aclose=AsyncMock()))
    worker = AsyncMock(return_value=False)
    monkeypatch.setattr(worker_health, "worker_responds", worker)
    result = await main.readiness()
    assert result["status"] == "ready" and result["canary"] is True
    assert "execution_worker" not in result["checks"]
    worker.assert_not_awaited()
    settings.canary_mode = False
    with pytest.raises(HTTPException) as exc:
        await main.readiness()
    assert exc.value.status_code == 503
    assert exc.value.detail["checks"]["execution_worker"] is False
    worker.assert_awaited_once()
