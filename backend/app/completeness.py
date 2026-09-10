"""Deterministic evidence coverage; collection envelopes never imply completeness."""
from collections import deque


async def read_notion_tree(request, block_id, *, page_size=100, max_requests=20, max_blocks=1000):
    pending = deque([(block_id, None, None)])
    roots, children, seen = [], {}, set()
    requests = 0
    reasons = []
    while pending and requests < max_requests and len(seen) < max_blocks:
        parent_id, cursor, parent_block = pending.popleft()
        params = {"page_size": min(page_size, max_blocks - len(seen))}
        if cursor:
            params["start_cursor"] = cursor
        from urllib.parse import quote
        result = await request("GET", f"blocks/{quote(parent_id, safe='')}/children", params=params)
        requests += 1
        if not isinstance(result.get("results"), list):
            raise ValueError("Notion block listing has no results array")
        target = roots if parent_block is None else children.setdefault(parent_block, [])
        for block in result["results"]:
            identifier = block.get("id")
            if not identifier or identifier in seen:
                reasons.append("Missing or repeated block identifier")
                continue
            if len(seen) >= max_blocks:
                reasons.append("Block budget exhausted")
                break
            seen.add(identifier)
            target.append(block)
            if block.get("has_children"):
                pending.append((identifier, None, identifier))
        if result.get("has_more"):
            next_cursor = result.get("next_cursor")
            if not next_cursor or next_cursor == cursor:
                reasons.append("Provider did not advance its pagination cursor")
            else:
                pending.appendleft((parent_id, next_cursor, parent_block))
    if pending:
        reasons.append("Read budget exhausted before all pages and nested blocks were retrieved")
    return {"results": roots, "nested_children": children, "has_more": bool(pending or reasons),
        "next_cursor": None,
        "_aura_completeness": {"complete": not pending and not reasons, "reasons": reasons,
            "provider_requests": requests, "blocks_read": len(seen)}}


def incomplete_evidence(operation, result, required_evidence=()):
    if not isinstance(result, dict):
        return ["Provider evidence is not an object"]
    marker = result.get("_aura_completeness")
    if operation == "notion.blocks.children.list":
        if marker:
            return [] if marker.get("complete") is True else marker.get("reasons") or ["Body coverage is incomplete"]
        if result.get("has_more") or any(block.get("has_children") for block in result.get("results", [])):
            return ["Unread pages or nested Notion blocks remain"]
    if "complete_collection" in required_evidence:
        cursor = (result.get("next_cursor") or result.get("nextPageToken") or result.get("offset")
                  or result.get("continuation") or result.get("paging", {}).get("next")
                  or result.get("response_metadata", {}).get("next_cursor"))
        if cursor or result.get("has_more") or result.get("isLast") is False:
            return ["Collection pagination is incomplete"]
    return []
