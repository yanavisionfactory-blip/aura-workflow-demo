import json
import logging
import re
from typing import Any

from .schemas import StepCondition

logger = logging.getLogger(__name__)

REFERENCE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-\[\]'\" ]+?)\s*\}\}")
BRACKET_INDEX = re.compile(r"\[(\d+)\]")
BRACKET_KEY = re.compile(r"\[['\"]([^'\"]+)['\"]\]")


class WorkflowContextError(ValueError):
    pass


def referenced_paths(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(referenced_paths(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(referenced_paths(item) for item in value))
    if not isinstance(value, str):
        return set()
    return {normalize_reference_path(match.group(1)) for match in REFERENCE.finditer(value)}


def normalize_reference_path(path: str) -> str:
    path = BRACKET_KEY.sub(lambda match: f".{match.group(1)}", path)
    return BRACKET_INDEX.sub(lambda match: f".{match.group(1)}", path)


def qualify_prior_step_references(value: Any, prior_keys: set[str]) -> Any:
    """Qualify an unambiguous model reference to an earlier planned step.

    Only an exact, already declared step key may become a ``steps.*`` path.
    Other roots still fail preflight; this never invents a resource or output.
    """
    if isinstance(value, dict):
        return {key: qualify_prior_step_references(item, prior_keys) for key, item in value.items()}
    if isinstance(value, list):
        return [qualify_prior_step_references(item, prior_keys) for item in value]
    if not isinstance(value, str):
        return value

    def qualify(match: re.Match) -> str:
        path = match.group(1).strip()
        root = re.split(r"[.\[]", path, maxsplit=1)[0]
        if root in prior_keys and root not in {"inputs", "vars", "steps"}:
            return "{{steps." + path + "}}"
        return match.group(0)

    return REFERENCE.sub(qualify, value)


def referenced_step_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(referenced_step_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(referenced_step_keys(item) for item in value))
    if not isinstance(value, str):
        return set()
    return {
        path.split(".", 2)[1]
        for path in referenced_paths(value)
        if path.startswith("steps.") and len(path.split(".")) >= 2
    }


def _lookup(context: dict[str, Any], path: str) -> Any:
    # Structured planners commonly use JavaScript-style paths such as
    # ``steps.search.results[0].id``. Convert their safe bracket forms to the
    # same dotted tokens the resolver already understands. This remains a
    # data lookup only; arbitrary expressions are never evaluated.
    normalized_path = BRACKET_KEY.sub(lambda match: f".{match.group(1)}", path)
    normalized_path = BRACKET_INDEX.sub(lambda match: f".{match.group(1)}", normalized_path)
    value: Any = context
    for part in normalized_path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
            continue
        raise WorkflowContextError(f"Workflow variable {path!r} is unavailable")
    return value


def resolve_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: resolve_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if not isinstance(value, str):
        return value
    match = REFERENCE.fullmatch(value)
    if match:
        return _lookup(context, match.group(1))

    def replace(reference: re.Match) -> str:
        resolved = _lookup(context, reference.group(1))
        if isinstance(resolved, dict) and isinstance(resolved.get("summary"), str):
            return resolved["summary"]
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, separators=(",", ":"))
        if resolved is None:
            return ""
        return str(resolved)

    return REFERENCE.sub(replace, value)


def _notion_context_value(value: Any) -> Any:
    """Add a plain title alias without changing the provider evidence.

    Notion page titles live in a property whose name is user-defined. Only
    the provider's title-typed property is authoritative; never guess a name
    or fabricate a title when that property was not returned.
    """
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    if isinstance(value.get("results"), list):
        normalized["results"] = [_notion_context_value(item) for item in value["results"]]
    properties = value.get("properties")
    if "title" not in value and isinstance(properties, dict):
        for prop in properties.values():
            if not isinstance(prop, dict) or prop.get("type") != "title":
                continue
            parts = prop.get("title")
            if not isinstance(parts, list):
                continue
            texts = []
            for part in parts:
                if not isinstance(part, dict):
                    break
                text = part.get("plain_text")
                if not isinstance(text, str) and isinstance(part.get("text"), dict):
                    text = part["text"].get("content")
                if not isinstance(text, str):
                    break
                texts.append(text)
            else:
                normalized["title"] = "".join(texts)
            break
    return normalized


def _pipedream_result_object(result: dict[str, Any]) -> dict[str, Any] | None:
    """Find a single returned object inside a Pipedream action receipt.

    Action receipts wrap the application result in ``ret`` or ``exports``.
    An ID is usable as a downstream resource only when the receipt identifies
    exactly one object; choosing the first search match could target the wrong
    folder or document.
    """
    def single(value: Any, depth: int = 0) -> dict[str, Any] | None:
        if depth > 4:
            return None
        if isinstance(value, list):
            return single(value[0], depth + 1) if len(value) == 1 else None
        if not isinstance(value, dict):
            return None
        if value.get("id"):
            return value
        candidates = [
            single(value[key], depth + 1)
            for key in ("data", "results", "items", "records", "files", "folders", "folder")
            if key in value
        ]
        found = [candidate for candidate in candidates if candidate and candidate.get("id")]
        return found[0] if len(found) == 1 else None

    if result.get("ret") is not None:
        return single(result["ret"])
    return single(result.get("exports"))


def _exact_folder_result(result: dict[str, Any], arguments: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve a broad folder search only when one result has the requested name."""
    args = arguments if isinstance(arguments, dict) else {}
    name = next((args.get(key) for key in ("nameSearchTerm", "searchName", "name", "folderName")
                 if isinstance(args.get(key), str) and args[key].strip()), None)
    if not name:
        return None
    candidates = result.get("ret")
    if isinstance(candidates, dict):
        if candidates.get("id"):
            candidates = [candidates]
        else:
            candidates = candidates.get("files", candidates.get("folders", candidates.get("data")))
        if isinstance(candidates, dict) and not candidates.get("id"):
            candidates = candidates.get("files", candidates.get("folders", candidates.get("results")))
        if isinstance(candidates, dict) and candidates.get("id"):
            candidates = [candidates]
    if not isinstance(candidates, list):
        return None
    matching = [item for item in candidates if isinstance(item, dict)
                and item.get("name") == name.strip() and item.get("id")
                and item.get("mimeType") in (None, "application/vnd.google-apps.folder")]
    return matching[0] if len(matching) == 1 else None


def _unique_notes_doc(result: dict[str, Any]) -> tuple[dict[str, Any] | None, int, int]:
    """Choose only an unambiguous Docs file for a planned notes-document read."""
    returned = result.get("ret")
    files = returned.get("files") if isinstance(returned, dict) else returned
    if not isinstance(files, list):
        return None, 0, 0
    docs = [item for item in files if isinstance(item, dict) and item.get("id")
            and item.get("mimeType") == "application/vnd.google-apps.document"]
    notes = [item for item in docs if isinstance(item.get("name"), str)
             and re.search(r"\bnotes?\b", item["name"], re.IGNORECASE)]
    if len(notes) == 1:
        return notes[0], len(docs), len(notes)
    return (docs[0] if len(docs) == 1 else None), len(docs), len(notes)


def _complete_indexed_doc_reads(
    result: dict[str, Any], step_key: str | None, planned_steps: list[dict] | None,
) -> list[dict] | None:
    """Expose a multi-file list only if the reviewed plan reads every Docs item."""
    returned = result.get("ret")
    files = returned.get("files") if isinstance(returned, dict) else returned
    if not isinstance(files, list) or not files or len(files) > 20 or not step_key or not planned_steps:
        return None
    if any(not isinstance(item, dict) or not item.get("id") or
           item.get("mimeType") != "application/vnd.google-apps.document" for item in files):
        return None
    expected = {f"steps.{step_key}.files.{index}.id" for index in range(len(files))}
    covered = set().union(*(
        referenced_paths(step.get("arguments", {})) for step in planned_steps
        if step.get("operation") == "google-docs.get-document" and not step.get("optional")
    ))
    return files if expected <= covered else None


def _result_shape(value: Any, depth: int = 0) -> Any:
    """Describe receipt structure without logging folder names, IDs or content."""
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, list):
        return {"type": "list", "count": len(value),
                "first": _result_shape(value[0], depth + 1) if len(value) == 1 else None}
    if isinstance(value, dict):
        known = {"ret", "exports", "data", "files", "folders", "folder", "results",
                 "items", "id", "name", "status", "error", "success", "details", "object"}
        return {"type": "object", "keys": sorted(known & value.keys()),
                "other_keys": len(value.keys() - known),
                "children": {key: _result_shape(value[key], depth + 1)
                             for key in ("data", "files", "folders", "folder", "results", "items")
                             if key in value}}
    return type(value).__name__


def step_context_value(
    result: Any, operation: str | None = None, arguments: dict[str, Any] | None = None,
    planned_steps: list[dict] | None = None, step_key: str | None = None,
) -> Any:
    """Expose provider results through both canonical and compatibility paths.

    The planner is instructed to use ``steps.key.field`` for named fields, but
    structured-output models can still produce the common ``steps.key.output``
    or ``steps.key.result`` forms when they mean the entire provider response.
    Keep direct fields available while making those whole-result aliases safe.
    """
    evidence = result
    if (operation or "").startswith("notion."):
        result = _notion_context_value(result)
    if not isinstance(result, dict):
        value = {"output": result, "result": result, "provider_result": result}
    else:
        value = dict(result)
        value.setdefault("output", result)
        value.setdefault("result", result)
        value.setdefault("provider_result", evidence)
        if "ret" in result or "exports" in result:
            returned = _pipedream_result_object(result)
            if operation == "google-docs.get-document":
                doc = result.get("ret")
                if isinstance(doc, dict) and isinstance(doc.get("textContent"), str):
                    tabs = doc.get("tabs")
                    tab_texts = [
                        tab.get("textContent") for tab in tabs
                        if isinstance(tab, dict) and isinstance(tab.get("textContent"), str)
                    ] if isinstance(tabs, list) else []
                    value.setdefault("textContent", "\n\n".join(tab_texts) if tab_texts
                                     else doc["textContent"])
                logger.info(
                    "docs_receipt_text ret_type=%s text_present=%s tabs=%s",
                    type(doc).__name__,
                    bool(isinstance(doc, dict) and isinstance(doc.get("textContent"), str)),
                    len(doc.get("tabs", [])) if isinstance(doc, dict)
                    and isinstance(doc.get("tabs"), list) else 0,
                )
            if operation == "google-drive.find-folder" and isinstance(arguments, dict) and any(
                isinstance(arguments.get(key), str) and arguments[key].strip()
                for key in ("nameSearchTerm", "searchName", "name", "folderName")
            ):
                returned = _exact_folder_result(result, arguments)
            doc_count = notes_count = 0
            if operation == "google-drive.list-files" and not returned:
                returned, doc_count, notes_count = _unique_notes_doc(result)
            all_files = (
                _complete_indexed_doc_reads(result, step_key, planned_steps)
                if operation == "google-drive.list-files" else None
            )
            if operation == "google-drive.find-folder":
                logger.info(
                    "drive_folder_receipt_shape ret=%s exports=%s argument_fields=%s confirmed_single=%s",
                    _result_shape(result.get("ret")),
                    _result_shape(result.get("exports")),
                    sorted(arguments) if isinstance(arguments, dict) else [],
                    bool(returned),
                )
            if operation == "google-drive.list-files":
                logger.info(
                    "drive_file_receipt_shape ret=%s exports=%s docs=%s notes_docs=%s selected=%s all_read=%s",
                    _result_shape(result.get("ret")),
                    _result_shape(result.get("exports")),
                    doc_count,
                    notes_count,
                    bool(returned),
                    bool(all_files),
                )
            if returned:
                for key, item in returned.items():
                    value.setdefault(key, item)
                if operation in {"google-drive.find-folder", "google-drive.list-files"}:
                    # Pipedream may return one folder object in ret, while a
                    # planner references it as files[0]. Only expose this
                    # collection alias when the receipt confirms one ID.
                    value.setdefault("files", [returned])
            if all_files:
                value["files"] = all_files

    # Structured planners sometimes name a downstream value after the source
    # operation (for example ``steps.weather.forecast``). Expose that operation
    # noun as a stable compatibility alias. Prefer a provider's human-readable
    # summary when it has one, otherwise preserve the full provider result.
    operation_alias = (operation or "").rsplit(".", 1)[-1]
    if operation_alias:
        alias_value = result.get("summary", result) if isinstance(result, dict) else result
        value.setdefault(operation_alias, alias_value)

    # Expose the resource noun from operations such as ``notion.page.get``.
    # Both ``steps.read.id`` and ``steps.read.page.id`` then address the same
    # provider-confirmed object without connector-specific mappings.
    operation_parts = (operation or "").split(".")
    for resource_name in operation_parts[1:-1]:
        value.setdefault(resource_name, result)

    # Search/list providers use different collection nouns (results, items,
    # records, candidates). Expose stable compatibility aliases so a valid
    # provider response can feed the next step without leaking those naming
    # differences into planner reliability.
    if isinstance(result, dict):
        collection = next(
            (
                result.get(key)
                for key in ("results", "items", "records", "candidates", "data")
                if isinstance(result.get(key), list)
            ),
            None,
        )
        if collection is not None:
            for alias in ("results", "items", "records", "candidates"):
                value.setdefault(alias, collection)
            if collection and isinstance(collection[0], dict):
                first = collection[0]
                value.setdefault("item", first)
                value.setdefault("candidate", first)
                entity_name = next(
                    (
                        first.get(key)
                        for key in ("object", "type", "kind")
                        if isinstance(first.get(key), str)
                        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", first[key])
                    ),
                    None,
                )
                if entity_name:
                    singular = entity_name.lower().replace("-", "_")
                    if singular.endswith("y") and not singular.endswith(("ay", "ey", "iy", "oy", "uy")):
                        plural = f"{singular[:-1]}ies"
                    elif singular.endswith("s"):
                        plural = singular
                    else:
                        plural = f"{singular}s"
                    value.setdefault(singular, first)
                    if first.get("id"):
                        value.setdefault(f"{singular}_id", first["id"])
                    value.setdefault(plural, collection)
                for key, item in first.items():
                    value.setdefault(key, item)
    return value


def canonical_action_arguments(operation: str, arguments: dict, context: dict) -> dict:
    """Bind job-backed resource inputs to their completed provider result.

    A job ID and the resource it created are distinct identities. Repair only
    an exact receipt match from this run; never substitute an unrelated design.
    """
    if operation != "canva.export.create":
        return arguments
    requested = arguments.get("design_id")
    candidates = set()
    matched_job = False
    for output in context.get("steps", {}).values():
        if not isinstance(output, dict):
            continue
        receipt = output.get("provider_result", output)
        if not isinstance(receipt, dict):
            continue
        job = receipt.get("job", {})
        if not isinstance(job, dict) or job.get("id") != requested:
            continue
        matched_job = True
        designs = job.get("result", {}).get("designs", [])
        if job.get("status") == "success" and len(designs) == 1 and designs[0].get("id"):
            candidates.add(designs[0]["id"])
    if matched_job:
        if len(candidates) != 1:
            raise WorkflowContextError("The saved import job does not identify one completed design")
        return {**arguments, "design_id": candidates.pop()}
    return arguments


def evaluate_condition(condition: StepCondition | dict, context: dict[str, Any]) -> bool:
    rule = (
        condition
        if isinstance(condition, StepCondition)
        else StepCondition.model_validate(condition)
    )
    try:
        left = resolve_value(rule.left, context)
    except WorkflowContextError:
        if rule.operator == "exists":
            return False
        if rule.operator == "not_exists":
            return True
        raise
    right = resolve_value(rule.right, context)
    operator = rule.operator
    if operator == "exists":
        return left is not None
    if operator == "not_exists":
        return left is None
    if operator == "is_true":
        return left is True
    if operator == "is_false":
        return left is False
    if operator == "equals":
        return left == right
    if operator == "not_equals":
        return left != right
    try:
        if operator == "contains":
            return right in left
        if operator == "not_contains":
            return right not in left
        if operator == "greater_than":
            return left > right
        if operator == "greater_than_or_equal":
            return left >= right
        if operator == "less_than":
            return left < right
        if operator == "less_than_or_equal":
            return left <= right
    except (TypeError, ValueError) as exc:
        raise WorkflowContextError(
            f"Condition {operator!r} cannot compare these workflow values"
        ) from exc
    raise WorkflowContextError(f"Unsupported condition operator: {operator}")


def requires_content_composition(arguments: dict, input_schema: dict, context: dict) -> bool:
    """Structured evidence used as text needs composition, not JSON interpolation."""
    for name, value in arguments.items():
        if input_schema.get("properties", {}).get(name, {}).get("type") != "string":
            continue
        for path in referenced_paths(value):
            if isinstance(resolve_value("{{" + path + "}}", context), (dict, list)):
                return True
    return False
