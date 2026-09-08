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
