"""Fresh media for an existing, authorized Frame.io result; never persisted URLs."""

from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from . import frameio
from .execution_preflight import _connection_credentials
from .models import CapabilityManifest, RunStep, StepStatus, ToolConnection, ToolKind, WorkflowRun
from .run_readiness import account_fingerprint


def _media_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        trusted = any(host == domain or host.endswith("." + domain)
                      for domain in ("frame.io", "amazonaws.com", "cloudfront.net", "adobe.io"))
        if url.scheme == "https" and trusted and not url.username and not url.password and url.port in (None, 443):
            return value
    except ValueError:
        pass
    return None


async def read_media(credentials, account_id, file_id):
    # Includes documented at developer.frame.io/platform/v4/docs/guides/media-links.
    # No original-download permission is requested; unavailable renditions are null.
    path = f"/v4/accounts/{account_id}/files/{file_id}"
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        payload = await frameio._get(client, path, frameio._headers(credentials), {
            "include": "media_links.thumbnail,media_links.efficient,media_links.video_h264_180",
        })
    file = frameio._file(payload, file_id)
    links = payload["data"].get("media_links") or {}
    if not isinstance(links, dict):
        raise frameio.FrameioReadError("Frame.io returned invalid media links")
    def rendition(key):
        return links.get(key) if isinstance(links.get(key), dict) else {}
    efficient = _media_url(rendition("efficient").get("download_url"))
    silent = _media_url(rendition("video_h264_180").get("url"))
    return {"account_id": account_id, "file_id": file_id, "name": file.get("name"),
            "thumbnail_url": _media_url(rendition("thumbnail").get("url")),
            "playback_url": efficient or silent, "silent_preview": not efficient and bool(silent)}


async def saved_frameio_screen(session, context, run_id, step_key):
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    step = await session.scalar(select(RunStep).where(RunStep.run_id == run.id, RunStep.step_key == step_key))
    if (not step or step.status != StepStatus.completed or step.tool_slug != "frameio"
            or step.operation not in {"frameio.file.get", "frameio.comments.list"}):
        raise HTTPException(404, "Saved Frame.io file not found")
    output = step.output or {}
    receipt = output.get("provider_result") or {}
    if (receipt.get("source_provider") != "frameio" or receipt.get("vendor_api_called") is not True
            or receipt.get("error") or receipt.get("isError")
            or output.get("critic", {}).get("action") != "accept"
            or output.get("outcome_check", {}).get("status") != "verified"):
        raise HTTPException(404, "Verified Frame.io file not found")
    try:
        account_id = frameio._uuid(receipt.get("account_id"), "account")
        file_id = frameio._uuid(receipt.get("asset_id"), "file")
        if (receipt.get("version_id") != file_id or receipt.get("file", {}).get("id") != file_id
                or receipt.get("file", {}).get("type") != "file"):
            raise ValueError("Version mismatch")
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(404, "Saved exact file version is unavailable") from exc
    tool = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == context.workspace_id, ToolConnection.slug == step.tool_slug))
    if not tool or not tool.enabled or tool.kind != ToolKind.oauth or (tool.config or {}).get("managed_by"):
        raise HTTPException(409, "The original Frame.io connection is unavailable")
    if "frameio.file.get" not in (tool.allowed_operations or []):
        raise HTTPException(403, "Frame.io file read access is required")
    manifest = await session.scalar(select(CapabilityManifest).where(
        CapabilityManifest.workspace_id == context.workspace_id, CapabilityManifest.tool_id == tool.id))
    if not manifest or manifest.status != "verified":
        raise HTTPException(409, "The Frame.io connection needs verification")
    try:
        credentials, verification, blocker = await _connection_credentials(session, tool, manifest)
        if blocker:
            raise HTTPException(409, "The Frame.io connection needs attention")
        binding = (run.execution_context or {}).get("__aura_review_readiness__", {}).get("bindings", {}).get(step.tool_slug)
        if binding and (binding.get("connection_id") != tool.id
                        or binding.get("account_fingerprint") != account_fingerprint(tool, verification)):
            raise HTTPException(409, "The connected Frame.io account differs from this run")
        screen = await read_media(credentials or {}, account_id, file_id)
        await session.commit()  # Retain an ordinary OAuth refresh only.
        return screen
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "The media preview is unavailable. Open this file in Frame.io; your saved review remains available.") from exc
