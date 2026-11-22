"""A cheap, tool-free probe of the direct planner's real structured contract."""
import asyncio
import json
from traceback import extract_tb

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
    stage = "planner_contract"
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
            stage = "source_selection"
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
            from .presentation_research import assess_research_brief
            from .reports import ReportRequest

            market_question = ("I have a project in a Drive folder making background music for restaurants. "
                "Create a presentation for those places so I can understand the viability of the project.")
            stage = "market_research_scope"
            market = await assess_research_brief(market_question)
            stage = "private_research_scope"
            private = await assess_research_brief(market_question + " Use only the materials in my folder.")
            result["presentation_research"] = market.scope == "discover" and private.scope == "project_only"
            if not result["presentation_research"]:
                return {**result, "ready": False}

            brief = ReportRequest(title="Brisa", instructions="Pitch a listening trial to a café owner in European Portuguese.",
                sources=[{"id": "brief", "title": "Synthetic project brief",
                    "content": "Brisa creates original instrumental background music for cafés. "
                    "Propose a listening trial during one lunch service and ask the owner for feedback. "
                    "Price and public performance rights are unconfirmed."}], presentation=True)
            broken = PresentationDraft(title="Música para restaurantr", subtitle="", phases=[{
                "period": "Oferta", "title": "Ambiente para o seu “m", "items": ["Resumo da documentação."],
                "source_ids": ["brief"]}], limitations=["Termos por confirmar."])
            stage = "editor_rejection"
            review = await review_copy(brief, broken)
            if not review.issues:
                return {**result, "ready": False, "presentation_editor": False}
            stage = "sample_composition"
            sample = await compose_presentation(brief)
            result["presentation_editor"] = bool(sample["presentation"]["phases"])
            result["ready"] = result["presentation_editor"]
        return result
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed without provider payloads
        # Function names and line numbers identify a broken contract without recording prompts or provider messages.
        trace = [f"{frame.name}:{frame.lineno}" for frame in extract_tb(exc.__traceback__)]
        return {"ready": False, "model": settings.openai_model, "probe_stage": stage, "trace": trace[-5:],
                "error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None),
                "quota_exhausted": is_model_quota_error(exc)}
