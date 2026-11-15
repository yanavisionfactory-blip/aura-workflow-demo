"""Create a populated Google Slides deck in one import, then verify saved text."""

import asyncio
import base64
import json
import re
from urllib.parse import quote
from uuid import uuid4

from jsonschema import validate

from .presentation_content import PRESENTATION_SCHEMA, render_timeline


def verify_slides(result, presentation):
    slides = result.get("slides") if isinstance(result, dict) else None
    if not isinstance(slides, list) or len(slides) != len(presentation["phases"]):
        raise ValueError("Saved slide count does not match the approved presentation")

    def texts(value):
        if isinstance(value, dict):
            if isinstance(value.get("textRun"), dict):
                yield value["textRun"].get("content", "")
            for child in value.values():
                yield from texts(child)
        elif isinstance(value, list):
            for child in value:
                yield from texts(child)

    for slide, phase in zip(slides, presentation["phases"], strict=True):
        text = " ".join(" ".join(texts(slide)).split())
        expected = [presentation["title"], phase["title"], *phase["items"]]
        if any(" ".join(value.split()) not in text for value in expected):
            raise ValueError("Saved slide text does not match the approved content")


async def execute(broker, external_user_id, account_id, arguments):
    from .pipedream_connect import PipedreamConnectError

    if set(arguments) != {"presentation"}:
        raise ValueError("A populated presentation cannot also copy an existing deck")
    presentation = arguments["presentation"]
    validate(presentation, PRESENTATION_SCHEMA)
    if presentation.get("layout") != "slides":
        raise ValueError("Google Slides creation requires layout=slides")
    verified = await broker.verify_account(external_user_id, "google_slides", account_id)
    if verified.get("ok") is not True:
        raise PipedreamConnectError("Google Slides authorization is required", retryable=False, status_code=403)
    pptx = await asyncio.to_thread(render_timeline, presentation)
    boundary = "aura_" + uuid4().hex
    metadata = json.dumps({"name": presentation["title"],
        "mimeType": "application/vnd.google-apps.presentation"}, ensure_ascii=False).encode()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
        + metadata + f"\r\n--{boundary}\r\nContent-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation\r\n\r\n".encode()
        + pptx + f"\r\n--{boundary}--\r\n".encode())

    def proxy(target):
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        return f"/v1/connect/{quote(broker.settings.pipedream_project_id, safe='')}/proxy/{encoded}"

    routing = {"external_user_id": external_user_id, "account_id": account_id}
    # One non-retried mutation imports already populated slide bytes. There is
    # no blank create followed by a second possibly failed content mutation.
    receipt = await broker._request("POST", proxy(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,mimeType,webViewLink"),
        params=routing, headers={"Content-Type": "application/octet-stream",
            "x-pd-proxy-Content-Type": f"multipart/related; boundary={boundary}"},
        content=body, retry_safe=False)
    resource_id = receipt.get("id") if isinstance(receipt, dict) else None
    if not isinstance(resource_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", resource_id):
        raise PipedreamConnectError("Google Slides creation did not return a verifiable resource ID",
                                   retryable=False, effect_uncertain=True)
    url = f"https://docs.google.com/presentation/d/{resource_id}/edit"
    try:
        saved = await broker._request("GET", proxy(
            f"https://slides.googleapis.com/v1/presentations/{resource_id}"), params=routing)
        if saved.get("presentationId") != resource_id:
            raise ValueError("Saved presentation identity changed")
        verify_slides(saved, presentation)
    except Exception as exc:
        raise PipedreamConnectError(
            f"Presentation was created at {url}, but saved-content verification did not finish. "
            "Read this existing presentation before considering another create.",
            retryable=False, effect_uncertain=True) from exc
    return {"ret": saved, "presentationId": resource_id, "url": url,
        "import_receipt": receipt, "verification": {"saved_content_matches": True,
            "slide_count": len(saved["slides"])},
        "aura_transport": "google_slides_populated_import_v1",
        "exports": {"$summary": f"Created and verified {len(saved['slides'])} populated slides."}}
