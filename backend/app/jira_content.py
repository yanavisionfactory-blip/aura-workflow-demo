"""Keep Jira document structure out of prose and out of customer review screens."""

import json
from copy import deepcopy


def _document_string(value):
    document, tail = None, value
    try:
        parsed, end = json.JSONDecoder().raw_decode(value.lstrip())
        if (isinstance(parsed, dict) and parsed.get("type") == "doc"
                and parsed.get("version") == 1 and isinstance(parsed.get("content"), list)):
            document, tail = parsed, value.lstrip()[end:].strip()
    except (ValueError, TypeError):
        pass
    return document, tail


def jira_description(value, *, _depth=0):
    # Providers and composers can wrap a serialized document in another ADF
    # paragraph. Unpack transport envelopes, preserving real nodes and prose.
    if isinstance(value, str):
        document, tail = _document_string(value)
        paragraphs = [{"type": "paragraph", "content": [{"type": "text", "text": line}]}
                      for line in tail.splitlines() if line.strip()]
        document = {**document, "content": [*document["content"], *paragraphs]} if document else {
            "type": "doc", "version": 1, "content": paragraphs}
    else:
        document = deepcopy(value)
    if not (isinstance(document, dict) and document.get("type") == "doc"
            and document.get("version") == 1 and isinstance(document.get("content"), list)):
        return document
    content = []
    for node in document["content"]:
        parts = node.get("content") if isinstance(node, dict) else None
        if (isinstance(node, dict) and node.get("type") == "paragraph"
                and isinstance(parts, list) and len(parts) == 1
                and isinstance(parts[0], dict)
                and parts[0].get("type") == "text" and isinstance(parts[0].get("text"), str)
                and _document_string(parts[0]["text"])[0] is not None):
            if _depth >= 8:
                raise ValueError("Prepare readable handoff prose instead of nested document envelopes")
            content.extend(jira_description(parts[0]["text"], _depth=_depth + 1)["content"])
        else:
            content.append(node)
    return {**document, "content": content}
