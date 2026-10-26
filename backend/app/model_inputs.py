"""Lossless model-input packing and explicit, provider-independent size limits.

Stored connector receipts are never modified. Repeated subtrees are represented by
JSON pointers into this input, rather than copied into the model window repeatedly.
"""
import base64
import hashlib
import json
from urllib.parse import unquote_to_bytes

MAX_INPUT_BYTES = 96_000
CHUNK_BYTES = 24_000
MAX_CHUNKS = 12


class ModelInputTooLarge(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def is_input_limit(exc):
    return isinstance(exc, ModelInputTooLarge) or any(marker in str(exc).lower() for marker in (
        "context_length_exceeded", "exceeds the context window", "maximum context length",
    ))


def semantic_evidence(value):
    """Project MIME transport bytes for model review without altering receipts.

    Binary files are verified by byte hashes in provider read-back. Feeding their
    base64 encoding to a text model wastes its budget and cannot establish content.
    Keep names, MIME types, byte counts and hashes; decode textual MIME bodies.
    """
    if isinstance(value, list):
        return [semantic_evidence(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: semantic_evidence(item) for key, item in value.items()}
    upload = value.get("file_url")
    if isinstance(upload, str) and upload.startswith("data:") and "," in upload:
        metadata, encoded_upload = upload.split(",", 1)
        try:
            raw_upload = (base64.b64decode(encoded_upload, validate=True)
                          if ";base64" in metadata.lower() else unquote_to_bytes(encoded_upload))
        except ValueError:
            return result
        # Upload bytes remain in the durable run inputs. Provider/parser
        # receipts carry the readable findings; a model must not infer contents
        # from opaque base64. Never change the stored argument or source file.
        result["file_url"] = "[User-supplied upload; original retained in run inputs]"
        result["upload_evidence"] = {"sha256": hashlib.sha256(raw_upload).hexdigest(),
                                     "size": len(raw_upload),
                                     "mime_type": metadata[5:].split(";", 1)[0],
                                     "meaning": "Transport metadata; not proof of file contents"}
    body = value.get("body")
    mime = value.get("mimeType")
    if isinstance(mime, str) and isinstance(body, dict) and isinstance(body.get("data"), str):
        try:
            raw = base64.b64decode(body["data"] + "=" * (-len(body["data"]) % 4), altchars=b"-_", validate=True)
        except ValueError:
            return result
        if mime.lower().startswith("text/"):
            try:
                representation = {"decoded_text": raw.decode("utf-8")}
            except UnicodeDecodeError:
                return result
        else:
            representation = {"binary_evidence": {"sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw), "meaning": "Transport bytes; content is not inferred from this hash"}}
        result["body"] = {key: item for key, item in result["body"].items() if key != "data"}
        result["body"].update(representation)
    return result


def pack(value):
    """Intern exact repeated values only; never trim content, fields or list entries."""
    seen = {}

    def walk(item, path):
        raw = encoded(item)
        if len(raw) >= 256:
            digest = hashlib.sha256(raw.encode()).digest()
            if digest in seen:
                return {"__aura_evidence_ref__": seen[digest]}
            seen[digest] = path
        if isinstance(item, dict):
            return {k: walk(v, path + "/" + str(k).replace("~", "~0").replace("/", "~1")) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v, path + "/" + str(i)) for i, v in enumerate(item)]
        return item

    return walk(value, "#")


def bounded_input(payload):
    result = encoded(pack(payload))
    if len(result.encode()) > MAX_INPUT_BYTES:
        raise ModelInputTooLarge("Source information exceeds the model input budget")
    return result


def step_review_payload(step, provider_result):
    """Keep website source evidence inside the part the reader can partition.

    Content preparation is an internal, read-only composition operation. Its
    resolved sources are evidence, not consequential action arguments. Leaving
    them in the contract repeats the entire source corpus in every reader call
    and can prevent review even when each evidence batch fits. Preserve every
    source value in the evidence envelope and leave exact references in the
    contract. Stored arguments and provider receipts are never changed. Other
    operations, especially writes, retain their exact argument contract.
    """
    contract = semantic_evidence(step)
    arguments = contract.get("arguments", {})
    if step.get("operation") != "website.content.prepare" or not isinstance(arguments, dict):
        return {"step_contract": contract, "provider_result": provider_result}
    sources = arguments.get("sources")
    if not isinstance(sources, list):
        return {"step_contract": contract, "provider_result": provider_result}
    references = [{"evidence_path": f"#/source_arguments/{index}"}
                  for index in range(len(sources))]
    contract = {**contract, "arguments": {**arguments, "sources": references}}
    return {"step_contract": contract, "provider_result": {
        "recorded_provider_result": provider_result,
        "composition_arguments": {key: value for key, value in arguments.items() if key != "sources"},
        "source_arguments": sources,
        "source_kind": "Exact resolved source arguments; original receipts retained by executor",
    }}


def evidence_chunks(value):
    """Split at structural boundaries, with source paths and no incomplete JSON.

    Ordinary records remain intact. Oversized containers are split into children;
    only oversized strings are segmented, with offsets for exact reconstruction.
    """
    records = []
    def visit(item, path):
        record = {"path": path, "value": item}
        if len(encoded(record).encode()) <= CHUNK_BYTES - 2:
            records.append(record)
        elif isinstance(item, dict):
            for key, child in item.items():
                visit(child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, path + "/" + str(index))
        elif isinstance(item, str):
            offset = 0
            while offset < len(item):
                length = min(3000, len(item) - offset)
                segment = {"path": path, "value": item[offset:offset + length],
                           "offset": offset, "total_characters": len(item)}
                if len(encoded(segment).encode()) > CHUNK_BYTES - 2:
                    raise ModelInputTooLarge("Source path exceeds the evidence processing budget")
                records.append(segment)
                offset += length
        else:
            raise ModelInputTooLarge("Source value exceeds the evidence processing budget")
    visit(value, "#")
    chunks, current = [], []
    for record in records:
        if current and len(encoded([*current, record]).encode()) > CHUNK_BYTES:
            chunks.append(encoded(current))
            current = []
        current.append(record)
    if current:
        chunks.append(encoded(current))
    if len(chunks) > MAX_CHUNKS:
        raise ModelInputTooLarge("Source information exceeds the bounded evidence processing budget")
    return chunks


def canonical_execution_evidence(context):
    """Remove executor compatibility copies from model evidence, not from storage.

    step_context_value exposes whole receipts and collections under several paths
    for deterministic reference resolution. Those aliases are not new evidence.
    Preserve the provider fields, computed additions and a small alias map instead.
    """
    steps = {}
    for step_key, value in context.get("steps", {}).items():
        if not isinstance(value, dict) or "provider_result" not in value:
            steps[step_key] = value
            continue
        receipt = value["provider_result"]
        if not isinstance(receipt, dict):
            steps[step_key] = {"provider_result": receipt}
            continue
        document = receipt.get("ret")
        if isinstance(document, dict) and isinstance(document.get("textContent"), str):
            # Get Document returns both the text and a full structural body
            # containing the same text again. For content composition, keep
            # one complete text copy and its identity; receipts stay intact.
            steps[step_key] = {
                "documentId": document.get("documentId"),
                "title": document.get("title"),
                "textContent": value.get("textContent", document["textContent"]),
                "source_kind": "Google Docs full text; original receipt retained",
            }
            continue
        canonical = dict(receipt)
        aliases = {"provider_result": "."}
        known_values = {}
        for field, original in receipt.items():
            known_values.setdefault(encoded(original), field)
            if isinstance(original, list) and original:
                known_values.setdefault(encoded(original[0]), field + ".0")
                if isinstance(original[0], dict):
                    for subfield, subvalue in original[0].items():
                        known_values.setdefault(encoded(subvalue), field + ".0." + subfield)
        for key, item in value.items():
            if key == "provider_result":
                continue
            if key in receipt:
                # Keep computed normalization such as a Notion title.
                canonical[key] = item
                continue
            if item == receipt or (isinstance(item, dict) and item == value.get("output")):
                aliases[key] = "."
                continue
            target = known_values.get(encoded(item))
            if target is not None:
                aliases[key] = target
                continue
            canonical[key] = item
        if aliases:
            canonical["__aura_context_aliases__"] = aliases
        steps[step_key] = canonical
    return {"inputs": context.get("inputs", {}), "vars": context.get("vars", {}), "steps": steps}


def canonical_review_artifacts(artifacts):
    """Use one full Google Docs text copy in final model review.

    Pipedream's Get Document receipt contains `textContent` as well as a
    structural `body`/`tabs` tree with the same text. The durable receipt and
    its read-back check remain unchanged; only the model's review input is
    projected so eight source documents fit without dropping source text.
    """
    projected = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            projected.append(artifact)
            continue
        receipt = artifact.get("provider_result")
        document = receipt.get("ret") if isinstance(receipt, dict) else None
        if not (isinstance(document, dict) and isinstance(document.get("textContent"), str)):
            projected.append(artifact)
            continue
        projected.append({
            **artifact,
            "provider_result": {
                **receipt,
                "ret": {
                    "documentId": document.get("documentId"),
                    "title": document.get("title"),
                    "textContent": document["textContent"],
                    "source_kind": "Google Docs full text; original receipt retained",
                },
            },
        })
    return projected


def sheet_transfer_evidence(context, step):
    """Transfer a completed report using its full text and direct dependencies.

    The report already consumed its research. Sending every raw source through
    the transfer model again wastes the delivery budget and can alter the report.
    This projects model input only; stored receipts remain unchanged. Other
    actions and non-report references retain their complete context.
    """
    from .workflow_context import (
        REFERENCE,
        normalize_reference_path,
        referenced_paths,
        referenced_step_keys,
    )

    canonical = canonical_execution_evidence(context)
    value = (step.get("arguments") or {}).get("values")
    match = REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if step.get("operation") != "sheets.append" or not match:
        return canonical
    path = normalize_reference_path(match.group(1)).split(".")
    if len(path) < 3 or path[0] != "steps" or path[2:] not in (
        ["body"], ["provider_result", "body"], ["output", "body"], ["result", "body"],
    ):
        return canonical
    report = canonical["steps"].get(path[1])
    if not (isinstance(report, dict) and report.get("status") == "draft"
            and isinstance(report.get("body"), str) and report["body"].strip()
            and isinstance(report.get("sources"), list)):
        return canonical
    needed = set(step.get("depends_on") or []) | referenced_step_keys(step.get("arguments", {}))
    # A variable may name evidence outside the declared dependencies. Preserve
    # broader context until that reference has an explicit transfer contract.
    if any(ref.startswith("vars.") for ref in referenced_paths(step.get("arguments", {}))):
        return canonical
    projected = {key: item for key, item in canonical["steps"].items() if key in needed}
    projected[path[1]] = {
        key: report[key] for key in ("title", "summary", "body", "status", "synthetic", "generated_at")
        if key in report
    }
    projected[path[1]]["source_references"] = [
        {key: source[key] for key in ("id", "title") if key in source}
        for source in report["sources"] if isinstance(source, dict)
    ]
    projected[path[1]]["source_kind"] = "Complete prepared report for transfer; original research receipts retained by executor"
    return {**canonical, "steps": projected}
