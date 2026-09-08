"""Bounded Canva PDF transfer; URLs are never fetched with account credentials."""
import asyncio
import base64
import hashlib
from urllib.parse import urlsplit, urljoin
import httpx

MAX_FILE_BYTES = 8 * 1024 * 1024
ATTACHMENTS_SCHEMA = {"type": "array", "maxItems": 3, "items": {
    "type": "object", "additionalProperties": False, "required": ["filename", "url"],
    "properties": {"filename": {"type": "string", "pattern": r"^[^/\\\r\n]{1,100}\.pdf$"},
        "url": {"type": "string", "format": "uri"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "size": {"type": "integer", "minimum": 1, "maximum": MAX_FILE_BYTES}}}}


def allowed_download_url(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
            or not (host.endswith('.canva.com') or host.endswith('.canvausercontent.com'))):
        raise ValueError('PDF download must use a Canva export URL')
    return url


async def download_pdf(url):
    async def fetch():
        current = url
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            for _ in range(4):
                allowed_download_url(current)
                async with client.stream('GET', current) as response:
                    if response.is_redirect:
                        current = urljoin(current, response.headers['location'])
                        continue
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_FILE_BYTES:
                            raise ValueError('PDF exceeds the attachment size budget')
                    if not data.startswith(b'%PDF-'):
                        raise ValueError('Canva download is not a PDF')
                    return bytes(data)
            raise ValueError('PDF download exceeded the redirect budget')
    return await asyncio.wait_for(fetch(), timeout=20)


def fingerprint(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


async def prepare_attachments(arguments, approved_urls):
    from jsonschema import validate
    attachments = arguments.get('attachments', [])
    validate(attachments, ATTACHMENTS_SCHEMA)
    prepared = []
    total = 0
    for item in attachments:
        if item['url'] not in approved_urls:
            raise ValueError('Attachment URL must come from a completed Canva export in this run')
        data = await download_pdf(item['url'])
        total += len(data)
        if total > MAX_FILE_BYTES:
            raise ValueError('Combined attachments exceed the size budget')
        prepared.append({**item, **fingerprint(data)})
    return {**arguments, 'attachments': prepared} if attachments else arguments


def gmail_attachment_fingerprints(payload):
    result = []
    def visit(part):
        if part.get('filename'):
            data = part.get('body', {}).get('data')
            if data is None:
                raise ValueError('Attachment read-back bytes are missing')
            raw = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
            result.append({'filename': part['filename'], **fingerprint(raw)})
        for child in part.get('parts', []):
            visit(child)
    visit(payload)
    return sorted(result, key=lambda item: (item['filename'], item['sha256']))
