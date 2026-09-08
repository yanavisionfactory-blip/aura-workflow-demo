"""Bounded semantic retrieval of explicitly owned, verified workflow results."""

import hashlib
import math

from openai import AsyncOpenAI
from sqlalchemy import select

from .config import get_settings
from .db import set_tenant_context
from .models import AuditEvent, RunStatus, WorkflowMemory, WorkflowRun


class MemoryUnavailable(RuntimeError):
    pass


def unit_vector(values: list[float]) -> list[float]:
    if not values or any(not math.isfinite(value) for value in values):
        raise MemoryUnavailable("Invalid embedding vector")
    norm = math.sqrt(sum(value * value for value in values))
    if not norm or not math.isfinite(norm):
        raise MemoryUnavailable("Invalid embedding norm")
    return [value / norm for value in values]


async def embed_text(text: str) -> list[float]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise MemoryUnavailable("Memory embeddings are not configured")
    try:
        async with AsyncOpenAI(
            api_key=settings.openai_api_key, timeout=20, max_retries=1
        ) as client:
            response = await client.embeddings.create(
                model=settings.memory_embedding_model,
                input=text[:8000],
                encoding_format="float",
            )
        return unit_vector(response.data[0].embedding)
    except Exception as exc:
        raise MemoryUnavailable(
            "Memory embeddings are temporarily unavailable"
        ) from exc


async def source_owner(session, workspace_id: str, run_id: str) -> str | None:
    return await session.scalar(
        select(AuditEvent.actor)
        .where(
            AuditEvent.workspace_id == workspace_id,
            AuditEvent.run_id == run_id,
            AuditEvent.event_type == "run.created",
        )
        .order_by(AuditEvent.created_at)
        .limit(1)
    )


async def index_run_memory(
    session, run: WorkflowRun, subject: str | None = None
) -> WorkflowMemory | None:
    await set_tenant_context(session, run.workspace_id)
    owner = await source_owner(session, run.workspace_id, run.id)
    if not owner or (subject is not None and owner != subject):
        return None
    # The run lock also serializes explicit indexing requests for the same source.
    run = await session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.id == run.id, WorkflowRun.workspace_id == run.workspace_id)
        .with_for_update()
    )
    if (
        run.status != RunStatus.completed
        or run.result.get("verification", {}).get("status") != "verified"
    ):
        return None
    existing = await session.scalar(
        select(WorkflowMemory).where(
            WorkflowMemory.workspace_id == run.workspace_id,
            WorkflowMemory.subject == owner,
            WorkflowMemory.run_id == run.id,
        )
    )
    if existing and existing.deleted:
        return None  # A forgotten memory is never silently recreated.
    deliverable = run.result.get("unified_deliverable", {})
    content = (
        run.prompt[:2000]
        + "\n"
        + str(deliverable.get("summary", ""))[:2000]
        + "\n"
        + str(deliverable.get("deliverable", ""))[:4000]
    )[:8000]
    digest = hashlib.sha256(content.encode()).hexdigest()
    model = get_settings().memory_embedding_model
    if (
        existing
        and existing.content_hash == digest
        and existing.embedding_model == model
    ):
        return existing
    embedding = await embed_text(content)
    memory = existing or WorkflowMemory(
        workspace_id=run.workspace_id, subject=owner, run_id=run.id
    )
    memory.text, memory.embedding = content, embedding
    memory.embedding_model, memory.content_hash = model, digest
    session.add(memory)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor=owner,
            event_type="memory.indexed",
            payload={"memory_id": memory.id, "model": model},
        )
    )
    return memory


async def search_memory(
    session,
    workspace_id: str,
    subject: str,
    query: str,
    limit: int = 5,
    minimum_score: float = 0.25,
) -> list[dict]:
    settings = get_settings()
    # Filter by both ACL dimensions before retrieving vectors or calling the model.
    candidates = (
        await session.scalars(
            select(WorkflowMemory)
            .where(
                WorkflowMemory.workspace_id == workspace_id,
                WorkflowMemory.subject == subject,
                WorkflowMemory.deleted.is_(False),
                WorkflowMemory.embedding_model == settings.memory_embedding_model,
            )
            .order_by(WorkflowMemory.created_at.desc())
            .limit(settings.memory_candidate_limit)
        )
    ).all()
    if not candidates:
        return []
    query_vector = await embed_text(query)
    matches = []
    for memory in candidates:
        source = await session.get(WorkflowRun, memory.run_id)
        if (
            not source
            or source.workspace_id != workspace_id
            or source.status != RunStatus.completed
            or source.result.get("verification", {}).get("status") != "verified"
            or await source_owner(session, workspace_id, source.id) != subject
        ):
            continue
        if len(memory.embedding) != len(query_vector):
            continue
        try:
            vector = unit_vector(memory.embedding)
        except MemoryUnavailable:
            continue
        score = max(
            -1.0,
            min(1.0, sum(a * b for a, b in zip(query_vector, vector, strict=True))),
        )
        if score >= minimum_score:
            matches.append(
                {
                    "memory_id": memory.id,
                    "run_id": source.id,
                    "score": round(score, 6),
                    "text": memory.text,
                    "step_keys": sorted(source.execution_context.get("steps", {})),
                }
            )
    matches.sort(key=lambda item: (-item["score"], item["memory_id"]))
    return matches[:limit]
