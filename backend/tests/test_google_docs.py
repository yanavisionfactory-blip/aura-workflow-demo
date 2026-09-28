"""Google Docs creation uses one scoped write and verifies the actual document."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.native_connectors import native_manifest
from app.operation_contracts import enrich_operation, output_errors
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.providers import PROVIDERS, ProviderExecutor


@pytest.mark.asyncio
async def test_create_imports_complete_approved_text_and_reads_it_back(monkeypatch):
    title = "AURA verification"
    body = "First paragraph\nSecond paragraph with café & symbols."
    executor = ProviderExecutor(
        {"access_token": "test-token"}, capability_manifest=native_manifest("google")
    )
    request = AsyncMock(side_effect=[
        {"id": "doc-123", "name": title, "mimeType": "application/vnd.google-apps.document"},
        {"documentId": "doc-123", "title": title, "tabs": [{"documentTab": {"body": {
            "content": [{"paragraph": {"elements": [{"textRun": {"content": body + "\n"}}]}}]
        }}}]},
    ])
    monkeypatch.setattr(executor, "_request", request)

    receipt = await executor.execute("docs.create", {"title": title, "body": body})
    method, url = request.await_args_list[0].args
    kwargs = request.await_args_list[0].kwargs
    assert (method, url) == ("POST", "https://www.googleapis.com/upload/drive/v3/files")
    assert kwargs["params"]["uploadType"] == "multipart"
    assert kwargs["headers"]["Content-Type"].startswith("multipart/related; boundary=")
    assert '"mimeType": "application/vnd.google-apps.document"' in kwargs["content"].decode()
    assert body.encode() in kwargs["content"]
    assert receipt["result_url"] == "https://docs.google.com/document/d/doc-123/edit"

    readback = await executor.execute("docs.get", {"document_id": receipt["id"]})
    assert readback["body"] == body
    assert request.await_args_list[1].args == (
        "GET", "https://docs.googleapis.com/v1/documents/doc-123"
    )
    assert request.await_args_list[1].kwargs["params"] == {"includeTabsContent": "true"}
    check = build_outcome_check("docs.create", {"title": title, "body": body}, receipt)
    assert check.operation == "docs.get"
    assert evaluate_outcome_check(check, readback)["status"] == "verified"
    assert evaluate_outcome_check(check, {**readback, "body": "wrong"})["status"] == "failed"


@pytest.mark.asyncio
async def test_docs_readback_uses_drive_export_when_docs_api_denies_the_read(monkeypatch):
    title = "Monday briefing"
    body = "Event details\nNotes from Drive"
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.host == "docs.googleapis.com":
            return httpx.Response(403, request=request, json={"error": {"code": 403}})
        if request.url.path.endswith("/export"):
            assert request.url.params["mimeType"] == "text/plain"
            return httpx.Response(200, request=request, text=body + "\n")
        assert request.url.params["fields"] == "id,name,mimeType,trashed"
        return httpx.Response(200, request=request, json={
            "id": "doc-123", "name": title,
            "mimeType": "application/vnd.google-apps.document", "trashed": False,
        })

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    executor = ProviderExecutor({"access_token": "test-token"}, capability_manifest=native_manifest("google"))
    observed = await executor.execute("docs.get", {"document_id": "doc-123"})

    assert observed == {
        "id": "doc-123", "title": title, "body": body,
        "result_url": "https://docs.google.com/document/d/doc-123/edit",
    }
    assert len(calls) == 3
    check = build_outcome_check("docs.create", {"title": title, "body": body}, {"id": "doc-123"})
    assert evaluate_outcome_check(check, observed)["status"] == "verified"


@pytest.mark.asyncio
async def test_docs_drive_fallback_rejects_a_different_resource(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.host == "docs.googleapis.com":
            return httpx.Response(403, request=request)
        return httpx.Response(200, request=request, json={
            "id": "another-doc", "name": "Other", "mimeType": "application/vnd.google-apps.document",
        })

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    executor = ProviderExecutor({"access_token": "test-token"})
    with pytest.raises(ValueError, match="did not identify"):
        await executor.execute("docs.get", {"document_id": "doc-123"})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_create_rejects_empty_content_without_an_external_write(monkeypatch):
    executor = ProviderExecutor({"access_token": "test-token"})
    request = AsyncMock()
    monkeypatch.setattr(executor, "_request", request)
    with pytest.raises(ValueError, match="nonempty body"):
        await executor.execute("docs.create", {"title": "Empty", "body": "  "})
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_google_rejection_logs_only_a_fixed_reason(monkeypatch, caplog):
    executor = ProviderExecutor({"access_token": "test-token"})
    request = httpx.Request("POST", "https://www.googleapis.com/upload/drive/v3/files")
    response = httpx.Response(403, request=request, json={"error": {
        "status": "PERMISSION_DENIED", "errors": [{"reason": "insufficientPermissions"}],
        "message": "private provider detail",
    }})
    monkeypatch.setattr(executor, "_request", AsyncMock(side_effect=httpx.HTTPStatusError(
        "403 Forbidden", request=request, response=response,
    )))
    with pytest.raises(httpx.HTTPStatusError):
        await executor.execute("docs.create", {"title": "Poem", "body": "Verse"})
    assert "reason=insufficientPermissions" in caplog.text
    assert "private provider detail" not in caplog.text


def test_docs_require_scoped_consent_and_typed_readback():
    assert "https://www.googleapis.com/auth/drive.file" in PROVIDERS["google"].scopes
    capabilities = {m["name"]: enrich_operation(m) for m in native_manifest("google")["capabilities"]}
    create = capabilities["docs.create"]
    assert create["reliability"]["output_validation"] == "typed"
    assert create["reliability"]["readback_operation"] == "docs.get"
    assert not output_errors("docs.create", {
        "id": "doc-123", "name": "AURA verification",
        "mimeType": "application/vnd.google-apps.document",
    })
