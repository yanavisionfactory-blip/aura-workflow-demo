"""Read-only Frame.io V4 access using an operator-owned Adobe OAuth app."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from uuid import UUID

import httpx

API_ORIGIN = "https://api.frame.io"
OPERATIONS = frozenset({
    "frameio.identity.get", "frameio.accounts.list",
    "frameio.file.get", "frameio.comments.list",
})


class FrameioReadError(ValueError):
    pass


def _headers(credentials: dict) -> dict:
    token = credentials.get("access_token")
    if not isinstance(token, str) or not token:
        raise FrameioReadError("Frame.io authorization is missing; reconnect the account.")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _uuid(value: object, label: str) -> str:
    # This pilot accepts Frame.io UUIDs, never URLs, stack IDs as file versions,
    # or unversioned Adobe aliases. A file UUID identifies one exact version.
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FrameioReadError(f"Select the exact Frame.io {label} UUID.") from exc


async def _get(client: httpx.AsyncClient, path: str, headers: dict, params: dict | None = None) -> dict:
    response = await client.get(API_ORIGIN + path, headers=headers, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise FrameioReadError("Frame.io returned an invalid response.")
    return payload


def _rows(payload: dict) -> list[dict]:
    rows = payload.get("data")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise FrameioReadError("Frame.io returned an invalid collection.")
    return rows


def _next_cursor(payload: dict, path: str) -> str | None:
    links = payload.get("links") or {}
    if not isinstance(links, dict):
        raise FrameioReadError("Frame.io returned invalid pagination.")
    next_link = links.get("next")
    if not next_link:
        return None
    if not isinstance(next_link, str):
        raise FrameioReadError("Frame.io returned invalid pagination.")
    target = urlsplit(urljoin(API_ORIGIN + path, next_link))
    if (target.scheme != "https" or target.netloc != "api.frame.io"
            or target.path != path or target.fragment):
        raise FrameioReadError("Frame.io pagination changed the requested resource.")
    after = parse_qs(target.query).get("after", [])
    if len(after) != 1 or not after[0] or len(after[0]) > 8192:
        raise FrameioReadError("Frame.io pagination did not provide a usable cursor.")
    return after[0]


async def verify(credentials: dict) -> dict:
    """Adobe identity alone is insufficient: at least one Frame.io account is required."""
    headers = _headers(credentials)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        me = await _get(client, "/v4/me", headers)
        identity = me.get("data", me)
        if not isinstance(identity, dict) or not (identity.get("user_id") or identity.get("id")):
            raise FrameioReadError("Adobe did not return a verified Frame.io user.")
        accounts = _rows(await _get(client, "/v4/accounts", headers, {"page_size": 100}))
    if not accounts or any(not row.get("id") for row in accounts):
        raise FrameioReadError("This Adobe user has no accessible Frame.io V4 account.")
    return {
        "ok": True, "status_code": 200,
        "identity": {key: identity[key] for key in ("user_id", "id", "name", "email") if key in identity},
        "account_ids": [row["id"] for row in accounts],
        "accounts_verified": len(accounts),
    }


def _file(payload: dict, file_id: str) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("id") != file_id or data.get("type") != "file":
        raise FrameioReadError("Frame.io did not return the exact selected file version.")
    return {key: data[key] for key in (
        "id", "name", "type", "parent_id", "project_id", "created_at", "updated_at",
        "adobe_id", "adobe_version_id", "view_url",
    ) if key in data}


def _comment(row: dict, file_id: str, seen: set[str]) -> dict:
    comment_id = row.get("id")
    if not isinstance(comment_id, str) or not comment_id or row.get("file_id") != file_id:
        raise FrameioReadError("Frame.io returned a comment for an unverified file version.")
    if comment_id in seen:
        raise FrameioReadError("Comments changed during pagination; repeat the exact-version read.")
    seen.add(comment_id)
    result = {key: row[key] for key in (
        "id", "file_id", "text", "timestamp", "duration", "page", "annotation",
        "text_review_annotation", "created_at", "updated_at", "text_edited_at",
        "completed_at", "completer_id", "owner_id", "anchor", "links", "mentions",
    ) if key in row}
    if isinstance(row.get("owner"), dict):
        result["owner"] = {key: row["owner"][key] for key in ("id", "name") if key in row["owner"]}
    attachments = row.get("attachments") or []
    if not isinstance(attachments, list) or any(not isinstance(item, dict) for item in attachments):
        raise FrameioReadError("Frame.io returned invalid comment attachments.")
    result["attachments"] = [{key: item[key] for key in ("id", "name", "media_type", "file_size")
                               if key in item} for item in attachments]
    replies = row.get("replies", [])
    if not isinstance(replies, list) or any(not isinstance(reply, dict) for reply in replies):
        raise FrameioReadError("Frame.io returned invalid comment replies.")
    result["replies"] = [_comment(reply, file_id, seen) for reply in replies]
    return result


async def execute(credentials: dict, operation: str, arguments: dict, timeout: float = 45) -> dict:
    if operation not in OPERATIONS:
        raise FrameioReadError("This Frame.io connector supports reviewed read operations only.")
    if operation == "frameio.identity.get":
        return await verify(credentials)
    headers = _headers(credentials)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if operation == "frameio.accounts.list":
            page_size = arguments.get("page_size", 100)
            if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 100:
                raise FrameioReadError("Frame.io page_size must be between 1 and 100.")
            params = {"page_size": page_size}
            if arguments.get("after"):
                params["after"] = str(arguments["after"])
            payload = await _get(client, "/v4/accounts", headers, params)
            rows = _rows(payload)
            cursor = _next_cursor(payload, "/v4/accounts")
            return {"data": [{key: row[key] for key in ("id", "display_name", "roles") if key in row}
                             for row in rows], "next_cursor": cursor, "complete": cursor is None,
                    "source_provider": "frameio", "vendor_api_called": True}
        account_id = _uuid(arguments.get("account_id"), "account")
        file_id = _uuid(arguments.get("file_id"), "file")
        file_path = f"/v4/accounts/{quote(account_id, safe='')}/files/{quote(file_id, safe='')}"
        file = _file(await _get(client, file_path, headers), file_id)
        evidence = {"source_provider": "frameio", "input_mode": "vendor_api",
                    "vendor_api_called": True, "account_id": account_id,
                    "asset_id": file_id, "version_id": file_id, "file": file,
                    "retrieved_at": datetime.now(UTC).isoformat(), "approval_status": "not_verified"}
        if operation == "frameio.file.get":
            return evidence
        path = file_path + "/comments"
        params = {"page_size": 100, "include": "replies", "include_total_count": "true"}
        comments, seen, cursors = [], set(), set()
        total_count = None
        for _ in range(10):
            payload = await _get(client, path, headers, params)
            count = payload.get("total_count")
            if count is not None:
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise FrameioReadError("Frame.io returned an invalid comment count.")
                if total_count is not None and count != total_count:
                    raise FrameioReadError("Comments changed during pagination; repeat the read.")
                total_count = count
            comments.extend(_comment(row, file_id, seen) for row in _rows(payload))
            cursor = _next_cursor(payload, path)
            if cursor is None:
                if total_count is not None and total_count != len(comments):
                    raise FrameioReadError("Frame.io comment coverage is incomplete; repeat the read.")
                return {**evidence, "comments": comments, "comment_count": len(comments),
                        "complete": True,
                        "limitations": ["A comment's completed state is not asset approval.",
                                        "Attachment content has not been read; review it separately.",
                                        "Version identity is the exact file UUID, not a guessed version label."]}
            if cursor in cursors:
                raise FrameioReadError("Frame.io repeated a pagination cursor; coverage is incomplete.")
            cursors.add(cursor)
            params["after"] = cursor
        raise FrameioReadError("This file exceeds the 1000-comment read limit; use a complete comments export.")
