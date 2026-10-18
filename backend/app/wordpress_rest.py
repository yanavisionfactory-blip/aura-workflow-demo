"""Bounded WordPress REST routes using an already owned Pipedream account.

Some hosts omit the HTML discovery link used by the vendor's wpapi client.
These routes use the standard API directly, preserving the existing account,
operation contract, approval and dispatch boundaries.
"""

import hashlib
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from .universal_connectors import ConnectorError, validate_public_endpoint

OPERATIONS = {"wordpress-org.search-posts", "wordpress-org.list-media-options", "wordpress-org.update-post"}


class WordPressRESTError(ValueError):
    pass


def _html_text(value):
    class Text(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)
    parser = Text()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


def post_evidence(post):
    if not isinstance(post, dict) or not isinstance(post.get("id"), int) or post["id"] < 1:
        raise WordPressRESTError("WordPress post identity is missing")
    title, content = post.get("title"), post.get("content")
    if not isinstance(title, dict) or not isinstance(content, dict):
        raise WordPressRESTError("WordPress title or complete body fields are missing")
    title = title.get("rendered", title.get("raw"))
    content = content.get("rendered", content.get("raw"))
    if not isinstance(title, str) or not isinstance(content, str) or not isinstance(post.get("status"), str):
        raise WordPressRESTError("WordPress post fields are malformed")
    text = _html_text(content)
    return {"id": post["id"], "title": _html_text(title), "status": post["status"],
            "word_count": sum(bool(re.search(r"\w", token)) for token in text.split()),
            "body_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "body_field_present": True}


def post_collection_evidence(result, arguments):
    """Derive auditable source facts without altering the saved WP receipt."""
    if not isinstance(result, dict) or result.get("aura_transport") != "authenticated_wordpress_rest" or not isinstance(result.get("ret"), list):
        raise WordPressRESTError("An authenticated WordPress post collection is required")
    posts = result["ret"]
    evidence = [post_evidence(post) for post in posts]
    if len({item["id"] for item in evidence}) != len(evidence):
        raise WordPressRESTError("WordPress returned duplicate post identities")
    statuses = arguments.get("statuses") or ["publish"]
    terms = re.findall(r"\w+", str(arguments.get("search") or "").casefold())
    for post, item in zip(posts, evidence, strict=True):
        if item["status"] not in statuses:
            raise WordPressRESTError("WordPress returned a post outside the requested status scope")
        fields = [post.get(key) for key in ("title", "content", "excerpt")]
        searchable = " ".join(_html_text(field.get("raw", field.get("rendered", "")))
                              for field in fields if isinstance(field, dict)).casefold()
        if any(term not in searchable for term in terms):
            raise WordPressRESTError("WordPress returned a post outside the requested text scope")
        item["query_terms_present_in_post_text"] = True
    return {"source": "derived_from_actual_wordpress_post_fields", "posts": evidence,
            "word_count_method": "HTML text; whitespace tokens containing letters or digits; title excluded",
            "collection_scope": "Returned page only; target coverage is checked against accepted write receipts"}


def _draft_arguments(arguments):
    # A blank optional opaque reference is absent, not an invented attachment
    # or author ID. Explicit nonempty references remain outside this draft-only
    # adapter and continue through the vendor route.
    return {key: value for key, value in arguments.items()
            if not (key in {"media", "author"} and value in (None, ""))}


def handles(provider, operation, arguments):
    if provider != "wordpress-org" or operation not in OPERATIONS:
        return False
    # Keep every other vendor action and publishing flow on its declared route.
    arguments = _draft_arguments(arguments)
    return operation != "wordpress-org.update-post" or (
        arguments.get("status") == "draft"
        and set(arguments) <= {"post", "status", "title", "content", "excerpt"}
    )


async def execute(broker, external_user_id, account_id, operation, arguments):
    if not handles("wordpress-org", operation, arguments):
        raise WordPressRESTError("This WordPress REST operation is not supported")
    if operation == "wordpress-org.update-post":
        arguments = _draft_arguments(arguments)
    credentials = await broker.wordpress_account_credentials(external_user_id, account_id)
    site = str(credentials.get("url") or "").strip().rstrip("/")
    if site and "://" not in site:
        site = "https://" + site
    parsed = urlsplit(site)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.port not in (None, 443)
        or any(part in {".", ".."} for part in parsed.path.split("/"))):
        raise WordPressRESTError("The WordPress site must use a valid HTTPS address")
    username, password = credentials.get("username"), credentials.get("application_password")
    if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
        raise WordPressRESTError("The WordPress application-password connection is incomplete")
    validate_public_endpoint(site)

    async def request(client, method, path, *, query=None, body=None):
        try:
            response = await client.request(method, site + "/wp-json/wp/v2" + path,
                                            params=query, json=body)
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError, ConnectorError):
            raise WordPressRESTError("The authenticated WordPress REST request could not be verified") from None
        if not isinstance(result, (dict, list)):
            raise WordPressRESTError("WordPress returned an invalid REST response")
        return result

    async with httpx.AsyncClient(timeout=20, follow_redirects=False,
                                 auth=httpx.BasicAuth(username, password),
                                 headers={"Accept": "application/json"}) as client:
        if operation == "wordpress-org.search-posts":
            query = {"context": "edit", "per_page": 100, "page": 1}
            if arguments.get("search"):
                query["search"] = arguments["search"]
            statuses = arguments.get("statuses") or ["publish"]
            if not isinstance(statuses, list) or any(
                status not in {"publish", "future", "draft", "pending", "private"} for status in statuses
            ):
                raise WordPressRESTError("The WordPress search status is invalid")
            query["status"] = ",".join(statuses)
            for source, target in (("author", "author"), ("authorExclude", "author_exclude")):
                if arguments.get(source):
                    query[target] = arguments[source]
            result = await request(client, "GET", "/posts", query=query)
            if not isinstance(result, list):
                raise WordPressRESTError("WordPress did not return a post collection")
        elif operation == "wordpress-org.list-media-options":
            page = arguments.get("page", 0)
            if not isinstance(page, int) or page < 0:
                raise WordPressRESTError("The WordPress media page is invalid")
            media = await request(client, "GET", "/media", query={"context": "edit", "per_page": 100, "page": page + 1})
            if not isinstance(media, list):
                raise WordPressRESTError("WordPress did not return a media collection")
            result = [{"label": unescape(str((item.get("title") or {}).get("rendered") or item["id"])),
                       "value": str(item["id"])} for item in media if isinstance(item, dict) and isinstance(item.get("id"), int)]
        else:
            post = str(arguments.get("post") or "")
            if not re.fullmatch(r"[1-9]\d*", post):
                raise WordPressRESTError("The WordPress post identifier is invalid")
            path = "/posts/" + post
            existing = await request(client, "GET", path, query={"context": "edit"})
            if not isinstance(existing, dict) or existing.get("id") != int(post) or existing.get("status") not in {"draft", "pending", "private"}:
                raise WordPressRESTError("Draft updates require an existing unpublished WordPress post")
            result = await request(client, "POST", path, body={key: value for key, value in arguments.items() if key != "post"})
            if not isinstance(result, dict) or result.get("id") != int(post) or result.get("status") != "draft":
                raise WordPressRESTError("The saved WordPress draft could not be verified; inspect it before retrying")
    # This is an explicit AURA transport envelope around the actual WP response,
    # not a forged vendor execution receipt.
    return {"ret": result, "aura_transport": "authenticated_wordpress_rest",
            "pagination": {"per_page": 100, "page": arguments.get("page", 0) + 1}
            if isinstance(result, list) else None}
