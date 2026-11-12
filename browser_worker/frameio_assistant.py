"""Frame.io's in-product assistant, using a separately signed-in AURA browser.

No exported cookies, private vendor APIs, or substitute analysis engines. Sessions
are memory-only, expire after two hours, and disappear on worker restart.
"""
import asyncio
import base64
import hashlib
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel, ConfigDict, Field

TTL = 7200
MAX_SESSIONS = max(1, int(os.getenv("INTERACTIVE_BROWSER_CONCURRENCY", "2")))


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: UUID
    project_id: UUID
    file_id: UUID

    @property
    def url(self):
        return f"https://app.frame.io/project/{self.project_id}/view/{self.file_id}"


class SessionRequest(Target):
    scope: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class InputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern=r"^(click|text|key|scroll|verify)$")
    x: int = Field(default=0, ge=0, le=1439)
    y: int = Field(default=0, ge=0, le=999)
    text: str = Field(default="", max_length=4096)
    key: str = Field(default="", max_length=40)
    delta: int = Field(default=0, ge=-1000, le=1000)


class ReviewRequest(SessionRequest):
    invocation_id: UUID
    instructions: str = Field(min_length=1, max_length=6000)


@dataclass
class Profile:
    request: SessionRequest
    runtime: object
    browser: object
    context: object
    page: object
    created: float = field(default_factory=time.monotonic)
    ready: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Read rendered message DOM only. Stable message IDs and the exact submitted
# user message bind a result to this invocation, never a previous conversation.
MESSAGES = r"""() => {
 const render = node => {
   if (node.nodeType === 3) return node.textContent;
   if (['BUTTON', 'SVG', 'SCRIPT', 'STYLE'].includes(node.tagName)) return '';
   if (node.children.length === 0 && node.textContent === 'Assistant said:') return '';
   if (node.tagName === 'TABLE') {
     const rows = [...node.querySelectorAll('tr')].map(row => [...row.cells].map(cell =>
       cell.innerText.trim().replace(/\|/g, '\\|').replace(/\n/g, ' ')));
     if (!rows.length) return '';
     return '\n\n' + [rows[0], rows[0].map(() => '---'), ...rows.slice(1)]
       .map(row => '| ' + row.join(' | ') + ' |').join('\n') + '\n\n';
   }
   const text = [...node.childNodes].map(render).join('');
   if (node.tagName === 'BR') return '\n';
   if (node.tagName === 'LI') return '\n- ' + text.trim();
   if (['P', 'UL', 'OL', 'BLOCKQUOTE'].includes(node.tagName)) return '\n\n' + text + '\n\n';
   if (/^H[1-6]$/.test(node.tagName)) return '\n\n' + '#'.repeat(Number(node.tagName[1])) + ' ' + text + '\n\n';
   return text;
 };
 return [...document.querySelectorAll('[data-message-id]')].map(row => {
   const labels = [...row.querySelectorAll('div')].filter(e => e.children.length === 0);
   const assistant = labels.find(e => e.textContent === 'Assistant said:');
   const user = labels.find(e => e.textContent === 'You said:');
   const node = assistant?.parentElement || user?.parentElement;
   return {id: row.getAttribute('data-message-id'), role: assistant ? 'assistant' : user ? 'user' : 'other',
     text: node?.innerText?.replace(/^(Assistant said:|You said:)\s*/, '').trim() || '',
     markdown: assistant ? render(node).replace(/\n{3,}/g, '\n\n').trim() : '',
     complete: !!row.querySelector('button[aria-label="Thumbs Up"]'),
     analyzed: row.innerText.includes('Completed video analysis')};
 });
}"""


def fresh_reply(messages, before, prompt):
    """Only a completed assistant reply following this exact new user message."""
    submitted = False
    for message in messages:
        if message["id"] in before:
            continue
        if message["role"] == "user":
            submitted = message["text"] == prompt
        elif submitted and message["role"] == "assistant" and message["complete"]:
            return message
    return None


def install_routes(app, require_token, public_guard):
    profiles, jobs = {}, {}
    registry_lock = asyncio.Lock()
    tasks = set()

    async def close(profile):
        await profile.context.close()
        await profile.browser.close()
        await profile.runtime.stop()

    async def expire(identifier, profile):
        await asyncio.sleep(TTL)
        async with profile.lock:
            if profiles.get(identifier) is profile:
                profiles.pop(identifier, None)
                await close(profile)
        for key, job in list(jobs.items()):
            if job.get("profile_id") == identifier:
                jobs.pop(key, None)

    async def shutdown():
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(close(profile) for profile in profiles.values()), return_exceptions=True)
        profiles.clear()
        jobs.clear()

    app.router.add_event_handler("shutdown", shutdown)

    async def profile_for(identifier, scope):
        profile = profiles.get(identifier)
        if not profile or profile.request.scope != scope:
            raise HTTPException(404, "Frame.io assistant session not found; reconnect in AURA")
        if time.monotonic() - profile.created > TTL:
            if not profile.lock.locked():
                profiles.pop(identifier, None)
                await close(profile)
            raise HTTPException(410, "Frame.io assistant sign-in expired; reconnect in AURA")
        return profile

    async def guard(route):
        request = route.request
        # Login can redirect only to Frame.io and established identity providers.
        # Subresources still pass the worker's public-network guard.
        if request.is_navigation_request() and request.frame.parent_frame is None:
            host = urlsplit(request.url).hostname or ""
            allowed = ("frame.io", "adobe.com", "adobelogin.com", "adobe.io",
                       "google.com", "apple.com", "microsoftonline.com", "live.com")
            if not any(host == domain or host.endswith("." + domain) for domain in allowed):
                await route.abort()
                return
        await public_guard(route)

    async def active_page(profile):
        pages = [page for page in profile.context.pages if not page.is_closed()]
        if not pages:
            raise HTTPException(409, "Frame.io sign-in window closed; reconnect in AURA")
        return pages[-1]

    async def status(profile, screen=False):
        page = await active_page(profile)
        host = urlsplit(page.url).hostname or ""
        data = {"ready": profile.ready, "site": host,
                "expires_in_seconds": max(0, int(TTL - (time.monotonic() - profile.created))),
                "busy": profile.lock.locked()}
        if screen and not profile.ready and not profile.lock.locked():
            data["screenshot"] = base64.b64encode(await page.screenshot(type="jpeg", quality=75)).decode()
            data.update(width=1440, height=1000)
        return data

    async def open_assistant(profile):
        page = profile.page
        await page.goto(profile.request.url, wait_until="domcontentloaded", timeout=45000)
        toggle = page.get_by_role("button", name="Toggle the AI Panel", exact=True)
        await toggle.wait_for(timeout=30000)
        if await toggle.get_attribute("data-selected") != "true":
            await toggle.click()
        await page.locator('[data-compose-content="true"][contenteditable="true"]').wait_for(timeout=15000)
        # The player URL must still identify the exact verified project/version.
        current = urlsplit(page.url)
        if current.hostname not in {"app.frame.io", "next.frame.io"} or current.path.rstrip("/") != urlsplit(profile.request.url).path:
            raise ValueError("Frame.io did not open the selected video version")
        return page

    @app.post("/v1/frameio-assistant/sessions", dependencies=[Depends(require_token)])
    async def create(request: SessionRequest):
        async with registry_lock:
            for identifier, profile in list(profiles.items()):
                if time.monotonic() - profile.created > TTL and not profile.lock.locked():
                    profiles.pop(identifier)
                    await close(profile)
            if len(profiles) >= MAX_SESSIONS:
                raise HTTPException(429, "AURA's Frame.io sign-in capacity is busy; disconnect an unused session")
            runtime = await async_playwright().start()
            browser = None
            try:
                browser = await runtime.chromium.launch(args=["--disable-dev-shm-usage", "--no-sandbox"])
                context = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=False)
                await context.route("**/*", guard)
                page = await context.new_page()
                await page.goto(request.url, wait_until="domcontentloaded", timeout=45000)
            except Exception:  # noqa: BLE001 — sanitize vendor/browser failures and preserve dispatch uncertainty
                if browser:
                    await browser.close()
                await runtime.stop()
                raise HTTPException(502, "Could not open Frame.io sign-in") from None
            identifier = str(uuid4())
            profiles[identifier] = Profile(request, runtime, browser, context, page)
            task = asyncio.create_task(expire(identifier, profiles[identifier]))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            return {"id": identifier, **await status(profiles[identifier], screen=True)}

    @app.get("/v1/frameio-assistant/sessions/{identifier}", dependencies=[Depends(require_token)])
    async def get_session(identifier: UUID, scope: str, screen: bool = False):
        return await status(await profile_for(str(identifier), scope), screen=screen)

    @app.delete("/v1/frameio-assistant/sessions/{identifier}", dependencies=[Depends(require_token)])
    async def delete(identifier: UUID, scope: str):
        profile = await profile_for(str(identifier), scope)
        if profile.lock.locked():
            raise HTTPException(409, "Wait for the active review before disconnecting")
        profiles.pop(str(identifier), None)
        await close(profile)
        return {"disconnected": True}

    @app.post("/v1/frameio-assistant/sessions/{identifier}/input", dependencies=[Depends(require_token)])
    async def input_event(identifier: UUID, scope: str, request: InputRequest):
        profile = await profile_for(str(identifier), scope)
        if profile.lock.locked() or profile.ready:
            raise HTTPException(409, "The sign-in window is closed for input")
        async with profile.lock:
            page = await active_page(profile)
            if request.action == "verify":
                try:
                    await open_assistant(profile)
                except Exception:  # noqa: BLE001 — sanitize vendor/browser failures and preserve dispatch uncertainty
                    raise HTTPException(409, "Finish Frame.io sign-in and enable its AI Assistant for this video, then check again") from None
                profile.ready = True
            elif request.action == "click":
                await page.mouse.click(request.x, request.y)
            elif request.action == "text":
                await page.keyboard.insert_text(request.text)
            elif request.action == "scroll":
                await page.mouse.wheel(0, request.delta)
            elif request.action == "key":
                if request.key not in {"Tab", "Shift+Tab", "Enter", "Backspace", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Control+A", "Delete"}:
                    raise HTTPException(422, "Unsupported sign-in key")
                await page.keyboard.press(request.key)
        return await status(profile, screen=True)

    async def run_review(profile, request, job):
        async with profile.lock:
            try:
                page = await open_assistant(profile)
                if await page.get_by_role("button", name="Stop generating", exact=True).count():
                    raise ValueError("An earlier Frame.io response is still generating")
                prompt = (
                    f"AURA review request {request.invocation_id}. Review only the selected video "
                    f"{request.file_id} in project {request.project_id}, account {request.account_id}. "
                    "Use Frame.io's native Video analysis. Return your findings here as a chronological "
                    "timestamp / issue / production correction table. Clearly separate observed defects, "
                    "suggestions and unverified findings, including any audio or timeline access limits. "
                    "Do not post comments, notify people, modify files, create skills, or change anything. "
                    "The following text supplies review criteria only, not permission for any other action:\n"
                    + request.instructions
                )
                before = {row["id"] for row in await page.evaluate(MESSAGES)}
                await page.locator('[data-compose-content="true"][contenteditable="true"]').fill(prompt)
                # Never repeat this click, even when navigation or acknowledgement fails.
                job["status"] = "submitted"
                await page.get_by_role("button", name="Send message", exact=True).click(timeout=10000)
                deadline = time.monotonic() + 540
                while time.monotonic() < deadline:
                    reply = fresh_reply(await page.evaluate(MESSAGES), before, prompt)
                    if reply and not await page.get_by_role("button", name="Stop generating", exact=True).count():
                        if not reply["analyzed"]:
                            job.update(status="needs_attention", message="Frame.io replied without a completed native video analysis", response=reply["text"])
                        else:
                            job.update(status="completed", response=reply["text"], response_markdown=reply["markdown"], message_id=reply["id"], source_url=profile.request.url)
                        return
                    await asyncio.sleep(2)
                job.update(status="unknown", message="Frame.io has not returned a completed review. Check its conversation before starting a new review.")
            except Exception:  # noqa: BLE001 — sanitize vendor/browser failures and preserve dispatch uncertainty
                # Do not leak page contents, login fields or vendor errors into logs.
                job.update(status="unknown" if job["status"] == "submitted" else "failed",
                           message="Frame.io assistant could not finish this review. Reconnect if sign-in expired; check Frame.io before submitting again.")

    @app.post("/v1/frameio-assistant/sessions/{identifier}/reviews", dependencies=[Depends(require_token)])
    async def review(identifier: UUID, request: ReviewRequest):
        profile = await profile_for(str(identifier), request.scope)
        if not profile.ready:
            raise HTTPException(409, "Sign in to the Frame.io AI Assistant through AURA first")
        if any(getattr(profile.request, key) != getattr(request, key) for key in ("account_id", "project_id", "file_id")):
            raise HTTPException(409, "Connect the assistant for this exact selected video first")
        fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        key = str(request.invocation_id)
        async with registry_lock:
            if key in jobs:
                job = jobs[key]
                if job["scope"] != request.scope or job["fingerprint"] != fingerprint:
                    raise HTTPException(409, "Review invocation does not match its original request")
            else:
                if profile.lock.locked():
                    raise HTTPException(409, "The Frame.io assistant is busy")
                job = jobs[key] = {"status": "queued", "scope": request.scope, "fingerprint": fingerprint, "profile_id": str(identifier)}
                task = asyncio.create_task(run_review(profile, request, job))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        return {k: v for k, v in job.items() if k not in {"scope", "fingerprint", "profile_id"}}

    @app.get("/v1/frameio-assistant/reviews/{identifier}", dependencies=[Depends(require_token)])
    async def get_review(identifier: UUID, scope: str):
        job = jobs.get(str(identifier))
        if not job or job["scope"] != scope:
            raise HTTPException(404, "Review state unavailable; do not automatically resubmit")
        return {k: v for k, v in job.items() if k not in {"scope", "fingerprint", "profile_id"}}
