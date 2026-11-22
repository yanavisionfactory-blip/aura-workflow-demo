"""Regression of the reported folder binding and source-to-slide execution path."""

import base64
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from jsonschema import Draft202012Validator

from app import drive_materials, material_relevance, slides_materials
from app.extended_outcomes import build_extended, evaluate_extended, required_reads
from app.native_connectors import native_manifest
from app.orchestrator import _normalize_planned_steps, _prepare_provider_arguments
from app.pipedream_connect import PipedreamConnectError
from app.presentation_sources import validate_source_presentation_plan
from app.reports import ReportRequest
from app.schemas import PlanStep, WorkflowPlan
from app.source_contracts import upgrade_capabilities
from app.workflow_context import DriveFolderIdentityError, resolve_value, step_context_value

GOAL = "Create a presentation from my Drive project for AI music for small restaurants."
DECK = {"title": "Ambient music", "subtitle": "Proposal for review", "layout": "slides",
        "phases": [{"period": "01", "title": "Pilot", "items": ["Test background tracks with venues."]}]}


def capability(provider, operation, write=False):
    return {"name": operation, "description": operation,
        "input_schema": {"type": "object", "additionalProperties": False,
            "properties": {"title" if write else "query": {"type": "string"}},
            "required": ["title" if write else "query"]},
        "output_schema": {"type": "object"}, "permission_scope": "write" if write else "read",
        "requires_approval": write, "transport": {"type": "pipedream_action", "action_id": "real-action"},
        "metadata": {"connector_broker": {"provider": provider}}}


def saved_deck():
    return {"presentationId": "created-presentation", "title": DECK["title"], "slides": [
        {"pageElements": [{"shape": {"text": {"textElements": [
            {"textRun": {"content": text + "\n"}} for text in [
                DECK["title"], phase["title"], *phase["items"]]]}}}]} for phase in DECK["phases"]]}


@pytest.mark.parametrize("path", ["id", "folderId", "ret.folderId", "ret.id", "files.0.id"])
def test_real_folder_path_string_receipt_resolves_without_changing_evidence(path):
    receipt = {"ret": "confirmed-folder-id", "exports": {"$summary": "Found folder"}}
    before = deepcopy(receipt)
    context = {"steps": {"parent": step_context_value(receipt, "google-drive.get-folder-id-for-path")}}
    assert resolve_value("{{steps.parent." + path + "}}", context) == "confirmed-folder-id"
    assert receipt == before
    assert context["steps"]["parent"]["ret"] == "confirmed-folder-id"


@pytest.mark.parametrize("value", [None, "", [], {}, "bad/path", ["one", "two"]])
def test_missing_path_identity_never_generates_an_id(value):
    context = {"steps": {"parent": step_context_value({"ret": value}, "google-drive.get-folder-id-for-path")}}
    with pytest.raises(DriveFolderIdentityError):
        resolve_value("{{steps.parent.ret.folderId}}", context)


def test_source_contract_modes_are_exclusive_and_do_not_grant_operations():
    original = [capability("google-drive", drive_materials.OPERATION)]
    upgraded = upgrade_capabilities("google-drive", original)
    assert original[0]["input_schema"]["required"] == ["query"]
    assert upgraded == upgrade_capabilities("google-drive", upgraded)
    assert upgraded[0]["permission_scope"] == "read" and not upgraded[0]["requires_approval"]
    manifest = {"capabilities": upgraded}
    for args in [{"query": "name = 'Brief'"}, {"semantic_goal": GOAL},
                 {"semantic_goal": GOAL, "folder_path": ["ChatGPT on the goooo! 💖", "Brisa Studio"]}]:
        assert _prepare_provider_arguments(manifest, drive_materials.OPERATION, args)[0] == args
    with pytest.raises(ValueError):
        _prepare_provider_arguments(manifest, drive_materials.OPERATION, {"semantic_goal": GOAL, "query": ""})
    assert upgrade_capabilities("other-provider", original) == original


class Broker:
    settings = SimpleNamespace(pipedream_project_id="project")

    def __init__(self, responder):
        self.verify_account = AsyncMock(return_value={"ok": True})
        self.calls = []
        self.responder = responder

    async def _request(self, method, path, **kwargs):
        assert kwargs["params"] == {"external_user_id": "owner", "account_id": "selected-account"}
        encoded = path.rsplit("/", 1)[-1]
        target = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        self.calls.append((method, target, kwargs))
        return self.responder(method, target, kwargs)


def file(identifier, name, mime="application/vnd.google-apps.document", parents=None):
    return {"id": identifier, "name": name, "mimeType": mime, "parents": parents or []}


async def test_path_discovery_reads_and_semantically_selects_actual_contents(monkeypatch):
    parent = file("parent", "ChatGPT on the goooo! 💖", drive_materials.FOLDER)
    folder = file("project", "Brisa Studio", drive_materials.FOLDER, ["parent"])
    good = file("useful", "Notes 07", parents=["project"])
    bad = file("irrelevant", "AI music restaurants", parents=["project"])
    audio = file("demo", "track.mp3", "audio/mpeg", ["project"])
    contents = {"useful": "Música ambiente para pequenos cafés. Teste de assinatura mensal.",
                "irrelevant": "AI music restaurants. A list of unrelated SEO keywords."}

    def respond(method, target, kwargs):
        assert method == "GET" and target.startswith("https://www.googleapis.com/drive/v3/files")
        query = parse_qs(urlsplit(target).query)
        if "q" in query:
            q = query["q"][0]
            rows = ([good, bad, audio] if "'project' in parents" in q else
                    [folder] if "'parent' in parents" in q else [parent])
            return {"files": rows}
        identifier = urlsplit(target).path.split("/")[-2]
        return contents[identifier].encode()

    async def infer(goal, documents, schema, instruction):
        assert goal == GOAL
        assert {doc["id"]: "".join(doc["passages"].values()) for doc in documents} == contents
        return schema(assessments=[material_relevance.PassageSelection(candidate_id=identifier,
            relevant=identifier == "useful", reason="Context reviewed",
            passage_indices=[0] if identifier == "useful" else []) for identifier in contents])

    monkeypatch.setattr(material_relevance, "_infer", infer)
    broker = Broker(respond)
    result = await drive_materials.execute(broker, "owner", "selected-account", {
        "semantic_goal": GOAL, "folder_path": [" ChatGPT on the goooo! 💖 ", "Brisa Studio"]})
    assert result["status"] == "matched"
    assert len(result["documents"]) == 2
    assert result["sources"][0]["title"] == "Notes 07"
    assert contents["useful"] in result["sources"][0]["content"]
    assert result["unsupported_files"][0]["id"] == "demo"
    assert not result["ret"]["isComplete"]
    broker.verify_account.assert_awaited_once_with("owner", "google_drive", "selected-account")

    # This is the actual downstream binding: metadata must survive even when
    # the composer never receives the full receipt or its scope_folders key.
    bound = resolve_value("{{steps.discover.sources}}", {"steps": {
        "discover": step_context_value(result, drive_materials.OPERATION)}})
    request = ReportRequest(title="QA preflight", instructions="Report folder and file identities",
                            sources=bound)
    source, coverage = request.sources
    assert source.id == "material_1"  # A stable citation label, not a provider ID.
    digest = hashlib.sha256(contents["useful"].encode()).hexdigest()
    assert "Drive file ID: useful\n" in source.content
    assert f"Read SHA-256: {digest}\n" in source.content
    assert "not a Drive file" in coverage.content
    metadata = json.loads(coverage.content.splitlines()[1])
    assert metadata["scope_folders"] == [
        {"id": "parent", "name": "ChatGPT on the goooo! 💖", "parents": []},
        {"id": "project", "name": "Brisa Studio", "parents": ["parent"]}]
    assert metadata["read_files"] == [
        {"drive_file_id": identifier, "name": name,
         "sha256": hashlib.sha256(contents[identifier].encode()).hexdigest(), "relevant": relevant}
        for identifier, name, relevant in [("useful", "Notes 07", True),
                                           ("irrelevant", "AI music restaurants", False)]]
    assert metadata["reviewed_file_count"] == 2
    assert metadata["relevant_file_count"] == 1
    assert metadata["unsupported_file_count"] == 1
    assert metadata["is_complete"] is False
    assert contents["irrelevant"] not in coverage.content


async def test_ambiguous_folder_does_not_read_first_match_or_broaden_scope():
    broker = Broker(lambda *_: {"files": [file("one", "Project", drive_materials.FOLDER),
                                            file("two", "Project", drive_materials.FOLDER)]})
    result = await drive_materials.execute(broker, "owner", "selected-account", {
        "semantic_goal": GOAL, "folder_path": ["Project"]})
    assert result["status"] == "scope_unresolved" and len(broker.calls) == 1
    context = {"steps": {"discover": step_context_value(result, drive_materials.OPERATION)}}
    with pytest.raises(DriveFolderIdentityError, match="No folder ID is required"):
        resolve_value("{{steps.discover.sources}}", context)


async def test_revoked_account_does_not_read_or_invoke_model():
    broker = Broker(lambda *_: pytest.fail("Provider read after rejected account"))
    broker.verify_account.return_value = {"ok": False}
    with pytest.raises(PipedreamConnectError):
        await drive_materials.execute(broker, "owner", "selected-account", {"semantic_goal": GOAL})
    assert not broker.calls


@pytest.mark.parametrize("candidate,relevant,indices,message", [
    ("known", True, [7], "invalid source passages"),
    ("known", True, [], "invalid source passages"),
    ("known", False, [0], "invalid source passages"),
    ("known", True, [0, 0], "invalid source passages"),
    ("other-account-document", True, [0], "exactly"),
])
async def test_semantic_review_rejects_invalid_references_after_one_repair(
    monkeypatch, candidate, relevant, indices, message,
):
    fake = material_relevance.PassageSelections(assessments=[
        material_relevance.PassageSelection(candidate_id=candidate, relevant=relevant,
            reason="Useful", passage_indices=indices)])
    infer = AsyncMock(return_value=fake)
    monkeypatch.setattr(material_relevance, "_infer", infer)
    with pytest.raises(ValueError, match=message):
        await material_relevance.assess_materials(GOAL, [{"id": "known", "text": "License unconfirmed"}])
    assert infer.await_count == 2


async def test_semantic_selection_resolves_original_unicode_and_line_endings(monkeypatch):
    text = ("Música ambiente — para pequenos cafés.\r\n" * 16
            + "Uso\u00a0comercial ainda não confirmado; rever a licença.\n")
    originals = {"notes": text, "decoy": "AI music restaurants. Unrelated keyword list."}

    async def infer(goal, documents, schema, instruction):
        assert {doc["id"]: "".join(doc["passages"].values()) for doc in documents} == originals
        notes = next(doc for doc in documents if doc["id"] == "notes")
        last = len(notes["passages"]) - 1
        return schema(assessments=[
            {"candidate_id": "notes", "relevant": True, "reason": "Project and rights uncertainty",
             "passage_indices": [last, 0]},
            {"candidate_id": "decoy", "relevant": False, "reason": "Only repeated words",
             "passage_indices": []}])

    monkeypatch.setattr(material_relevance, "_infer", infer)
    result = await material_relevance.assess_materials(GOAL, [
        {"id": identifier, "text": value} for identifier, value in originals.items()])
    assert all(excerpt in text and len(excerpt) <= 180 for excerpt in result["notes"].excerpts)
    assert "\r\n" in result["notes"].excerpts[0]
    assert "Uso\u00a0comercial ainda não confirmado" in result["notes"].excerpts[-1]
    assert result["decoy"].relevant is False and result["decoy"].excerpts == []


async def test_semantic_invalid_selection_repairs_references_without_rereading(monkeypatch):
    def selection(indices):
        return material_relevance.PassageSelections(assessments=[
            material_relevance.PassageSelection(candidate_id="known", relevant=True,
                reason="Source facts", passage_indices=indices)])
    infer = AsyncMock(side_effect=[selection([99]), selection([0])])
    monkeypatch.setattr(material_relevance, "_infer", infer)
    result = await material_relevance.assess_materials(GOAL, [{"id": "known", "text": "License unconfirmed"}])
    assert result["known"].excerpts == ["License unconfirmed"]
    assert infer.call_args_list[0].args[1] == infer.call_args_list[1].args[1]
    assert "previous selection" in infer.call_args_list[1].args[3]


async def test_semantic_provider_failure_is_not_retried_as_bad_references(monkeypatch):
    infer = AsyncMock(side_effect=RuntimeError("usage_limit_exceeded"))
    monkeypatch.setattr(material_relevance, "_infer", infer)
    with pytest.raises(RuntimeError, match="usage_limit_exceeded"):
        await material_relevance.assess_materials(GOAL, [{"id": "known", "text": "License unconfirmed"}])
    infer.assert_awaited_once()


async def test_twelve_document_review_repairs_missing_coverage_and_keeps_exact_sources(monkeypatch):
    documents = [{"id": f"doc_{index}", "text": f"Source {index}: commercial rights remain unconfirmed."}
                 for index in range(12)]
    complete = material_relevance.PassageSelections(assessments=[
        material_relevance.PassageSelection(candidate_id=doc["id"], relevant=True,
            reason="Rights qualification", passage_indices=[0]) for doc in documents])
    partial = material_relevance.PassageSelections(assessments=complete.assessments[:-1])
    infer = AsyncMock(side_effect=[partial, complete])
    monkeypatch.setattr(material_relevance, "_infer", infer)
    result = await material_relevance.assess_materials(GOAL, documents)
    assert {key: value.excerpts for key, value in result.items()} == {
        doc["id"]: [doc["text"]] for doc in documents}
    assert infer.await_count == 2


def test_model_cannot_supply_generated_quotes_as_source_evidence():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        material_relevance.PassageSelection(candidate_id="known", relevant=True, reason="Claim",
            passage_indices=[0], excerpts=["Invented commercial license"])


@pytest.mark.parametrize("text", ["", "a" * 601, "音楽と権利。" * 120, "\r\n\t\u00a0" * 200])
def test_source_partition_is_lossless_and_bounded(text):
    passages = material_relevance._source_passages(text)
    assert "".join(passages) == text
    assert all(0 < len(part) <= 180 for part in passages)


async def test_populated_slides_are_one_write_and_read_back_exactly(monkeypatch):
    saved = saved_deck()
    def respond(method, target, kwargs):
        if method == "POST":
            assert target.startswith("https://www.googleapis.com/upload/drive/v3/files?")
            assert kwargs["retry_safe"] is False
            assert kwargs["headers"]["x-pd-proxy-Content-Type"].startswith("multipart/related; boundary=")
            assert b"application/vnd.google-apps.presentation" in kwargs["content"]
            assert b"PPTX-BYTES" in kwargs["content"]
            return {"id": "created-presentation"}
        return saved
    monkeypatch.setattr(slides_materials, "render_timeline", lambda _: b"PPTX-BYTES")
    broker = Broker(respond)
    receipt = await slides_materials.execute(broker, "owner", "selected-account", {"presentation": DECK})
    assert [method for method, *_ in broker.calls] == ["POST", "GET"]
    assert receipt["verification"]["saved_content_matches"]
    check = build_extended("google-slides.create-presentation", {"presentation": DECK}, receipt)
    assert required_reads("google-slides.create-presentation", {"presentation": DECK}) == {"google-slides.get-presentation"}
    assert evaluate_extended(check, {"ret": saved})["status"] == "unverified"
    page_review = {"design_id": "created-presentation", "page_count": 1, "verification": {"status": "verified"}}
    assert evaluate_extended(check, {"ret": saved, "page_review": page_review})["status"] == "verified"
    saved["slides"] = []
    assert evaluate_extended(check, {"ret": saved})["status"] == "failed"


async def test_import_receipt_is_not_treated_as_populated_success(monkeypatch):
    monkeypatch.setattr(slides_materials, "render_timeline", lambda _: b"pptx")
    broker = Broker(lambda method, *_: {"id": "created-presentation"} if method == "POST"
                    else {"presentationId": "created-presentation", "slides": []})
    with pytest.raises(PipedreamConnectError, match="created-presentation") as error:
        await slides_materials.execute(broker, "owner", "selected-account", {"presentation": DECK})
    assert error.value.effect_uncertain and not error.value.retryable
    assert len(broker.calls) == 2


@pytest.mark.parametrize("source_count", [1, 2])
def test_source_plan_binds_semantic_evidence_to_populated_slides(source_count):
    def step(key, op, args, deps=(), slug="aura", write=False):
        return PlanStep(key=key, agent="Researcher", tool_slug=slug, operation=op,
            arguments=args, depends_on=list(deps), consequential=write, reason="Project materials",
            expected_output="Verified evidence")
    plan = WorkflowPlan(name="Project", interpretation=GOAL, steps=[
        step("discover", drive_materials.OPERATION, {"semantic_goal": GOAL}, slug="google-drive"),
        step("compose", "report.compose", {"title": "Brief", "instructions": GOAL,
            "sources": [{"id": f"project_{index}", "title": "Sources", "content": "{{steps.discover}}"}
                        for index in range(source_count)]}, ["discover"]),
        step("create", "google-slides.create-presentation", {"title": "Project"}, ["compose"],
             "google-slides", True)])
    manifests = {"aura": native_manifest("aura"), "google-slides": {"capabilities":
        upgrade_capabilities("google-slides", [capability("google-slides", "google-slides.create-presentation", True)])}}
    _normalize_planned_steps(plan, manifests, GOAL)
    assert plan.steps[0].reduced_scope_arguments == plan.steps[0].arguments
    plan.steps[0].arguments["folder_path"] = ["ChatGPT on the goooo! 💖", "Brisa Studio"]
    plan.steps[0].reduced_scope_arguments = {"query": ""}
    _normalize_planned_steps(plan, manifests, GOAL)
    assert plan.steps[0].reduced_scope_arguments == plan.steps[0].arguments
    assert plan.steps[0].reduced_scope_arguments is not plan.steps[0].arguments
    assert plan.steps[1].arguments["sources"] == "{{steps.discover.sources}}"
    assert plan.steps[2].arguments == {"presentation": "{{steps.compose.presentation}}"}
    validate_source_presentation_plan(GOAL, plan)
    for unselected in ["{{steps.discover.ret.files}}", "{{steps.discover.documents}}", "{{steps.discover}}"]:
        plan.steps[1].arguments["sources"] = [
            {"id": "unselected", "title": "Metadata", "content": unselected},
            {"id": "other", "title": "Other", "content": "{{steps.other.text}}"}]
        with pytest.raises(ValueError, match="verified sources"):
            validate_source_presentation_plan(GOAL, plan)
    plan.steps[1].arguments["sources"] = "{{steps.discover.sources}}"
    _prepare_provider_arguments(manifests["google-slides"], "google-slides.create-presentation", {"presentation": DECK})
    for cap in manifests["google-slides"]["capabilities"]:
        Draft202012Validator.check_schema(cap["input_schema"])
    plan.steps[2].arguments = {"title": "{{steps.compose.title}}"}
    with pytest.raises(ValueError, match="blank presentation"):
        validate_source_presentation_plan(GOAL, plan)


async def test_unscoped_search_reads_neutral_name_without_keyword_hit(monkeypatch):
    neutral = file("neutral", "2026-10-07")
    calls = []
    def respond(method, target, kwargs):
        calls.append(target)
        params = parse_qs(urlsplit(target).query)
        if "q" in params:
            return {"files": [] if "fullText" in params["q"][0] else [neutral]}
        return b"Background sound subscriptions for independent hospitality venues."
    monkeypatch.setattr(drive_materials, "retrieval_hints", AsyncMock(return_value=["music", "restaurant"]))
    async def assess(goal, documents):
        assert documents[0]["text"] == "Background sound subscriptions for independent hospitality venues."
        return {"neutral": material_relevance.IdentifiedAssessment(candidate_id="neutral", relevant=True,
            reason="Same commercial use case expressed differently", excerpts=[documents[0]["text"]])}
    monkeypatch.setattr(drive_materials, "assess_materials", assess)
    result = await drive_materials.execute(Broker(respond), "owner", "selected-account", {"semantic_goal": GOAL})
    assert result["sources"][0]["title"] == "2026-10-07"
    assert len(calls) == 3
    metadata = json.loads(result["sources"][-1]["content"].splitlines()[1])
    assert metadata["requested_folder_path"] == [] and metadata["scope_folders"] == []
    assert metadata["reviewed_file_count"] == metadata["relevant_file_count"] == 1
    assert metadata["is_complete"] is True


async def test_malformed_pdf_is_disclosed_without_fabricated_sources(monkeypatch):
    monkeypatch.setattr(drive_materials, "retrieval_hints", AsyncMock(return_value=[]))
    broker = Broker(lambda method, target, kw: {"files": [file("broken", "Brief.pdf", "application/pdf")]}
                    if "q=" in target else b"not a PDF")
    result = await drive_materials.execute(broker, "owner", "selected-account", {"semantic_goal": GOAL})
    assert result["status"] == "no_verified_match" and not result["sources"]
    assert result["unsupported_files"][0]["id"] == "broken"


async def test_binary_proxy_read_is_bounded_and_preserves_bytes(monkeypatch):
    import httpx

    from app.config import Settings
    from app.pipedream_connect import PipedreamClient

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"\x00\xffPDF")), **kwargs))
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    monkeypatch.setattr(client, "_oauth_token", AsyncMock(return_value="server-token"))
    assert await client._request("GET", "/proxy", response_bytes_limit=5) == b"\x00\xffPDF"
    with pytest.raises(PipedreamConnectError, match="limit"):
        await client._request("GET", "/proxy", response_bytes_limit=4)
    with pytest.raises(ValueError, match="bounded GET"):
        await client._request("POST", "/proxy", response_bytes_limit=5)


async def test_signed_contract_upgrade_preserves_old_pack_and_account_permissions(database, monkeypatch):
    import hashlib
    import hmac

    from sqlalchemy import select

    from app import pipedream_connect, source_contracts
    from app.config import Settings
    from app.models import (
        BrokerCapabilityPack,
        CapabilityManifest,
        ToolConnection,
        ToolKind,
        Workspace,
    )

    config = Settings(connector_engineer_signing_key="source-contract-signing-key-0000000000000")
    monkeypatch.setattr(source_contracts, "get_settings", lambda: config)
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: config)
    definition = {"capabilities": [capability("google-drive", drive_materials.OPERATION)]}
    pack = BrokerCapabilityPack(id="old-pack", backend="pipedream", provider_slug="google-drive",
        display_name="Drive", version=1, status="released", definition=definition,
        definition_hash=hashlib.sha256(pipedream_connect._canonical(definition)).hexdigest())
    pack.signature = hmac.new(config.connector_release_signing_key.encode(),
        pipedream_connect._pack_signature_payload(pack), hashlib.sha256).hexdigest()
    async with database() as session:
        session.add(Workspace(id="w", name="Owner"))
        session.add(pack)
        tool = ToolConnection(id="drive", workspace_id="w", slug="google-drive", display_name="Drive",
            kind=ToolKind.oauth, enabled=True, allowed_operations=[], config={"managed_by": "pipedream",
                "account_id": "selected-account", "external_user_id": "owner", "custom_setting": "preserve",
                "capability_pack_id": pack.id, "capability_pack_hash": pack.definition_hash})
        manifest = CapabilityManifest(tool_id="drive", workspace_id="w", provider_type="oauth",
                                      status="verified", manifest=deepcopy(definition))
        session.add_all([tool, manifest])
        await session.flush()
        before = deepcopy(pack.definition)
        await source_contracts.refresh_source_contract(session, tool, manifest)
        new_id = tool.config["capability_pack_id"]
        assert new_id != pack.id and tool.allowed_operations == []
        assert tool.config["account_id"] == "selected-account" and tool.config["external_user_id"] == "owner"
        assert tool.config["custom_setting"] == "preserve"
        upgraded = await session.get(BrokerCapabilityPack, new_id)
        assert pipedream_connect.pack_signature_valid(upgraded)
        assert pack.definition == before and pipedream_connect.pack_signature_valid(pack)
        await source_contracts.refresh_source_contract(session, tool, manifest)
        assert tool.config["capability_pack_id"] == new_id
        assert len((await session.scalars(select(BrokerCapabilityPack))).all()) == 2


async def test_combined_content_bound_discloses_unreviewed_documents(monkeypatch):
    monkeypatch.setattr(drive_materials, "retrieval_hints", AsyncMock(return_value=[]))
    rows = [file(str(index), "Notes " + str(index)) for index in range(3)]
    broker = Broker(lambda method, target, kw: {"files": rows} if "q=" in target else b"a" * 60_000)
    async def assess(goal, documents):
        assert len(documents) == 2 and all(len(doc["text"]) == 60_000 for doc in documents)
        return {doc["id"]: material_relevance.IdentifiedAssessment(candidate_id=doc["id"],
            relevant=True, reason="Reviewed the entire supplied source", excerpts=["a" * 100]) for doc in documents}
    monkeypatch.setattr(drive_materials, "assess_materials", assess)
    result = await drive_materials.execute(broker, "owner", "selected-account", {"semantic_goal": GOAL})
    assert len(result["documents"]) == 2 and not result["ret"]["isComplete"]
    assert "120 KB" in result["unsupported_files"][0]["reason"]


async def test_fulltext_candidates_use_provider_relevance_without_order_by(monkeypatch):
    monkeypatch.setattr(drive_materials, "retrieval_hints", AsyncMock(return_value=["ambient music"]))
    queries = []

    def respond(method, target, kwargs):
        params = parse_qs(urlsplit(target).query)
        queries.append(params)
        if "fullText contains" in params["q"][0]:
            if "orderBy" in params:
                raise PipedreamConnectError("Sorting is not supported for queries with fullText terms",
                                            retryable=False, status_code=400)
            return {"files": [], **({"nextPageToken": "page-2"} if "pageToken" not in params else {})}
        assert params["orderBy"] == ["modifiedTime desc"]
        return {"files": []}

    result = await drive_materials.execute(Broker(respond), "owner", "selected-account", {"semantic_goal": GOAL})
    assert result["status"] == "no_verified_match"
    assert len(queries) == 3 and queries[1]["pageToken"] == ["page-2"]


async def test_large_candidate_inventory_is_ranked_without_exceeding_model_budget(monkeypatch):
    import random
    import string

    from app.model_inputs import bounded_input

    rng = random.Random(17)
    candidates = [{**file(f"candidate_{i}", "".join(rng.choices(string.ascii_letters, k=500))),
                   "description": "".join(rng.choices(string.ascii_letters, k=500))}
                  for i in range(200)]
    calls = []

    async def infer(goal, evidence, schema, instruction):
        bounded_input({"objective": goal, "evidence": evidence})
        calls.append([item["id"] for item in evidence])
        # A relevant candidate at the end of the inventory must reach the final ranking.
        ordered = sorted(evidence, key=lambda item: int(item["id"].split("_")[1]), reverse=True)
        return material_relevance.CandidateSelection(candidate_ids=[item["id"] for item in ordered[:12]])

    monkeypatch.setattr(material_relevance, "_infer", infer)
    selected = await material_relevance.select_candidates(GOAL, candidates)
    assert len(calls) > 1
    assert set().union(*(set(call) for call in calls)) == {item["id"] for item in candidates}
    assert [item["id"] for item in selected] == [f"candidate_{i}" for i in range(199, 187, -1)]


async def test_download_restricted_file_does_not_abort_other_material_reads(monkeypatch):
    monkeypatch.setattr(drive_materials, "retrieval_hints", AsyncMock(return_value=[]))
    restricted = {**file("restricted", "Commercial terms"), "capabilities": {"canDownload": False}}
    useful = {**file("useful", "Project brief"), "capabilities": {"canDownload": True}}
    text = "A background music service for small restaurants."

    def respond(method, target, kwargs):
        if "q=" in target:
            return {"files": [restricted, useful]}
        if "/restricted/" in target:
            raise PipedreamConnectError("Download forbidden", retryable=False, status_code=403)
        return text.encode()

    async def assess(goal, documents):
        assert [doc["id"] for doc in documents] == ["useful"]
        return {"useful": material_relevance.IdentifiedAssessment(candidate_id="useful", relevant=True,
            reason="Project brief", excerpts=[text])}

    monkeypatch.setattr(drive_materials, "assess_materials", assess)
    broker = Broker(respond)
    result = await drive_materials.execute(broker, "owner", "selected-account", {"semantic_goal": GOAL})
    assert result["status"] == "matched" and not result["ret"]["isComplete"]
    assert result["unsupported_files"][0]["id"] == "restricted"
    assert "download" in result["unsupported_files"][0]["reason"].lower()
    assert all("/restricted/" not in target for _, target, _ in broker.calls)
    assert "canDownload" in parse_qs(urlsplit(broker.calls[0][1]).query)["fields"][0]


@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_live_authorization_and_provider_errors_still_stop_discovery(monkeypatch, status):
    monkeypatch.setattr(drive_materials, "retrieval_hints", AsyncMock(return_value=[]))
    assess = AsyncMock()
    monkeypatch.setattr(drive_materials, "assess_materials", assess)

    def respond(method, target, kwargs):
        if "q=" in target:
            return {"files": [file("source", "Brief")]}
        raise PipedreamConnectError("Provider refused content", retryable=status in {429, 503},
                                    status_code=status)

    with pytest.raises(PipedreamConnectError) as error:
        await drive_materials.execute(Broker(respond), "owner", "selected-account", {"semantic_goal": GOAL})
    assert error.value.status_code == status
    assess.assert_not_awaited()


async def test_only_restricted_materials_cannot_feed_a_presentation(monkeypatch):
    monkeypatch.setattr(drive_materials, "retrieval_hints", AsyncMock(return_value=[]))
    broker = Broker(lambda *_: {"files": [
        {**file("restricted", "Brief"), "capabilities": {"canDownload": False}}]})
    result = await drive_materials.execute(broker, "owner", "selected-account", {"semantic_goal": GOAL})
    assert result["status"] == "no_verified_match" and not result["sources"]
    assert not result["documents"] and len(broker.calls) == 1
    context = {"steps": {"discover": step_context_value(result, drive_materials.OPERATION)}}
    with pytest.raises(DriveFolderIdentityError, match="No folder ID is required"):
        resolve_value("{{steps.discover.sources}}", context)


@pytest.mark.parametrize("ids", [["unknown"], ["known", "known"]])
async def test_candidate_ranking_cannot_invent_or_duplicate_identities(monkeypatch, ids):
    candidates = [file("known", "Brief")] + [file(str(i), "Notes") for i in range(12)]
    monkeypatch.setattr(material_relevance, "_infer", AsyncMock(return_value=
        material_relevance.CandidateSelection(candidate_ids=ids)))
    with pytest.raises(ValueError, match="unknown or duplicate"):
        await material_relevance.select_candidates(GOAL, candidates)
