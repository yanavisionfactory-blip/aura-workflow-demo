"""A cheap, tool-free probe of the direct planner's real structured contract."""
import asyncio
import json

from openai import AsyncOpenAI

from .config import get_settings
from .model_failures import is_model_quota_error


async def probe_direct_model() -> dict:
    from .llm_planner import _catalog_plan_format
    from .material_relevance import assess_materials

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
                plan_ready = response.output_parsed is not None and response.output_parsed.model_dump() == expected
                if not plan_ready:
                    return {"ready": False, "model": settings.openai_model}
            # Exercise the real source-selection path, not just schema copying.
            # Synthetic local strings only: no connected account or provider read.
            notes = "Música ambiente original para pequenos cafés.\r\nUso\u00a0comercial ainda não confirmado; rever a licença."
            reviewed = await assess_materials(
                "Find project materials for selling AI background music to small cafés. Preserve licensing uncertainty.",
                [{"id": "notes", "title": "Notes 07", "text": notes},
                 {"id": "keywords", "title": "AI music restaurants", "text":
                  "An unrelated search keyword glossary: AI music restaurants. No project facts or proposal."}])
            sources_ready = (reviewed["notes"].relevant and reviewed["notes"].excerpts == [notes]
                             and not reviewed["keywords"].relevant and not reviewed["keywords"].excerpts)
        result = {"ready": sources_ready, "model": settings.openai_model, "source_review": sources_ready}
        if sources_ready and settings.canary_mode:
            from .presentation_draft import PresentationDraft, compose_presentation, review_copy
            from .reports import ReportRequest

            brief = ReportRequest(title="Brisa", instructions="Pitch a listening trial to a café owner in European Portuguese.",
                sources=[{"id": "brief", "title": "Notes", "content": "Original music for cafés."}], presentation=True)
            broken = PresentationDraft(title="Música para restaurantr", subtitle="", phases=[{
                "period": "Oferta", "title": "Ambiente para o seu “m", "items": ["Resumo da documentação."],
                "source_ids": ["brief"]}], limitations=["Termos por confirmar."])
            review = await review_copy(brief, broken)
            if not review.issues:
                return {**result, "ready": False, "presentation_editor": False}
            sample = await compose_presentation(brief)
            result["presentation_editor"] = bool(sample["presentation"]["phases"])
            result["ready"] = result["presentation_editor"]
        return result
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed without provider payloads
        return {"ready": False, "model": settings.openai_model,
                "error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None),
                "quota_exhausted": is_model_quota_error(exc)}
