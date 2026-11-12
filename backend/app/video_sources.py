"""Keep uploaded video references distinct from provider asset identifiers."""

from .workflow_context import WorkflowContextError, resolve_value


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


def validate_video_source_bindings(plan, inputs: dict | None) -> None:
    """Reject a wrong source while the planner still has its repair pass.

    Do not substitute assets, alter an approved plan or infer missing provider
    IDs. Valid Frame.io targets can coexist with unrelated attached videos.
    """
    if not inputs:
        return
    key = "attached_documents" if "attached_documents" in inputs else "documents"
    documents = inputs.get(key)
    if not isinstance(documents, list):
        return
    uploads = [(index, doc) for index, doc in enumerate(documents)
               if isinstance(doc, dict) and video_upload(doc)]
    for step in plan.steps:
        for operation, arguments in (
            (step.operation, step.arguments),
            (step.fallback_operation, step.arguments),
            (step.operation, step.reduced_scope_arguments),
        ):
            if operation != "frameio.video.review":
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
