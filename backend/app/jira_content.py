"""Keep Jira document structure out of prose and out of customer review screens."""

import json
from copy import deepcopy


def jira_description(value):
    if not isinstance(value, str):
        return deepcopy(value)
    # A provider read may have serialized its ADF document. Decode only a real
    # Jira document; ordinary JSON examples remain ordinary prose. Preserve an
    # append after that document as new paragraphs instead of double-encoding it.
    document, tail = None, value
    try:
        parsed, end = json.JSONDecoder().raw_decode(value.lstrip())
        if (isinstance(parsed, dict) and parsed.get("type") == "doc"
                and parsed.get("version") == 1 and isinstance(parsed.get("content"), list)):
            document, tail = parsed, value.lstrip()[end:].strip()
    except (ValueError, TypeError):
        pass
    paragraphs = [{"type": "paragraph", "content": [{"type": "text", "text": line}]}
                  for line in tail.splitlines() if line.strip()]
    if document is not None:
        return {**document, "content": [*document["content"], *paragraphs]}
    return {"type": "doc", "version": 1, "content": paragraphs}
