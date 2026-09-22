"""Credential-isolated browser execution worker for AURA.

The control plane sends only a fixed target URL, an allow-listed capability,
and approved inputs. Every browser request is restricted to public HTTPS
addresses so pages cannot pivot into Railway or other private infrastructure.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import re
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from statistics import mean
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


class TikTokScreenRequest(BaseModel):
    query: str = Field(default="public TikTok creators", min_length=1, max_length=300)
    max_candidates: int = Field(default=5, ge=1, le=10)
    videos_per_creator: int = Field(default=12, ge=10, le=30)
    min_followers: int = Field(default=15_000, ge=1)
    min_videos: int = Field(default=10, ge=10)
    min_trimmed_mean_views: int = Field(default=15_000, ge=1)
    min_original_audio_ratio: float = Field(default=0.3, ge=0, le=1)
    recency_days: int = Field(default=5, ge=1, le=30)


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
async def public_browser_context():
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
            try:
                yield context
            finally:
                await context.close()
                await browser.close()


async def open_public_page(context, url: str, *, settle_ms: int = 1_000) -> Page:
    await public_https_url(url)
    page = await context.new_page()
    await page.route("**/*", _guard_route)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(settle_ms)
        return page
    except Exception:
        await page.close()
        raise


@asynccontextmanager
async def rendered_page(url: str):
    async with public_browser_context() as context:
        page = await open_public_page(context, url)
        try:
            yield page
        finally:
            await page.close()


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


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)


async def _page_json_documents(page: Page) -> list[object]:
    texts = await page.locator("script[type='application/json']").evaluate_all(
        "nodes => nodes.map(node => node.textContent || '').filter(Boolean)"
    )
    documents: list[object] = []
    for value in texts:
        try:
            documents.append(json.loads(value))
        except (TypeError, ValueError):
            continue
    return documents


def _user_info(documents: list[object]) -> tuple[dict, dict] | None:
    for document in documents:
        for value in _walk_json(document):
            user = value.get("user")
            stats = value.get("stats")
            if (
                isinstance(user, dict)
                and isinstance(stats, dict)
                and (user.get("uniqueId") or user.get("unique_id"))
                and any(key in stats for key in ("followerCount", "follower_count"))
            ):
                return user, stats
    return None


def _video_items(documents: list[object]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for document in documents:
        for value in _walk_json(document):
            stats = value.get("stats")
            music = value.get("music")
            if not isinstance(stats, dict) or not isinstance(music, dict):
                continue
            if not any(key in stats for key in ("playCount", "play_count")):
                continue
            if not any(key in value for key in ("createTime", "create_time")):
                continue
            item_id = str(value.get("id") or value.get("aweme_id") or "")
            signature = item_id or json.dumps(
                [
                    stats.get("playCount", stats.get("play_count")),
                    value.get("createTime", value.get("create_time")),
                    music.get("id", music.get("title")),
                ],
                sort_keys=True,
            )
            if signature in seen:
                continue
            seen.add(signature)
            items.append(value)
    return items


def _integer(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _profile_url(value: str) -> str | None:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold()
    if hostname != "tiktok.com" and not hostname.endswith(".tiktok.com"):
        return None
    match = re.search(r"/@([^/?#]+)", parsed.path)
    if not match:
        return None
    return f"https://www.tiktok.com/@{match.group(1)}"


def _profile_urls(values: list[str], limit: int) -> list[str]:
    results: list[str] = []
    for value in values:
        profile = _profile_url(value)
        if profile and profile not in results:
            results.append(profile)
        if len(results) >= limit:
            break
    return results


def _original_audio(item: dict) -> bool:
    music = item.get("music") if isinstance(item.get("music"), dict) else {}
    explicit = music.get("original")
    if isinstance(explicit, bool):
        return explicit
    title = str(music.get("title") or "").casefold()
    return title.startswith("original sound") or title.startswith("original audio")


def _management_contact(signature: str) -> bool:
    return bool(
        re.search(
            r"\b(?:management|manager|managed\s+by|mgmt|agency|talent\s+agency|bookings?)\b",
            signature,
            re.IGNORECASE,
        )
    )


def _public_email(signature: str) -> str | None:
    match = re.search(
        r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
        signature,
    )
    return match.group(1) if match else None


def _creator_metrics(
    profile_url: str,
    user: dict,
    stats: dict,
    items: list[dict],
    policy: TikTokScreenRequest,
) -> dict:
    followers = _integer(stats.get("followerCount", stats.get("follower_count"))) or 0
    published = _integer(stats.get("videoCount", stats.get("video_count"))) or 0
    views = [
        value
        for item in items
        if (
            value := _integer(
                (item.get("stats") or {}).get(
                    "playCount", (item.get("stats") or {}).get("play_count")
                )
            )
        )
        is not None
    ]
    ordered = sorted(views)
    trim = math.floor(len(ordered) * 0.1)
    trimmed = ordered[trim : len(ordered) - trim] if trim else ordered
    trimmed_mean = mean(trimmed) if trimmed else 0
    original_count = sum(_original_audio(item) for item in items)
    original_ratio = original_count / len(items) if items else 0
    created = [
        value
        for item in items
        if (
            value := _integer(item.get("createTime", item.get("create_time")))
        )
        is not None
    ]
    latest = max(created, default=0)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=policy.recency_days)
    posted_recently = bool(
        latest and datetime.fromtimestamp(latest, timezone.utc) >= recent_cutoff
    )
    signature = str(user.get("signature") or user.get("bio") or "")
    private = bool(user.get("privateAccount", user.get("private_account", False)))
    accessible = bool(user.get("uniqueId") or user.get("unique_id")) and not private
    evidence_complete = len(items) >= policy.min_videos and len(views) >= policy.min_videos
    criteria = {
        "minimum_followers": followers >= policy.min_followers,
        "public_accessible_account": accessible,
        "minimum_published_videos": published >= policy.min_videos,
        "minimum_analyzed_videos": evidence_complete,
        "minimum_trimmed_mean_views": trimmed_mean >= policy.min_trimmed_mean_views,
        "minimum_original_audio_ratio": original_ratio >= policy.min_original_audio_ratio,
        "posted_within_recency_window": posted_recently,
        "no_management_contact_in_bio": not _management_contact(signature),
    }
    handle = str(user.get("uniqueId") or user.get("unique_id") or "")
    return {
        "handle": handle,
        "profile_url": profile_url,
        "display_name": str(user.get("nickname") or user.get("display_name") or handle),
        "bio": signature,
        "public_email": _public_email(signature),
        "followers": followers,
        "published_videos": published,
        "analyzed_videos": len(items),
        "view_counts": views,
        "trimmed_view_count": len(trimmed),
        "trimmed_mean_views": round(trimmed_mean, 2),
        "original_audio_videos": original_count,
        "original_audio_ratio": round(original_ratio, 4),
        "latest_post_at": (
            datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest else None
        ),
        "criteria": criteria,
        "evidence_complete": evidence_complete,
        "eligible_public_profile": evidence_complete and all(criteria.values()),
    }


async def _video_from_page(context, url: str) -> dict | None:
    page = await open_public_page(context, url, settle_ms=500)
    try:
        items = _video_items(await _page_json_documents(page))
        return items[0] if items else None
    finally:
        await page.close()


async def _inspect_tiktok_profile(
    context,
    profile_url: str,
    policy: TikTokScreenRequest,
) -> dict:
    page = await open_public_page(context, profile_url, settle_ms=2_000)
    try:
        for _ in range(4):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(600)
        documents = await _page_json_documents(page)
        user_info = _user_info(documents)
        items = _video_items(documents)
        links = await page.locator('a[href*="/video/"]').evaluate_all(
            "nodes => [...new Set(nodes.map(node => node.href))]"
        )
        body = (await page.locator("body").inner_text(timeout=10_000)).casefold()
    finally:
        await page.close()
    if user_info is None:
        return {
            "profile_url": profile_url,
            "evidence_complete": False,
            "eligible_public_profile": False,
            "error": (
                "profile_not_public_or_accessible"
                if any(marker in body for marker in ("private account", "couldn't find"))
                else "profile_evidence_unavailable"
            ),
        }
    needed = max(0, policy.videos_per_creator - len(items))
    if needed:
        item_ids = {str(item.get("id") or item.get("aweme_id") or "") for item in items}
        video_urls = []
        for value in links:
            if not _profile_url(value) or value in video_urls:
                continue
            video_id = (urlparse(value).path.rstrip("/").split("/") or [""])[-1]
            if video_id not in item_ids:
                video_urls.append(value)
            if len(video_urls) >= needed:
                break
        for start in range(0, len(video_urls), 3):
            batch = await asyncio.gather(
                *(
                    _video_from_page(context, value)
                    for value in video_urls[start : start + 3]
                ),
                return_exceptions=True,
            )
            for value in batch:
                if isinstance(value, dict):
                    items.append(value)
    user, stats = user_info
    return _creator_metrics(
        profile_url,
        user,
        stats,
        items[: policy.videos_per_creator],
        policy,
    )


async def _form_field_contract(page: Page) -> tuple[dict, list[str]]:
    controls = page.locator("form input[name], form textarea[name], form select[name]")
    properties: dict[str, dict] = {}
    required: list[str] = []
    for index in range(await controls.count()):
        control = controls.nth(index)
        name = str(await control.get_attribute("name") or "").strip()
        if not name:
            continue
        control_type = str(await control.get_attribute("type") or "").casefold()
        schema: dict = {"type": "boolean" if control_type == "checkbox" else "string"}
        if control_type == "email":
            schema["format"] = "email"
        placeholder = str(await control.get_attribute("placeholder") or "").strip()
        if placeholder:
            schema["description"] = placeholder[:300]
        properties[name] = schema
        if await control.get_attribute("required") is not None:
            required.append(name)
    return properties, required


def _approval_status(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).casefold()
    rejected = (
        "not approved",
        "rejected",
        "do not contact",
        "already contacted",
        "cannot reach out",
        "can't reach out",
        "not able to reach out",
    )
    approved = (
        "approved",
        "can reach out",
        "able to reach out",
        "eligible to contact",
        "submission accepted",
    )
    if any(marker in normalized for marker in rejected):
        return "rejected"
    if any(marker in normalized for marker in approved):
        return "approved"
    return "unknown"


async def _submit_form_page(
    page: Page,
    fields: dict,
    submit_text: str,
) -> dict:
    form = page.locator("form").first
    if await form.count() == 0:
        raise HTTPException(422, "No form was found")
    action = str(await form.get_attribute("action") or "").strip()
    if action and _origin(urljoin(page.url, action)) != _origin(page.url):
        raise HTTPException(422, "Form submission must stay on the configured origin")
    filled = await fill_form(page, fields)
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
    evidence = await page_evidence(page)
    return {
        "submitted": True,
        "filled_fields": filled,
        "status": _approval_status(evidence["text"]),
        **evidence,
    }


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "configured": bool(WORKER_TOKEN)}


@app.post("/v1/discover", dependencies=[Depends(require_worker_token)])
async def discover(payload: DiscoverRequest) -> dict:
    target = str(payload.target_url)
    async with rendered_page(target) as page:
        form_count = await page.locator("form").count()
        field_properties, required_fields = (
            await _form_field_contract(page) if form_count else ({}, [])
        )
        record_schema = {
            "type": "object",
            "properties": field_properties,
            "additionalProperties": False,
        }
        if required_fields:
            record_schema["required"] = required_fields
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
                        "Fill one record using the discovered named fields and submit it after "
                        "explicit workflow approval. Returns page evidence and an approval status "
                        "parsed from the creator-specific response."
                    ),
                    "permission_scope": "write",
                    "requires_approval": True,
                    "input_schema": {
                        "type": "object",
                        "required": ["fields"],
                        "properties": {
                            "fields": record_schema,
                            "submit_text": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "output_schema": {
                        "type": "object",
                        "required": ["submitted", "status", "url", "text"],
                        "properties": {
                            "submitted": {"const": True},
                            "status": {
                                "type": "string",
                                "enum": ["approved", "rejected", "unknown"],
                            },
                            "url": {"type": "string"},
                            "text": {"type": "string"},
                        },
                    },
                }
            )
            capabilities.append(
                {
                    "name": "browser.form.batch.submit",
                    "description": (
                        "Submit every record in one finite approved batch. Opens a fresh form for "
                        "each record, preserves a creator-specific receipt, classifies each response "
                        "as approved, rejected, or unknown, and returns approved_records separately. "
                        "The destination form's explicit status is the authoritative policy-gate "
                        "decision for each submitted record, including any private DNC, active-"
                        "management, prior-approval, or protected-outreach checks implemented by "
                        "that form. Unknown results must never be treated as approval or written "
                        "downstream."
                    ),
                    "permission_scope": "write",
                    "requires_approval": True,
                    "input_schema": {
                        "type": "object",
                        "required": ["records"],
                        "properties": {
                            "records": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 25,
                                "items": record_schema,
                            },
                            "submit_text": {"type": "string"},
                            "identity_field": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "output_schema": {
                        "type": "object",
                        "required": ["results", "approved_records"],
                        "properties": {
                            "results": {"type": "array", "items": {"type": "object"}},
                            "approved_records": {
                                "type": "array",
                                "items": record_schema,
                            },
                        },
                    },
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
    if payload.capability == "browser.form.batch.submit":
        records = payload.input.get("records")
        if not isinstance(records, list) or not records or len(records) > 25:
            raise HTTPException(422, "Batch submission requires 1 to 25 records")
        if not all(isinstance(record, dict) and record for record in records):
            raise HTTPException(422, "Every batch record must contain named fields")
        submit_text = str(payload.input.get("submit_text") or "").strip()
        identity_field = str(payload.input.get("identity_field") or "").strip()
        results: list[dict] = []
        async with public_browser_context() as context:
            for index, record in enumerate(records):
                page = None
                try:
                    page = await open_public_page(context, target)
                    receipt = await _submit_form_page(page, record, submit_text)
                except Exception as exc:
                    # A timeout after clicking submit has an uncertain external
                    # effect. Preserve that creator as unknown and continue the
                    # finite batch; never retry it or promote it to approved.
                    receipt = {
                        "submitted": False,
                        "filled_fields": [],
                        "status": "unknown",
                        "url": target,
                        "text": "Submission result unavailable.",
                        "error_code": type(exc).__name__,
                    }
                finally:
                    if page is not None:
                        await page.close()
                identity = record.get(identity_field) if identity_field else None
                if identity is None:
                    identity = next((value for value in record.values() if value), index)
                results.append(
                    {
                        "index": index,
                        "identity": str(identity),
                        "record": record,
                        **receipt,
                    }
                )
        return {
            "results": results,
            "approved_records": [
                item["record"] for item in results if item["status"] == "approved"
            ],
        }
    async with rendered_page(target) as page:
        if payload.capability == "browser.page.read":
            return await page_evidence(page)
        if payload.capability != "browser.form.submit":
            raise HTTPException(422, "Unknown browser capability")
        fields = payload.input.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise HTTPException(422, "browser.form.submit requires named fields")
        submit_text = str(payload.input.get("submit_text") or "").strip()
        return await _submit_form_page(page, fields, submit_text)


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


@app.post("/v1/tiktok/screen", dependencies=[Depends(require_worker_token)])
async def screen_tiktok_creators(payload: TikTokScreenRequest) -> dict:
    search_query = f"site:tiktok.com/@ {payload.query}"
    search_url = "https://html.duckduckgo.com/html/?q=" + quote_plus(search_query)
    async with public_browser_context() as context:
        search_page = await open_public_page(context, search_url)
        try:
            hrefs = await search_page.locator(".result__a").evaluate_all(
                "nodes => nodes.map(node => node.href).filter(Boolean)"
            )
        finally:
            await search_page.close()
        resolved: list[str] = []
        for href in hrefs:
            parsed = urlparse(href)
            if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
                href = parse_qs(parsed.query).get("uddg", [href])[0]
            resolved.append(href)
        profile_urls = _profile_urls(resolved, payload.max_candidates)
        candidates: list[dict] = []
        for profile_url in profile_urls:
            try:
                candidates.append(
                    await _inspect_tiktok_profile(context, profile_url, payload)
                )
            except Exception as exc:
                candidates.append(
                    {
                        "profile_url": profile_url,
                        "evidence_complete": False,
                        "eligible_public_profile": False,
                        "error": type(exc).__name__,
                    }
                )
    return {
        "query": payload.query,
        "searched_profile_urls": profile_urls,
        "candidates": candidates,
        "qualified_candidates": [
            candidate
            for candidate in candidates
            if candidate.get("eligible_public_profile") is True
        ],
        "verification_scope": (
            "Public TikTok profile, recent video, view-count, original-audio, and bio "
            "evidence only. Grail DNC, management, prior submission, and protected-outreach "
            "checks still require the current internal sheets."
        ),
    }


@app.post("/v1/read", dependencies=[Depends(require_worker_token)])
async def read(payload: ReadRequest) -> dict:
    async with rendered_page(str(payload.url)) as page:
        return await page_evidence(page)
