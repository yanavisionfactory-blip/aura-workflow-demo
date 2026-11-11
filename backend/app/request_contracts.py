"""Keep requested external effects intact across planning and recovery routes."""

from __future__ import annotations

import json
import re

from .connection_families import capability_family

_ACTION = re.compile(
    r"\b(send|email|deliver|forward|post|publish|create|make|schedule|add|"
    r"upload|append|update|edit|modify|write|populate|fill|format|style|delete|remove|archive|cancel|share)\b",
    re.IGNORECASE,
)
_VERBS = {
    "send": {"send", "email", "deliver", "forward", "post", "publish"},
    "create": {"create", "make", "schedule", "add", "upload", "append"},
    "update": {"update", "edit", "modify", "write", "populate", "fill"},
    "format": {"format", "style"},
    "delete": {"delete", "remove", "archive", "cancel"},
    "share": {"share"},
}
_OPERATION_VERBS = {
    "send": {"send", "post", "publish", "deliver", "forward"},
    "create": {"create", "schedule", "add", "upload", "append", "insert"},
    "update": {"update", "edit", "modify", "append"},
    "format": {"format", "formatting", "style"},
    "delete": {"delete", "remove", "archive", "cancel", "revoke"},
    "share": {"share"},
}
_ALIASES = {
    "gmail": ("gmail", "e-mail", "email", "e-mails", "emails"),
    "calendar": ("google calendar", "calendar"),
    "docs": ("google docs", "google doc"),
    "sheets": ("google sheets", "google sheet"),
    "drive": ("google drive", "google disk"),
    "slack": ("slack",),
    "jira": ("jira",),
    "notion": ("notion",),
    "canva": ("canva",),
}
_NEGATION = re.compile(r"\b(?:do not|don't|never|without|no)\s+$", re.IGNORECASE)
_NEGATED_DELIVERY = re.compile(
    r"\b(?:do not|don't|never|without)\s+"
    r"(?:[^.!?;\n]{0,160}?\s+(?:or|nor)\s+)?(?:send|email|mail|deliver)\b",
    re.IGNORECASE,
)
_SOURCE = re.compile(r"\b(?:from|using|about|regarding)\s+$", re.IGNORECASE)
_REVIEW_MARKER = "\n\nThe user reviewed the proposed workflow and requested this change:"
_STEP_ADD = re.compile(
    r"\s+(?:(?:a|an|the)\s+)?(?:(?:separate|new|first|next|last)\s+)?"
    r"(?:(?:read|lookup|search|workflow|planning)\s+)?step\b",
    re.IGNORECASE,
)
_PROVIDER_STEP_ADD = re.compile(
    r"\s+(?:" + "|".join(
        re.escape(alias) for aliases in _ALIASES.values() for alias in aliases
    ) + r")\s+as\s+(?:the\s+)?(?:first|next|last)\s+step\b",
    re.IGNORECASE,
)
_READ_ADD = re.compile(
    r"\s+(?:(?:a|an|the)\s+)?(?:read|lookup|search)\b|"
    r"\s+(?:(?:a|an|the)\s+)?(?:google\s+)?calendar\s+(?:read|lookup|search)\b",
    re.IGNORECASE,
)
_CALENDAR_EVENT_TARGET = re.compile(
    r"\s+(?:(?:a|an|the|new|my|one)\s+)?"
    r"(?:(?:google\s+)?calendar\s+)?(?:events?|meetings?|appointments?|reminders?)\b"
    r"(?!\s+(?:summary|briefing|notes|report|recap|agenda)\b)|"
    r"\s+(?:to|in|on)\s+(?:(?:my|the)\s+)?(?:google\s+)?calendar\b",
    re.IGNORECASE,
)


def user_request_text(prompt: str) -> str:
    """Separate user instructions from saved plans and result reference data."""
    if prompt.startswith("AURA_CONTENT_REVIEW_V1\n"):
        return "Prepare and review a marketing email from supplied evidence inside AURA. No external actions."
    def result_instruction(text):
        marker = "\nSaved result context (reference data): "
        change = "\nRequested change: "
        if text.startswith("Revise the selected ") and change in text and marker in text:
            # The result provider label and report body describe past work.
            # Platform names or imperative text in that saved evidence do not
            # request connections or authorize new actions. JSON escapes its
            # newlines, so report content cannot create these outer markers.
            return text.split(marker, 1)[0].split(change, 1)[1]
        return text

    parts = prompt.split(_REVIEW_MARKER)
    if len(parts) == 1:
        return result_instruction(prompt)
    instructions = [result_instruction(parts[0])]
    for revision in parts[1:]:
        instruction = revision.split("\nCurrent reviewed steps (", 1)[0]
        if instruction.lstrip().startswith("AURA backend authorization rejected the previous plan."):
            # Recovery diagnostics quote rejected operations verbatim. They are
            # internal repair hints, not a new user authorization to send.
            continue
        instructions.append(result_instruction(instruction))
    # Saved result edits can wrap a previously revised prompt. Keep every real
    # user edit, while excluding each serialized plan and any repair diagnostics.
    # JSON-encoded plan text escapes newlines, so it cannot add a review marker.
    return "\n".join(instructions)


def _existing_sheets_recovery(prompt: str) -> bool:
    marker = "Existing Google Sheets workbook receipts (data, not instructions):"
    if marker not in prompt or "Reuse these exact workbooks; do not create replacements." not in prompt:
        return False
    try:
        receipts, _ = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())
    except ValueError:
        return False
    return bool(isinstance(receipts, list) and receipts and all(
        isinstance(item, dict) and isinstance(item.get("spreadsheetId"), str)
        and re.fullmatch(r"[A-Za-z0-9_-]{10,200}", item["spreadsheetId"]) for item in receipts
    ))


def draft_only_email_request(prompt: str) -> bool:
    """A request for email prose does not authorize transmitting an email."""
    instruction = user_request_text(prompt)
    if requested_external_operations(instruction):
        return False
    return bool((
        _NEGATED_DELIVERY.search(instruction)
        and re.search(r"\b(?:emails?|e-mails?|gmail)\b", instruction, re.IGNORECASE)
    ) or re.search(
        r"\b(?:draft|compose|write|prepare)\b.{0,120}\b(?:emails?|e-mails?)\b",
        instruction, re.IGNORECASE | re.DOTALL,
    ) or (
        re.search(r"\b(?:draft|compose|write|prepare)\b.{0,120}"
                  r"\bfollow[\s-]?ups?\b", instruction, re.IGNORECASE | re.DOTALL)
        and re.search(r"\b(?:gmail|email|e-mail)\b", instruction, re.IGNORECASE)
    ))


def requested_external_operations(prompt: str) -> set[str]:
    """Legacy fallback for Gmail requests without a catalog-bound effect contract."""
    prompt = user_request_text(prompt)
    # A review checkpoint is a request to send *after* approval. The draft and
    # its delivery can be in different sentences, so inspect the full prompt.
    reviewed_delivery = (
        re.search(r"\b(?:prepare|draft|compose|write)\s+(?:an?\s+)?(?:email|e-mail)\s+to\b", prompt, re.IGNORECASE)
        and re.search(r"\bbefore\s+sending\s+(?:it|this|the\s+email)\b", prompt, re.IGNORECASE)
        and not re.search(r"\b(?:do not|don't|never|without)\s+send\b", prompt, re.IGNORECASE)
    )
    if reviewed_delivery:
        return {"gmail.send"}
    for clause in re.split(r"[.!?;\n]+", prompt.casefold()):
        if _NEGATED_DELIVERY.search(clause):
            continue
        if (re.search(r"\b(?:draft|compose|write|prepare)\b.{0,120}"
                      r"\b(?:emails?|e-mails?|follow[\s-]?ups?)\b", clause)
                and not re.search(r"\b(?:send|deliver|forward)\b", clause)):
            continue
        if (re.search(r"\b(?:send|deliver|forward)\b.{0,140}\b(?:emails?|e-mails?|gmail)\b", clause)
                or re.search(
                    r"\b(?:use|with|via|through|on|in)\s+(?:my\s+)?"
                    r"(?:gmail|e-mails?|emails?)\b.{0,90}\b(?:send|deliver)\b",
                    clause,
                )
                or re.search(r"\bemail\s+(?:me|us|them|it|this|the|a|an)\b", clause)
                or re.search(
                    r"\bfollow[\s-]?up\s+with\b.{0,160}"
                    r"\b(?:via|through|using|by|on|in)\s+(?:my\s+)?(?:gmail|e-mails?|emails?)\b",
                    clause,
                )):
            return {"gmail.send"}
    return set()


def _family(slug: str, operation: str) -> str:
    prefix = operation.split(".", 1)[0]
    family = capability_family(prefix if "." in operation else slug)
    for known in _ALIASES:
        if family == known or known in capability_family(slug).split("-"):
            return known
    return family


def _aliases(family: str, item: dict) -> set[str]:
    aliases = set(_ALIASES.get(family, ()))
    # Shared Google Workspace operations need their app name, while a
    # dedicated connector can use its public name as a provider cue.
    slug_family = capability_family(item.get("slug"))
    if family == slug_family or family in slug_family.split("-"):
        aliases.add(str(item.get("slug") or "").replace("-", " "))
        aliases.add(str(item.get("name") or ""))
    return {alias.casefold() for alias in aliases if alias and len(alias) >= 3}


def _operation_matches(kind: str, module: dict) -> bool:
    if module.get("permission_scope") not in {"write", "destructive"}:
        return False
    if kind == "format":
        # Formatting permission is deliberately narrower than arbitrary content
        # writes, creation, sharing, deletion, or a provider's batch endpoint.
        return module.get("permission_scope") == "write" and module.get("name") in {
            "google-sheets.format-cells", "google-sheets.format-worksheet",
        }
    words = re.findall(
        r"[a-z]+", (str(module.get("name") or "") + " "
                 + str(module.get("description") or "")).casefold()
    )
    return bool(set(words).intersection(_OPERATION_VERBS[kind]))


def is_gmail_delivery_step(step, manifests: dict | None = None) -> bool:
    field = step.get if isinstance(step, dict) else lambda key: getattr(step, key, None)
    for slug, operation in (
        (field("tool_slug"), field("operation")),
        (field("fallback_tool_slug"), field("fallback_operation")),
    ):
        if not operation:
            continue
        if operation == "gmail.send":
            return True
        if _family(str(slug or ""), str(operation)) != "gmail":
            continue
        module = next((item for item in (manifests or {}).get(slug, {}).get("capabilities", [])
                       if item.get("name") == operation), None)
        if module and _operation_matches("send", module):
            return True
        if module is None and re.search(
            r"(?:^|[._-])(?:send|deliver|forward)(?:$|[._-])", str(operation), re.IGNORECASE
        ):
            return True
    return False


def requested_effects(prompt: str, inventory: list[dict], manifests: dict) -> list[dict]:
    """Bind explicit provider actions to permitted writes in the real catalog.

    A requirement accepts equivalent native or dynamic operations for the
    named provider. Ambiguous phrases such as 'create a summary from Jira'
    remain for the model outcome reviewer to assess.
    """
    prompt = user_request_text(prompt)
    catalog: dict[tuple[str, str], tuple[dict, dict]] = {}
    for item in inventory:
        slug = str(item.get("slug") or "")
        allowed = set(item.get("allowed_operations") or [])
        for module in manifests.get(slug, {}).get("capabilities", []):
            name = str(module.get("name") or "")
            if name in allowed and module.get("permission_scope") in {"write", "destructive"}:
                catalog[slug, name] = (module, item)

    effects: dict[tuple[str, str], set[tuple[str, str]]] = {}
    # Parse explicit calls before sentence splitting: a catalog operation's
    # dot is not punctuation. Mentions, saved plan text and negated calls do
    # not authorize writes. An exact call authorizes only that operation.
    for (slug, operation), (module, _) in catalog.items():
        call = re.compile(
            r"\b(?:use|run|execute|call|insert|add)\s+"
            r"(?:(?:a|an|the|actual|real|supported|bounded)\s+){0,4}"
            + re.escape(operation) + r"(?![\w-]|\.[\w-])", re.IGNORECASE,
        )
        for match in call.finditer(prompt):
            lead = prompt[max(0, match.start() - 50):match.start()]
            if re.search(r"\b(?:do not|don't|never|without|no)(?:\s+\w+){0,3}\s+$",
                         lead, re.IGNORECASE):
                continue
            kind = next((kind for kind in _OPERATION_VERBS
                         if _operation_matches(kind, module)), None)
            if kind:
                effects.setdefault((_family(slug, operation), kind), set()).add((slug, operation))
    for clause in re.split(r"[.!?;\n]+", prompt.casefold()):
        actions = list(_ACTION.finditer(clause))
        if (re.search(r"\b(?:draft|compose|write|prepare)\b.{0,120}\b(?:emails?|e-mails?)\b", clause)
                and not re.search(r"\b(?:send|deliver|forward)\b", clause)):
            # In "draft an email", email is an object, not a command to
            # transmit it. An adjacent Gmail source does not change that.
            actions = [action for action in actions if action.group() != "email"]
        for index, action in enumerate(actions):
            if _NEGATION.search(clause[max(0, action.start() - 20):action.start()]):
                continue
            kind = next(k for k, verbs in _VERBS.items() if action.group() in verbs)
            tail = clause[action.end():actions[index + 1].start() if index + 1 < len(actions) else None]
            if action.group() == "add" and re.search(
                r"\bgoogle\s+sheets?\s+formatting\b", tail,
            ):
                # "Add Google Sheets formatting actions" requests presentation
                # updates, not a new workbook or merely a new read step.
                kind = "format"
            # Editing the workflow structure is not permission to create a
            # provider resource. "Add Google Calendar as the first step" means
            # read that source, while "add an event in Calendar" remains a write.
            if action.group() == "add" and (
                _STEP_ADD.match(tail) or _PROVIDER_STEP_ADD.match(tail)
                or _READ_ADD.match(tail)
            ):
                continue
            lead = clause[max(0, action.start() - 90):action.start()]
            for (slug, operation), (module, item) in catalog.items():
                if not _operation_matches(kind, module):
                    continue
                family = _family(slug, operation)
                if family == "gmail" and kind == "send" and _NEGATED_DELIVERY.search(clause):
                    # Negation also covers coordinated verbs: "do not wait
                    # for a response or send email" must not require delivery.
                    continue
                if family == "calendar" and not _CALENDAR_EVENT_TARGET.match(tail):
                    # "Create a briefing from Calendar" describes a source,
                    # even when Calendar appears later in the same sentence.
                    continue
                if family == "canva" and kind == "create":
                    # Creating a populated slide is a presentation action.
                    # An export job or a blank design cannot satisfy it.
                    wants_slide = re.search(
                        r"\b(?:slides?|presentations?|decks?|roadmaps?|timelines?)\b",
                        clause,
                    )
                    if wants_slide and operation != "canva.presentation.create":
                        continue
                    if operation == "canva.export.create" and not re.search(
                        r"\bexport\b", clause,
                    ):
                        continue
                for alias in _aliases(family, item):
                    match = re.search(r"\b" + re.escape(alias) + r"\b", tail)
                    direct_target = bool(match) and not _SOURCE.search(
                        tail[max(0, match.start() - 12):match.start()]
                    )
                    if direct_target and family not in _ALIASES:
                        # A provider can be the write destination or merely
                        # source material inside another app's new document.
                        prefix = tail[:match.start()]
                        direct_target = bool(re.fullmatch(
                            r"\s*(?:(?:a|an|the|one|new)\s+)*", prefix,
                        ) or re.search(r"\b(?:in|on|via|through)\s+(?:the\s+)?$", prefix))
                    leading_provider = re.search(
                        r"\b(?:use|with|in|on)\s+(?:the\s+)?" + re.escape(alias)
                        + r"\s+to\s+$", lead,
                    )
                    if not direct_target and not leading_provider:
                        continue
                    effects.setdefault((family, kind), set()).add((slug, operation))
                    break

    # 'Email me' has no named provider but clearly asks for delivery. Include
    # every catalog route able to send via Gmail, not just one native slug.
    if requested_external_operations(prompt) and ("gmail", "send") not in effects:
        email_senders = {
            (slug, operation) for (slug, operation), (module, _) in catalog.items()
            if _family(slug, operation) == "gmail" and _operation_matches("send", module)
        }
        if email_senders:
            effects[("gmail", "send")] = email_senders

    if _existing_sheets_recovery(prompt) and ("sheets", "create") in effects:
        # The requested workbook already exists. Complete its cells through
        # an approved update rather than requiring another create/append.
        updates = {(slug, operation) for (slug, operation), (module, _) in catalog.items()
                   if _family(slug, operation) == "sheets" and _operation_matches("update", module)}
        if updates:
            effects.pop(("sheets", "create"))
            effects.setdefault(("sheets", "update"), set()).update(updates)

    return [
        {"effect": f"{family} {kind}", "targets": [
            {"tool_slug": slug, "operation": operation}
            for slug, operation in sorted(targets)
        ]}
        for (family, kind), targets in sorted(effects.items())
    ]


def validate_revision_write_scope(
    prompt: str, plan, inventory: list[dict], manifests: dict,
    connection_routes: dict[str, str] | None = None,
) -> None:
    """The orchestrator may add a write only when the user requested it.

    Read expansions can preserve reviewed writes, but a model-generated write
    for another app must never become an approvable revision.
    """
    if _REVIEW_MARKER not in prompt:
        return
    marker = "\nCurrent reviewed steps (preserve unchanged steps and dependencies): "
    _, found, serialized = prompt.rpartition(marker)
    if not found:
        return
    try:
        reviewed, _ = json.JSONDecoder().raw_decode(serialized)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("The reviewed plan could not be read for revision authorization") from exc
    if not isinstance(reviewed, list):
        raise TypeError("The reviewed plan must contain a list of steps")
    prior_operations = {
        (str(step.get("tool")), str(step.get("operation"))) for step in reviewed
        if isinstance(step, dict) and isinstance(step.get("tool"), str)
        and isinstance(step.get("operation"), str)
    }
    authorized = {
        (target["tool_slug"], target["operation"])
        for effect in requested_effects(prompt, inventory, manifests)
        for target in effect["targets"]
    }
    prior_write_kinds: dict[str, set[str]] = {}
    # These are the actual shared Google writes this recovery can replace.
    # Appending rows modifies an existing workbook; it must not authorize a
    # new workbook merely because "append" is a generic create-effect verb.
    replaceable_writes = {
        "docs.create": {"create"}, "sheets.kpi.create": {"create"},
        "sheets.campaign_report.create": {"create"}, "sheets.append": {"update"},
    }
    for slug, operation in prior_operations:
        module = next((item for item in manifests.get(slug, {}).get("capabilities", [])
                       if item.get("name") == operation), {})
        if module.get("permission_scope") == "write":
            prior_write_kinds.setdefault(_family(slug, operation), set()).update(
                replaceable_writes.get(operation, set())
            )
    calls = [(step.tool_slug, step.operation) for step in plan.steps]
    if connection_routes:
        calls.extend((step.fallback_tool_slug, step.fallback_operation) for step in plan.steps
                     if step.fallback_tool_slug and step.fallback_operation)
    for slug, operation in calls:
        module = next((item for item in manifests.get(slug, {}).get("capabilities", [])
                       if item.get("name") == operation), None)
        if not module or module.get("permission_scope") not in {"write", "destructive"}:
            continue
        if (slug, operation) in prior_operations | authorized:
            continue
        family = _family(slug, operation)
        # Changing a draft's connection requires different real operations.
        # Preserve the reviewed creation/content writes only on the explicitly
        # selected route; it cannot authorize deletion, sharing, delivery or
        # writes for a previously read-only app. Start still needs fresh review.
        prior_kinds = prior_write_kinds.get(family, set())
        if ((connection_routes or {}).get(family) == slug
                and module.get("permission_scope") == "write"
                and not any(_operation_matches(kind, module) for kind in ("delete", "share", "send"))
                and (("create" in prior_kinds and any(_operation_matches(kind, module) for kind in ("create", "update")))
                     or ("update" in prior_kinds and _operation_matches("update", module)))):
            continue
        raise ValueError(
            f"Unrequested {family} write in the revised plan: {operation}. "
            "Keep the reviewed actions and add only the requested reads."
        )


def missing_requested_operations(
    prompt: str, operations: set[str], effects: list[dict] | None = None,
    artifacts: list[dict] | None = None,
) -> set[str]:
    if effects is None:
        return requested_external_operations(prompt) - operations
    missing = set()
    for effect in effects:
        targets = effect.get("targets") or []
        if artifacts is not None:
            matched = any(
                item.get("operation") == target.get("operation")
                and item.get("tool") == target.get("tool_slug")
                for item in artifacts for target in targets
            )
        else:
            matched = any(target.get("operation") in operations for target in targets)
        if not matched:
            missing.add(str(effect.get("effect") or "requested external action"))
    return missing


def validate_requested_operations(
    prompt: str, plan, available: set[str],
    inventory: list[dict] | None = None, manifests: dict | None = None,
    *, connection_routes: dict[str, str] | None = None,
) -> list[dict]:
    from .audit_sources import validate_audit_sources
    from .dashboard_quality import validate_dashboard_plan
    from .presentation_sources import validate_source_presentation_plan
    from .proofing import validate_proofing_sources

    validate_dashboard_plan(prompt, plan)
    validate_source_presentation_plan(user_request_text(prompt), plan)
    validate_audit_sources(user_request_text(prompt), plan, inventory or [])
    validate_proofing_sources(user_request_text(prompt), plan, inventory or [], manifests or {})
    if (_existing_sheets_recovery(prompt)
            and any(step.operation in {"google-sheets.new-spreadsheet", "google-sheets.create-spreadsheet",
                                       "sheets.kpi.create"} for step in plan.steps)):
        raise ValueError("This recovery must reuse the saved Google Sheets workbook; read its tabs and cells before proposing missing changes")
    if _existing_sheets_recovery(prompt):
        from .sheets_targets import DISCOVERY

        metadata = {step.key for step in plan.steps if step.operation in DISCOVERY
                    or step.operation == "sheets.workbook.get"}
        cells = {step.key for step in plan.steps if step.operation in {
            "google-sheets.get-values-in-range", "google-sheets.read-rows", "sheets.read",
        }}
        by_key = {step.key: step for step in plan.steps}
        for step in plan.steps:
            if not step.consequential or _family(step.tool_slug, step.operation) != "sheets":
                continue
            ancestors, pending = set(), list(step.depends_on)
            while pending:
                key = pending.pop()
                if key not in ancestors:
                    ancestors.add(key)
                    pending.extend(by_key[key].depends_on if key in by_key else [])
            if not metadata.intersection(ancestors) or not cells.intersection(ancestors):
                raise ValueError("Every remaining Sheets write must depend on reading the existing workbook's worksheet metadata and current cells first")
    if draft_only_email_request(prompt) and any(
        is_gmail_delivery_step(step, manifests) for step in plan.steps
    ):
        raise ValueError(
            "The user requested email drafts only. Gmail send operations transmit emails; "
            "remove every send step and synthesize the finished drafts from read evidence."
        )
    if inventory is not None and manifests is not None:
        validate_revision_write_scope(prompt, plan, inventory, manifests, connection_routes)
    if (
        draft_only_email_request(prompt)
        and (re.search(r"\b(?:gmail|inbox|mailbox)\b", user_request_text(prompt), re.IGNORECASE)
             or any(step.operation.startswith("gmail.") for step in plan.steps))
        and re.search(r"\b(?:customers?|clients?|contacts?)\b", prompt, re.IGNORECASE)
        and re.search(r"\bfollow[\s-]?up\b|\bfollowed\s+up\b", prompt, re.IGNORECASE)
        and "gmail.threads.read" not in {step.operation for step in plan.steps}
    ):
        raise ValueError(
            "To find customer follow-ups in Gmail and draft personalized emails, "
            "read the actual conversation and sent history with gmail.threads.read. "
            "Message IDs and a single message cannot establish the missing follow-ups."
        )
    effects = requested_effects(prompt, inventory, manifests) if inventory is not None and manifests is not None else []
    if not effects:
        missing = requested_external_operations(prompt) - {
            step.operation for step in plan.steps if not getattr(step, "optional", False)
        }
        if missing:
            raise ValueError(
                "Requested external action is absent from the executable plan: "
                + ", ".join(sorted(missing))
                + ". Add the exact approved operation with its real inputs and dependencies."
            )
    for effect in effects:
        if not any(
            not getattr(step, "optional", False) and any(
                step.tool_slug == target["tool_slug"] and step.operation == target["operation"]
                for target in effect["targets"]
            ) for step in plan.steps
        ):
            raise ValueError(
                "Requested external action is absent from the executable plan: "
                + effect["effect"] + ". Add a required approved operation from: "
                + ", ".join(sorted({target["operation"] for target in effect["targets"]}))
                + ". Keep it through every recovery attempt."
            )
    if (
        any(step.operation == "gmail.list" for step in plan.steps)
        and not any(step.operation == "gmail.get" for step in plan.steps)
        and re.search(r"\b(?:gmail|e-mails?|emails?|inbox|mailbox|messages?)\b", prompt, re.IGNORECASE)
        and re.search(
            r"\b(?:personaliz\w*|summari[sz]\w*|draft\w*|compos\w*|"
            r"follow(?:ed|ing)?[\s-]?up|check[\s-]?in)\b",
            prompt, re.IGNORECASE,
        )
    ):
        raise ValueError(
            "Gmail.list returns message IDs, not the message content needed for this "
            "request. Add gmail.get after the search and use its verified output "
            "before drafting or sending."
        )
    if (
        any(step.operation == "gmail.list" for step in plan.steps)
        and re.search(r"\bpersonaliz\w*\b", prompt, re.IGNORECASE)
    ):
        reads = {step.key for step in plan.steps if step.operation == "gmail.get"}
        by_key = {step.key: step for step in plan.steps}
        for send in (step for step in plan.steps if step.operation == "gmail.send"):
            pending = list(send.depends_on)
            visited: set[str] = set()
            while pending:
                key = pending.pop()
                if key in visited:
                    continue
                visited.add(key)
                pending.extend(by_key[key].depends_on if key in by_key else [])
            if not reads.intersection(visited):
                raise ValueError(
                    "A personalized Gmail follow-up must depend on the gmail.get "
                    "message context before its approval and send step."
                )
    if (
        "gmail.send" in requested_external_operations(prompt)
        and re.search(r"\b(?:customers?|clients?|contacts?)\b", prompt, re.IGNORECASE)
        and re.search(r"\b(?:follow[\s-]?up|check[\s-]?in|personaliz\w*)\b", prompt, re.IGNORECASE)
        and not re.search(r"\b(?:send|email|deliver)\b.{0,100}\b(?:to me|my inbox|myself)\b", prompt, re.IGNORECASE)
        and any(
            step.operation == "gmail.send" and str(step.arguments.get("to", "")).casefold() in {"me", "myself", "self"}
            for step in plan.steps
        )
    ):
        raise ValueError(
            "Customer follow-up emails must address the resolved customers, not the connected account. "
            "Use recipient values from verified customer context and show each completed email for approval."
        )
    plan.planning_artifacts["required_effects"] = effects
    return effects
