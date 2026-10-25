"""Immutable release identity written into the uploaded source archive by CI."""
import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache
def release_sha() -> str | None:
    try:
        value = json.loads(Path(__file__).with_name("release.json").read_text())["sha"]
        return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
