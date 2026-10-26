"""Deterministic checks between content composition and provider approval."""

import re
from html.parser import HTMLParser

from .approval_readiness import unfinished_action_content
from .workflow_context import referenced_paths


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "h1", "h2", "h3", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def article_word_count(html):
    parser = ArticleText()
    parser.feed(html)
    return len("".join(parser.parts).split())


def content_paths(arguments, path=()):
    for key, value in arguments.items():
        current = (*path, key)
        if isinstance(value, dict):
            yield from content_paths(value, current)
        elif key in {"body", "content", "text", "message", "description", "title", "focus_keyword"}:
            yield current, value


def validate_composed_content(step, arguments):
    planned = step.get("arguments") or {}
    for path, value in content_paths(planned):
        if not isinstance(value, str) or not unfinished_action_content("", {"description": value}):
            continue
        result = arguments
        for key in path:
            result = result.get(key) if isinstance(result, dict) else None
        if (path[-1] == "description" and isinstance(result, dict)
                and result.get("type") == "doc" and result.get("content")):
            continue
        if not isinstance(result, str) or not result.strip():
            raise ValueError("Composed action omitted requested content: " + ".".join(path))
    if step.get("operation") != "wordpress-org.update-post":
        return
    instruction = str(planned.get("content") or "")
    composing = unfinished_action_content("", {"content": instruction})
    if not composing:
        return
    if not str(arguments.get("title") or "").strip():
        raise ValueError("The complete article needs a finished title before review")
    body = str(arguments.get("content") or "")
    match = re.search(r"(\d[\d,]*)\s*[–—-]\s*(\d[\d,]*)\s+words", instruction)
    if match:
        minimum, maximum = (int(value.replace(",", "")) for value in match.groups())
        count = article_word_count(body)
        if not minimum <= count <= maximum:
            raise ValueError(f"The complete article has {count} words; write {minimum}–{maximum} words")
    if "html" in instruction.casefold() and not re.search(r"<(?:p|h[1-6])\b", body, re.IGNORECASE):
        raise ValueError("The complete article must use HTML paragraphs and headings")


def preserve_action_targets(planned, resolved):
    """Composition changes prose, never a known destination or publish status."""
    result = dict(resolved)
    for field in ("post", "post_id", "media_id", "issue_id_or_key", "status", "spreadsheet_id", "range"):
        value = planned.get(field)
        if value not in (None, "") and not referenced_paths(value):
            result[field] = value
    return result
