"""One authoritative local text revision without rewriting a provider receipt."""

import hashlib
from copy import deepcopy


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reviewed_text_result(operation, receipt, revision):
    """Only the server's durable output-review record can replace generated text.

    This is local editorial evidence, never proof of a remote write or supervisor
    sign-off. Older saved reviews have actor/time but no digest; retain support
    for those records while checking the digest on newly recorded revisions.
    """
    if not isinstance(receipt, dict) or not isinstance(revision, dict):
        return None
    text = revision.get("text")
    if (not isinstance(text, str) or not text.strip()
            or not revision.get("edited_by") or not revision.get("edited_at")):
        return None
    if revision.get("sha256") not in (None, text_digest(text)):
        raise ValueError("The saved text revision does not match its recorded digest")
    result = deepcopy(receipt)
    if operation == "report.compose" and isinstance(receipt.get("body"), str):
        result["body"] = text
        # An edited report must not retain a stale generated summary or QA badge.
        result["summary"] = "Reviewed text saved in AURA; see the current report."
        result.pop("quality_check", None)
        if revision.get("quality_check"):
            result["quality_check"] = deepcopy(revision["quality_check"])
    elif (operation in {"anthropic.chat", "intelligence.claude_backup"}
          and isinstance(receipt.get("ret"), dict)
          and isinstance(receipt["ret"].get("content"), list)):
        result["ret"]["content"] = [{"type": "text", "text": text}]
    else:
        return None
    return result


def reviewed_artifact(artifact):
    """Project the accepted local revision for both final synthesis and checking."""
    if not isinstance(artifact, dict) or artifact.get("artifact_origin") == "reviewed_local_text":
        return artifact
    revision = artifact.get("user_revision")
    result = reviewed_text_result(artifact.get("operation"), artifact.get("provider_result"), revision)
    if result is None:
        return artifact
    return {
        **{key: value for key, value in artifact.items() if key != "user_revision"},
        "original_provider_result": deepcopy(artifact["provider_result"]),
        "provider_result": result,
        "artifact_origin": "reviewed_local_text",
        "revision_evidence": {
            "edited_by": revision["edited_by"], "edited_at": revision["edited_at"],
            "sha256": text_digest(revision["text"]),
            "meaning": "Current accepted local text. Original provider receipt retained separately. "
                       "Output review is not external publication or supervisor content approval.",
        },
    }
