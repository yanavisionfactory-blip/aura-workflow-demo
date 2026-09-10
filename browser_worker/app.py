"""Credential-isolated browser execution worker for AURA.

The control plane sends only a fixed target URL, an allow-listed capability,
and approved inputs. Every browser request is restricted to public HTTPS
addresses so pages cannot pivot into Railway or other private infrastructure.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from contextlib import asynccontextmanager
from functools import lru_cache
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from playwright.async_api import Page, Route, async_playwright
from pydantic import BaseModel, Field, HttpUrl


WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")
MAX_PAGE_TEXT = 60_000
browser_slots = asyncio.Semaphore(int(os.environ.get("BROWSER_CONCURRENCY", "2")))

app = FastAPI(title="AURA Browser Worker", version="1.0")


class DiscoverRequest(BaseModel):
    target_url: HttpUrl


class ExecuteRequest(BaseModel):
    target_url: HttpUrl
    capability: str
    input: dict = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)


class ReadRequest(BaseModel):
    url: HttpUrl


def require_worker_token(authorization: str | None = Header(default=None)) -> None:
    if not WORKER_TOKEN or authorization != f"Bearer {WORKER_TOKEN}":
        raise HTTPException(401, "Unauthorized browser worker request")


@lru_cache(maxsize=512)
def _host_is_public(hostname: str) -> bool:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(value).is_global for value in addresses)


async def public_https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "Browser targets must be public HTTPS URLs")
    if not await asyncio.to_thread(_host_is_public, parsed.hostname):
        raise HTTPException(422, "Browser targets may not use private or reserved networks")
    return value


async def _guard_route(route: Route) -> None:
    parsed = urlparse(route.request.url)
    if parsed.scheme in {"data", "blob"}:
        await route.continue_()
        return
    try:
        await public_https_url(route.request.url)
    except HTTPException:
        await route.abort("blockedbyclient")
        return
    await route.continue_()


@asynccontextmanager
async def rendered_page(url: str):
    await public_https_url(url)
    async with browser_slots:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 AURA/1.0"
                ),
            )
            page = await context.new_page()
            await page.route("**/*", _guard_route)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(1_000)
                yield page
            finally:
                await context.close()
                await browser.close()


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    return parsed.scheme, parsed.hostname or "", parsed.port


async def _connector_url(target_url: str, path: str | None) -> str:
    if not path:
        return await public_https_url(target_url)
    resolved = urljoin(target_url.rstrip("/") + "/", path)
    if _origin(resolved) != _origin(target_url):
        raise HTTPException(422, "Connector navigation must stay on its configured origin")
    return await public_https_url(resolved)


async def page_evidence(page: Page) -> dict:
    body = await page.locator("body").inner_text(timeout=10_000)
    links = await page.locator("a[href]").evaluate_all(
        """nodes => nodes.slice(0, 80).map(node => ({
          text: (node.innerText || node.textContent || '').trim().slice(0, 300),
          url: node.href
        })).filter(item => item.text && item.url.startsWith('https://'))"""
    )
    return {
        "url": page.url,
        "title": await page.title(),
        "text": body[:MAX_PAGE_TEXT],
        "links": links,
    }


def _field_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


async def fill_form(page: Page, values: dict) -> list[str]:
    controls = page.locator("input, textarea, select")
    filled: list[str] = []
    for supplied_name, supplied_value in values.items():
        expected = _field_key(str(supplied_name))
        selected = None
        for index in range(await controls.count()):
            control = controls.nth(index)
            attributes = [
                await control.get_attribute("name"),
                await control.get_attribute("id"),
                await control.get_attribute("aria-label"),
                await control.get_attribute("placeholder"),
            ]
            if expected and any(_field_key(item) == expected for item in attributes):
                selected = control
                break
        if selected is None:
            raise HTTPException(422, f"No form field matches {supplied_name!r}")
        tag = await selected.evaluate("element => element.tagName.toLowerCase()")
        control_type = (await selected.get_attribute("type") or "").casefold()
        if tag == "select":
            await selected.select_option(str(supplied_value))
        elif control_type in {"checkbox", "radio"}:
            if bool(supplied_value):
                await selected.check()
            else:
                await selected.uncheck()
        else:
            await selected.fill(str(supplied_value))
        filled.append(str(supplied_name))
    return filled


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "configured": bool(WORKER_TOKEN)}


@app.post("/v1/discover", dependencies=[Depends(require_worker_token)])
async def discover(payload: DiscoverRequest) -> dict:
    target = str(payload.target_url)
    async with rendered_page(target) as page:
        form_count = await page.locator("form").count()
        capabilities = [
            {
                "name": "browser.page.read",
                "description": "Read the current rendered page or a same-origin path.",
                "permission_scope": "read",
                "requires_approval": False,
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "additionalProperties": False,
                },
                "output_schema": {"type": "object"},
            }
        ]
        if form_count:
            capabilities.append(
                {
                    "name": "browser.form.submit",
                    "description": (
                        "Fill named fields and submit a form after explicit workflow approval."
                    ),
                    "permission_scope": "write",
                    "requires_approval": True,
                    "input_schema": {
                        "type": "object",
                        "required": ["fields"],
                        "properties": {
                            "fields": {"type": "object"},
                            "submit_text": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "output_schema": {"type": "object"},
                }
            )
        return {
            "name": await page.title() or urlparse(target).hostname,
            "description": "Isolated browser connector for one public web application.",
            "capabilities": capabilities,
        }


@app.post("/v1/execute", dependencies=[Depends(require_worker_token)])
async def execute(payload: ExecuteRequest) -> dict:
    target = await _connector_url(str(payload.target_url), payload.input.get("path"))
    async with rendered_page(target) as page:
        if payload.capability == "browser.page.read":
            return await page_evidence(page)
        if payload.capability != "browser.form.submit":
            raise HTTPException(422, "Unknown browser capability")
        fields = payload.input.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise HTTPException(422, "browser.form.submit requires named fields")
        filled = await fill_form(page, fields)
        submit_text = str(payload.input.get("submit_text") or "").strip()
        button = (
            page.get_by_role("button", name=submit_text, exact=False)
            if submit_text
            else page.locator('button[type="submit"], input[type="submit"]').first
        )
        if await button.count() == 0:
            button = page.get_by_role("button", name=re.compile("submit", re.I)).first
        if await button.count() == 0:
            raise HTTPException(422, "No submit control was found")
        await button.click(timeout=10_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            await page.wait_for_timeout(1_000)
        return {
            "submitted": True,
            "filled_fields": filled,
            **(await page_evidence(page)),
        }


@app.post("/v1/search", dependencies=[Depends(require_worker_token)])
async def search(payload: SearchRequest) -> dict:
    search_url = "https://html.duckduckgo.com/html/?q=" + quote_plus(payload.query)
    async with rendered_page(search_url) as page:
        nodes = page.locator(".result")
        results: list[dict] = []
        for index in range(min(await nodes.count(), payload.limit)):
            node = nodes.nth(index)
            link = node.locator(".result__a").first
            if await link.count() == 0:
                continue
            href = await link.get_attribute("href") or ""
            parsed = urlparse(href)
            if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
                href = parse_qs(parsed.query).get("uddg", [href])[0]
            if not href.startswith("https://"):
                continue
            snippet = node.locator(".result__snippet").first
            results.append(
                {
                    "title": (await link.inner_text()).strip(),
                    "url": href,
                    "snippet": (
                        (await snippet.inner_text()).strip()
                        if await snippet.count()
                        else ""
                    ),
                }
            )
        return {"query": payload.query, "results": results}


@app.post("/v1/read", dependencies=[Depends(require_worker_token)])
async def read(payload: ReadRequest) -> dict:
    async with rendered_page(str(payload.url)) as page:
        return await page_evidence(page)
