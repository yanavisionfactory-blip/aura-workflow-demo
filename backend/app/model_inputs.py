"""Lossless model-input packing and explicit, provider-independent size limits.

Stored connector receipts are never modified. Repeated subtrees are represented by
JSON pointers into this input, rather than copied into the model window repeatedly.
"""
import hashlib
import json
import base64

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
