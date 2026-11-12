"""Keep uploaded video references distinct from provider asset identifiers."""

import re

from .workflow_context import WorkflowContextError, referenced_step_keys, resolve_value

UPLOAD_SOURCE_MESSAGE = (
    "Attach an MP4 or MOV using the video drop area before creating the review plan. "
    "Bind file_url to the attachment's file_url and filename to its name (not filename). "
    "The video review has not started."
)


def validate_uploaded_video_arguments(arguments: dict, context: dict) -> None:
    """Check input bindings without decoding media or calling a provider.

    Only actual earlier-step references may wait until execution. Missing upload
    bytes or filename paths must never pass readiness as a verified video source.
    """
    resolved = {}
    for key in ("file_url", "filename"):
        value = arguments.get(key)
        if referenced_step_keys(value):
            continue
        try:
            value = resolve_value(value, context)
        except WorkflowContextError:
            raise ValueError(UPLOAD_SOURCE_MESSAGE) from None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(UPLOAD_SOURCE_MESSAGE)
        resolved[key] = value
    source = resolved.get("file_url")
    if source is not None:
        if not re.fullmatch(
            r"data:(?:video/(?:mp4|quicktime)|application/octet-stream);base64,[A-Za-z0-9+/]+={0,2}", source,
        ):
            raise ValueError(UPLOAD_SOURCE_MESSAGE)
        if (source.startswith("data:application/octet-stream;") and "filename" in resolved
                and not resolved["filename"].lower().endswith((".mp4", ".mov"))):
            raise ValueError(UPLOAD_SOURCE_MESSAGE)


def video_upload(document: dict) -> bool:
    value = document.get("file_url")
    if not isinstance(value, str) or not value.startswith("data:"):
        return False
    media_type = value[5:].split(";", 1)[0].split(",", 1)[0].lower()
    return media_type in {"video/mp4", "video/quicktime"} or (
        media_type == "application/octet-stream"
        and str(document.get("name", "")).lower().endswith((".mp4", ".mov"))
    )


def video_upload_hint(input_key: str, index: int) -> str:
    reference = f"inputs.{input_key}.{index}"
    return (
        "Uploaded video source. For a requested review of this upload, use intelligence.video.review on aura with "
        f"file_url={{{{{reference}.file_url}}}} and filename={{{{{reference}.name}}}}. "
        "This upload is already the review source; it is not a Frame.io file ID. "
        "Preserve the user's review instructions."
    )


def uploaded_video_review_plan(prompt: str, inputs: dict | None, inventory: list[dict]):
    """Compile an unambiguous upload review without a model choosing an asset.

    Mixed-source work, provider-specific requests and later plan revisions stay
    with the general planner. Its normal grant/approval checks still apply here.
    """
    from .schemas import PlanStep, WorkflowPlan

    if not inputs or not prompt or len(prompt) > 6000:
        return None
    if "The user reviewed the proposed workflow and requested this change:" in prompt:
        return None
    text = prompt.casefold()
    if not re.search(r"\b(?:video|mp4|mov|clip|footage)\b", text) or not re.search(
        r"\b(?:review|inspect|check|analy[sz]e|feedback)\b", text,
    ):
        return None
    if re.search(r"https?://|\b(?:send|email|post|publish|upload|export|save|create|edit|trim|translate|transcribe|compare|schedule)\b", text):
        return None
    if re.search(r"(?:^|[.!?,;]\s*|\b(?:and|then)\s+)(?:remove|replace|fix|correct|add|render|resize|crop)\b", text):
        return None
    # A named provider is a source/destination choice, not permission to replace it.
    for item in inventory:
        if item.get("slug") == "aura":
            continue
        for alias in (item.get("name"), item.get("slug"), item.get("canonical_provider")):
            if alias and re.search(r"(?<!\w)" + re.escape(str(alias).casefold()) + r"(?!\w)", text):
                return None
    if not any(item.get("slug") == "aura" and "intelligence.video.review" in
               item.get("allowed_operations", []) for item in inventory):
        return None
    key = "attached_documents" if "attached_documents" in inputs else "documents"
    documents = inputs.get(key)
    if not isinstance(documents, list) or len(documents) != 1:
        return None
    document = documents[0]
    if not isinstance(document, dict) or not video_upload(document):
        return None
    source = f"inputs.{key}.0"
    return WorkflowPlan(
        name="Review uploaded video", interpretation=prompt,
        steps=[PlanStep(
            key="review_video", agent="AURA Intelligence", tool_slug="aura",
            operation="intelligence.video.review",
            arguments={"file_url": "{{" + source + ".file_url}}",
                       "filename": "{{" + source + ".name}}", "instructions": prompt},
            reason="Inspect the uploaded video's visuals and audio and prepare timestamped production feedback.",
            expected_output="Chronological issues, timestamps, evidence and recommended corrections, with review limitations disclosed.",
        )],
        planning_artifacts={"video_source": {"kind": "user_upload", "input_path": source}},
    )


def validate_video_source_bindings(plan, inputs: dict | None) -> None:
    """Reject a wrong source while the planner still has its repair pass.

    Do not substitute assets, alter an approved plan or infer missing provider
    IDs. Valid Frame.io targets can coexist with unrelated attached videos.
    """
    inputs = inputs or {}
    key = "attached_documents" if "attached_documents" in inputs else "documents"
    documents = inputs.get(key)
    if not isinstance(documents, list):
        documents = []
    uploads = [(index, doc) for index, doc in enumerate(documents)
               if isinstance(doc, dict) and video_upload(doc)]
    for step in plan.steps:
        fallback_operation = getattr(step, "fallback_operation", None)
        if not {step.operation, fallback_operation} & {"intelligence.video.review", "frameio.video.review", "frameio.assistant.review"}:
            continue
        variants = [
            (step.operation, step.arguments),
            (fallback_operation, step.arguments),
        ]
        if step.reduced_scope_arguments:
            variants.append((step.operation, step.reduced_scope_arguments))
        for operation, arguments in variants:
            if operation == "intelligence.video.review":
                validate_uploaded_video_arguments(arguments or {}, {"inputs": inputs})
                continue
            if operation not in {"frameio.video.review", "frameio.assistant.review"}:
                continue
            try:
                target = resolve_value((arguments or {}).get("file_id"), {"inputs": inputs})
            except WorkflowContextError:
                continue  # Prior-step bindings remain the graph compiler's responsibility.
            if not isinstance(target, str):
                continue
            matches = [index for index, doc in uploads
                       if target in (doc["file_url"], doc.get("name"))]
            if matches:
                raise ValueError(
                    "The planned Frame.io review incorrectly uses an uploaded video as file_id. "
                    + ("Several uploads have this name; use the exact user-selected input reference, "
                       "never an arbitrary match. " if len(matches) > 1 else "")
                    + " ".join(video_upload_hint(key, index) for index in matches)
                )
