"""Bounded WordPress REST routes using an already owned Pipedream account.

Some hosts omit the HTML discovery link used by the vendor's wpapi client.
These routes use the standard API directly, preserving the existing account,
operation contract, approval and dispatch boundaries.
"""

import re
from html import unescape
from urllib.parse import urlsplit

import httpx

from .universal_connectors import ConnectorError, validate_public_endpoint

OPERATIONS = {"wordpress-org.search-posts", "wordpress-org.list-media-options", "wordpress-org.update-post"}


class WordPressRESTError(ValueError):
    pass


def handles(provider, operation, arguments):
    if provider != "wordpress-org" or operation not in OPERATIONS:
        return False
    # Keep every other vendor action and publishing flow on its declared route.
    return operation != "wordpress-org.update-post" or (
        arguments.get("status") == "draft"
        and set(arguments) <= {"post", "status", "title", "content", "excerpt"}
    )


async def execute(broker, external_user_id, account_id, operation, arguments):
    if not handles("wordpress-org", operation, arguments):
        raise WordPressRESTError("This WordPress REST operation is not supported")
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
