"""Lossless model-input packing and explicit, provider-independent size limits.

Stored connector receipts are never modified. Repeated subtrees are represented by
JSON pointers into this input, rather than copied into the model window repeatedly.
"""
import hashlib
import json

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
    """Keep every character in ordered chunks; refuse work exceeding the run budget."""
    raw = encoded(value)
    chunks, current, size = [], [], 0
    for char in raw:
        length = len(char.encode())
        if size + length > CHUNK_BYTES:
            chunks.append("".join(current))
            current, size = [], 0
            if len(chunks) >= MAX_CHUNKS:
                raise ModelInputTooLarge("Source information exceeds the bounded evidence processing budget")
        current.append(char)
        size += length
    if current:
        chunks.append("".join(current))
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
