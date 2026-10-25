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
