from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import orchestrator


def saved():
    arguments = {"post_id": 31, "title": "Dallas demo guide", "description": "Fictional draft.",
                 "focus_keyword": "ac repair dallas"}
    result = {"verified": True, "reused": False, "post_id": 31, "post_status": "draft",
              "saved_fields": {key: arguments[key] for key in ("title", "description", "focus_keyword")},
              "rankmath": {"og_description": "An unrelated existing source value", "robots": ["index"]}}
    return arguments, result


@pytest.mark.parametrize("native_keys", [False, True])
async def test_exact_saved_fields_accept_existing_extra_source_metadata_without_replaying_write(monkeypatch, native_keys):
    unexpected = AsyncMock(side_effect=AssertionError("Do not replay or rejudge verified saved fields"))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", unexpected)
    monkeypatch.setattr(orchestrator, "critique_step", unexpected)
    arguments, result = saved()
    if native_keys:
        result["saved_fields"] = {"rank_math_" + key: value for key, value in result["saved_fields"].items()}
    original = deepcopy(result)
    step = SimpleNamespace(tool_slug="rankmath", operation="rankmath.post_seo.update",
                           output={"provider_result": result})
    decision = await orchestrator.review_recorded_result(None, None, step, None,
        {"arguments": arguments}, result)
    assert decision.action == "accept"
    assert step.output["outcome_check"]["status"] == "verified"
    assert result == original
    unexpected.assert_not_called()


async def test_mixed_native_and_short_saved_field_names_do_not_verify():
    arguments, result = saved()
    result["saved_fields"]["rank_math_title"] = result["saved_fields"].pop("title")
    step = SimpleNamespace(tool_slug="rankmath", operation="rankmath.post_seo.update", output={})
    decision = await orchestrator.review_recorded_result(None, None, step, None, {"arguments": arguments}, result)
    assert decision.action == "escalate"
    assert "outcome_check" not in step.output


@pytest.mark.parametrize("bad", ["wrong_post", "published", "unverified", "missing_field", "changed_field", "extra_saved_field"])
async def test_incomplete_or_mismatched_saved_metadata_remains_unverified(bad):
    arguments, result = saved()
    if bad == "wrong_post": result["post_id"] = 32
    elif bad == "published": result["post_status"] = "publish"
    elif bad == "unverified": result["verified"] = False
    elif bad == "missing_field": result["saved_fields"].pop("description")
    elif bad == "changed_field": result["saved_fields"]["title"] = "Different title"
    else: result["saved_fields"]["canonical"] = "https://example.test/"
    step = SimpleNamespace(tool_slug="rankmath", operation="rankmath.post_seo.update", output={})
    decision = await orchestrator.review_recorded_result(None, None, step, None,
        {"arguments": arguments}, result)
    assert decision.action == "escalate"
    assert "outcome_check" not in step.output
