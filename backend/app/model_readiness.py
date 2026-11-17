"""A cheap, tool-free probe of the direct planner's real structured contract."""
import asyncio
import json

from openai import AsyncOpenAI

from .config import get_settings
from .model_failures import is_model_quota_error


async def probe_direct_model() -> dict:
    from .llm_planner import _catalog_plan_format

    settings = get_settings()
    catalog = [{"slug": slug, "allowed_operations": [operation]} for slug, operation in (
        ("google-drive", "google-drive.search-files"),
        ("canva", "canva.presentation.create"), ("gmail", "gmail.draft.create"),
    )]
    expected = {"name": "Synthetic readiness", "interpretation": "No external work",
        "steps": [{"key": "canva", "agent": "Planner", "tool_slug": "canva",
        "operation": "canva.presentation.create", "arguments_json": "{}",
        "reason": "Synthetic probe only", "expected_output": "No execution",
        "consequential": True, "depends_on": [], "required_evidence": []}]}
    try:
        async with asyncio.timeout(settings.model_call_timeout_seconds):
            async with AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0) as client:
                response = await client.responses.parse(model=settings.openai_model,
                    instructions="Return exactly this synthetic plan. Do not execute anything.",
                    input=json.dumps(expected), text_format=_catalog_plan_format(catalog),
                    reasoning={"effort": "low"}, max_output_tokens=2048, store=False)
                ready = response.output_parsed is not None and response.output_parsed.model_dump() == expected
                return {"ready": ready, "model": settings.openai_model}
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed without provider payloads
        return {"ready": False, "model": settings.openai_model,
                "error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None),
                "quota_exhausted": is_model_quota_error(exc)}
