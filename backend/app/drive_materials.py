"""Bounded semantic discovery using only the selected owner's existing Drive grant."""

import asyncio
import base64
import hashlib
import io
import json
import re
import unicodedata
from urllib.parse import quote, urlencode

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .material_relevance import assess_materials, retrieval_hints, select_candidates

OPERATION = "google-drive.search-files"
FOLDER = "application/vnd.google-apps.folder"
EXPORTS = {"application/vnd.google-apps.document", "application/vnd.google-apps.presentation"}
READABLE = EXPORTS | {"application/pdf", "text/plain", "text/markdown", "text/csv"}
MAX_FILES = 200
MAX_READS = 12
MAX_BYTES = 8_000_000
MAX_TEXT_BYTES = 60_000
MAX_TOTAL_TEXT_BYTES = 120_000
ID = re.compile(r"[A-Za-z0-9_-]{1,200}")
FIELDS = ("nextPageToken,incompleteSearch,files(id,name,mimeType,parents,webViewLink,"
          "description,size,capabilities(canDownload))")


def normalized_name(value):
    return unicodedata.normalize("NFC", value).replace("\ufe0f", "").strip().casefold()


def query_literal(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


async def execute(broker, external_user_id, account_id, arguments):
    from .pipedream_connect import PipedreamConnectError

    goal = arguments.get("semantic_goal")
    user_request = arguments.get("user_request")
    path = arguments.get("folder_path", [])
    if (not isinstance(goal, str) or not 10 <= len(goal) <= 10000
            or set(arguments) - {"semantic_goal", "folder_path", "user_request"}
            or ("user_request" in arguments and (not isinstance(user_request, str)
                or not 1 <= len(user_request) <= 20000))
            or not isinstance(path, list) or len(path) > 8
            or any(not isinstance(part, str) or not part.strip() or len(part) > 400 for part in path)):
        raise ValueError("Semantic Drive search needs an objective and optional folder path segments")
    if user_request is not None:
        goal = {"user_request": user_request, "discovery_task": goal}
    verification = await broker.verify_account(external_user_id, "google_drive", account_id)
    if verification.get("ok") is not True:
        raise PipedreamConnectError("Google Drive authorization is required", retryable=False, status_code=403)
    pages, limitations, unsupported = [], [], []

    async def request(suffix, params, *, raw=False):
        target = "https://www.googleapis.com/drive/v3/files" + suffix + "?" + urlencode(params)
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        kwargs = {"params": {"external_user_id": external_user_id, "account_id": account_id}}
        if raw:
            kwargs["response_bytes_limit"] = MAX_BYTES
        result = await broker._request("GET",
            f"/v1/connect/{quote(broker.settings.pipedream_project_id, safe='')}/proxy/{encoded}", **kwargs)
        if not raw and (not isinstance(result, dict) or "error" in result):
            raise PipedreamConnectError("Google Drive returned an invalid discovery response", retryable=False)
        return result

    async def listing(query, *, fulltext=False):
        rows, tokens = [], set()
        token = None
        for _ in range(2):
            params = {"q": query, "pageSize": 100, "fields": FIELDS,
                      "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            # Drive rejects orderBy with fullText terms; those results already
            # use provider relevance order. Retain recency for broad inventory.
            if not fulltext:
                params["orderBy"] = "modifiedTime desc"
            if token:
                params["pageToken"] = token
            result = await request("", params)
            files = result.get("files", [])
            if not isinstance(files, list) or any(not isinstance(f, dict)
                    or not ID.fullmatch(str(f.get("id", "")))
                    or not isinstance(f.get("name"), str)
                    or not isinstance(f.get("mimeType"), str) for f in files):
                raise ValueError("Drive candidate metadata is malformed")
            pages.append({"query": query, "response": result})
            rows.extend(files)
            if result.get("incompleteSearch") is True:
                limitations.append("Google Drive reported an incomplete search.")
            token = result.get("nextPageToken")
            if not token:
                return rows
            if not isinstance(token, str) or token in tokens:
                raise ValueError("Drive pagination did not progress")
            tokens.add(token)
        limitations.append("Candidate listing reached its 200-file bound; account coverage is partial.")
        return rows

    folder_id = None
    scope_folders = []
    for segment in path:
        query = f"trashed = false and mimeType = '{FOLDER}'"
        spellings = {segment, segment.strip(), unicodedata.normalize("NFC", segment).strip(),
                     unicodedata.normalize("NFC", segment).strip().replace("\ufe0f", "")}
        query += " and (" + " or ".join("name = " + query_literal(name) for name in sorted(spellings)) + ")"
        if folder_id:
            query += " and " + query_literal(folder_id) + " in parents"
        folders = await listing(query)
        matches = [f for f in folders if normalized_name(f["name"]) == normalized_name(segment)]
        if len(matches) != 1:
            return {"ret": {"files": [], "sources": [], "status": "scope_unresolved",
                "scope_candidates": [{"id": f["id"], "name": f["name"],
                    "parents": f.get("parents", []), "url": f.get("webViewLink")} for f in matches],
                "unresolved_segment": segment, "isComplete": False},
                "sources": [], "status": "scope_unresolved", "provider_pages": pages,
                "aura_transport": "semantic_drive_read_v1",
                "limitations": [*limitations, ("The supplied location did not resolve uniquely. "
                    "Choose a displayed folder or describe the location; no folder ID is required.")],
                "summary": "Drive location needs clarification; no content or presentation was fabricated."}
        folder_id = matches[0]["id"]
        scope_folders.append(matches[0])

    inventory = []
    if folder_id:
        pending, visited = [folder_id], set()
        while pending and len(visited) < 12 and len(inventory) < MAX_FILES:
            current = pending.pop(0)
            if current in visited:
                continue
            visited.add(current)
            rows = await listing("trashed = false and " + query_literal(current) + " in parents")
            for file in rows:
                if file["mimeType"] == FOLDER:
                    pending.append(file["id"])
                elif file["id"] not in {f["id"] for f in inventory}:
                    inventory.append(file)
        if pending or len(inventory) > MAX_FILES:
            limitations.append("Folder traversal reached its bound; some materials remain unreviewed.")
    else:
        # The provider has token search, not a semantic index. Use its search
        # only to improve recall, unioned with a name-independent inventory.
        # Every final match still requires assessment of actual contents.
        hints = await retrieval_hints(goal)
        if hints:
            clauses = ["fullText contains " + query_literal(
                '"' + hint.replace('"', '') + '"' if " " in hint else hint) for hint in hints]
            inventory = await listing(f"trashed = false and mimeType != '{FOLDER}' and ("
                                      + " or ".join(clauses) + ")", fulltext=True)
        broad = await listing(f"trashed = false and mimeType != '{FOLDER}'")
        found = {file["id"] for file in inventory}
        inventory.extend(file for file in broad if file["id"] not in found)
        if len(inventory) > MAX_FILES:
            limitations.append("Merged candidate inventory exceeds the review bound; coverage is partial.")
    candidates = []
    for index, file in enumerate(inventory):
        capabilities = file.get("capabilities") or {}
        reason = ("The selected account cannot download this file; its content was not read."
                  if isinstance(capabilities, dict) and capabilities.get("canDownload") is False
                  else "This content format is not read by semantic discovery."
                  if file["mimeType"] not in READABLE else None)
        if reason:
            unsupported.append({"id": file["id"], "name": file["name"],
                                "mimeType": file["mimeType"], "reason": reason})
        elif index < MAX_FILES:
            candidates.append(file)
    selected = await select_candidates(goal, candidates)
    if len(selected) < len(candidates):
        limitations.append("At most 12 prioritized candidate documents were read; remaining contents are unreviewed.")

    semaphore = asyncio.Semaphore(4)

    async def read(file):
        async with semaphore:
            size = file.get("size")
            if size is not None and (not str(size).isdigit() or int(size) > MAX_BYTES):
                return file, None, "File exceeds the 8 MB reading limit."
            suffix = "/" + quote(file["id"], safe="")
            params = {"alt": "media", "supportsAllDrives": "true"}
            if file["mimeType"] in EXPORTS:
                suffix += "/export"
                params = {"mimeType": "text/plain"}
            try:
                raw = await request(suffix, params, raw=True)
                if not isinstance(raw, bytes):
                    raise TypeError("Drive content response is not bytes")
                if file["mimeType"] == "application/pdf":
                    def pdf_text():
                        reader = PdfReader(io.BytesIO(raw))
                        if reader.is_encrypted or len(reader.pages) > 100:
                            raise ValueError("Encrypted or oversized PDF")
                        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
                    text = await asyncio.to_thread(pdf_text)
                else:
                    text = raw.decode("utf-8-sig")
                if not text.strip():
                    return file, None, "No extractable text; scanned pages or audio were not analyzed."
                if len(text.encode()) > MAX_TEXT_BYTES:
                    return file, None, "Full text exceeds the semantic reading limit; it was not truncated."
                return file, {"text": text, "sha256": hashlib.sha256(raw).hexdigest()}, None
            except PipedreamConnectError as exc:
                if exc.status_code in {401, 403, 429} or exc.retryable:
                    raise
                return file, None, "The provider could not read this file."
            except (ValueError, UnicodeError, PyPdfError):
                return file, None, "This file could not be parsed as readable text."

    reads = await asyncio.gather(*(read(file) for file in selected[:MAX_READS]))
    # Keep the exact texts within the downstream evidence-reader budget too.
    # Oversized groups remain explicit unread coverage, never truncated facts.
    bounded_reads, total_text = [], 0
    for file, content, error in reads:
        if content is not None:
            size = len(content["text"].encode())
            if total_text + size > MAX_TOTAL_TEXT_BYTES:
                content, error = None, "Combined source text exceeds the 120 KB review limit; this file remains unreviewed."
            else:
                total_text += size
        bounded_reads.append((file, content, error))
    reads = bounded_reads
    documents, sources, assessments = [], [], []
    reviewed = await assess_materials(goal, [
        {"id": file["id"], "title": file["name"], "text": content["text"]}
        for file, content, error in reads if not error])
    for file, content, error in reads:
        if error:
            unsupported.append({"id": file["id"], "name": file["name"], "reason": error})
            continue
        assessment = reviewed[file["id"]]
        assessments.append({"id": file["id"], **assessment.model_dump()})
        documents.append({**file, **content})
        if assessment.relevant:
            url = file.get("webViewLink") or "https://drive.google.com/file/d/" + file["id"] + "/view"
            evidence = (content["text"] if len(content["text"].encode()) <= 4000
                        else "Selected verbatim passages from the fully reviewed document:\n\n"
                        + "\n\n".join(assessment.excerpts))
            sources.append({"id": f"material_{len(sources) + 1}", "title": file["name"][:200],
                            "content": (f"Source: {url}\nDrive file ID: {file['id']}\n"
                                        f"Read SHA-256: {content['sha256']}\n\n{evidence}")})
    if unsupported:
        limitations.append(f"{len(unsupported)} files were not content-reviewed; see unsupported_files.")
    status = "matched" if sources else "no_verified_match"
    if sources:
        # Downstream composers normally bind only `sources`, not the full
        # discovery receipt. Keep provider identities and scope in that exact
        # evidence path; citation aliases are not Google Drive file IDs.
        relevant_ids = {item["id"] for item in assessments if item["relevant"]}
        provenance = {
            "requested_folder_path": path,
            "scope_folders": [{"id": folder["id"], "name": folder["name"][:400],
                               "parents": folder.get("parents", [])} for folder in scope_folders],
            "read_files": [{"drive_file_id": doc["id"], "name": doc["name"][:200],
                            "sha256": doc["sha256"], "relevant": doc["id"] in relevant_ids}
                           for doc in documents],
            "reviewed_file_count": len(documents),
            "relevant_file_count": len(sources),
            "unsupported_file_count": len(unsupported),
            "is_complete": not limitations,
        }
        sources.append({"id": "discovery_coverage", "title": "Source discovery coverage",
            "content": ("Discovery metadata, not a Drive file or project facts. "
                "Do not count this entry as a file read. Source IDs such as material_1 are "
                "citation labels; drive_file_id identifies the provider file.\n"
                + json.dumps(provenance, ensure_ascii=False) + "\nCoverage limitations:\n"
                + "\n".join(limitations or [
                    "All returned supported candidate contents were assessed."]))})
    return {"ret": {"files": inventory, "isComplete": not limitations, "status": status},
            "status": status, "sources": sources, "documents": documents,
            "assessments": assessments, "scope_folders": scope_folders,
            "unsupported_files": unsupported, "limitations": limitations, "provider_pages": pages,
            "summary": f"Read {len(documents)} documents and found {max(0, len(sources) - 1)} relevant materials by meaning.",
            "aura_transport": "semantic_drive_read_v1", "external_writes": False}
