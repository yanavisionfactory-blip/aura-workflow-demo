"""Provider-agnostic proof that a workflow graph covers the user's request.

The planner may propose how work should be done, but it does not get to decide
which requested outcomes matter.  This module derives a small, deterministic
contract from the user's own words and proves that the approved graph contains
compatible evidence for every clause.  The proof is persisted with the plan so
the approval and outcome boundaries can re-check the same contract.
"""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Literal

from pydantic import BaseModel, Field

from .policy import operation_scope
from .schemas import PlanStep, WorkflowPlan

RequirementAction = Literal[
    "read",
    "synthesize",
    "create",
    "export",
    "store",
    "publish",
    "send",
    "update",
    "delete",
    "schedule",
    "outcome",
]


class AtomicRequirement(BaseModel):
    key: str = Field(pattern=r"^requirement_[1-9][0-9]*$")
    statement: str = Field(min_length=1, max_length=1000)
    action: RequirementAction
    provider_slugs: list[str] = Field(default_factory=list)
    format_hints: list[str] = Field(default_factory=list)
    content_terms: list[str] = Field(default_factory=list)
    constraint_terms: list[str] = Field(default_factory=list)


class RequirementEvidence(BaseModel):
    requirement_key: str
    step_keys: list[str] = Field(default_factory=list)
    proof_kind: Literal["graph", "synthesis"] = "graph"


class ExclusionConstraint(BaseModel):
    key: str = Field(pattern=r"^constraint_[1-9][0-9]*$")
    statement: str = Field(min_length=1, max_length=1000)
    forbidden_provider_slugs: list[str] = Field(default_factory=list)
    forbidden_operations: list[str] = Field(default_factory=list)


class RequestGraphProof(BaseModel):
    version: int = 2
    requirements: list[AtomicRequirement] = Field(default_factory=list)
    constraints: list[ExclusionConstraint] = Field(default_factory=list)
    evidence: list[RequirementEvidence] = Field(default_factory=list)
    fixes: list[str] = Field(default_factory=list)


_ACTION_PHRASES: list[tuple[str, RequirementAction]] = [
    ("look up", "read"),
    ("follow up", "send"),
    ("send", "send"),
    ("email", "send"),
    ("notify", "send"),
    ("share", "send"),
    ("message", "send"),
    ("publish", "publish"),
    ("post", "publish"),
    ("export", "export"),
    ("download", "export"),
    ("render", "export"),
    ("convert", "export"),
    ("save", "store"),
    ("store", "store"),
    ("upload", "store"),
    ("archive", "store"),
    ("schedule", "schedule"),
    ("book", "schedule"),
    ("delete", "delete"),
    ("remove", "delete"),
    ("cancel", "delete"),
    ("update", "update"),
    ("edit", "update"),
    ("change", "update"),
    ("append", "update"),
    ("summarize", "synthesize"),
    ("analyse", "synthesize"),
    ("analyze", "synthesize"),
    ("compare", "synthesize"),
    ("calculate", "synthesize"),
    ("extract", "synthesize"),
    ("classify", "synthesize"),
    ("draft", "synthesize"),
    ("include", "synthesize"),
    ("exclude", "synthesize"),
    ("prepare", "create"),
    ("create", "create"),
    ("make", "create"),
    ("generate", "create"),
    ("build", "create"),
    ("produce", "create"),
    ("write", "create"),
    ("check", "read"),
    ("find", "read"),
    ("search", "read"),
    ("retrieve", "read"),
    ("fetch", "read"),
    ("get", "read"),
    ("read", "read"),
    ("inspect", "read"),
    ("review", "read"),
    ("monitor", "read"),
    ("list", "read"),
]

_ACTION_PATTERN = "|".join(
    sorted((re.escape(value) for value, _ in _ACTION_PHRASES), key=len, reverse=True)
)
_ACTION_RE = re.compile(rf"\b({_ACTION_PATTERN})\b", re.IGNORECASE)
_FORMAT_RE = re.compile(
    r"\b(pdf|csv|xlsx?|docx?|pptx?|png|jpe?g|svg|json|xml|html|markdown|md|zip)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)

_STOP_WORDS = {
    "a",
    "all",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "it",
    "its",
    "latest",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "please",
    "requested",
    "result",
    "results",
    "the",
    "their",
    "them",
    "this",
    "through",
    "to",
    "using",
    "via",
    "with",
}
_GENERIC_PROVIDER_ALIASES = {
    "app",
    "data",
    "file",
    "files",
    "item",
    "items",
    "page",
    "pages",
    "record",
    "records",
    "tool",
    "workspace",
}
_EXPLICIT_CONSTRAINT_TERMS = {
    "all",
    "celsius",
    "editable",
    "every",
    "exact",
    "fahrenheit",
    "only",
    "without",
}
_INTERNAL_DELIVERABLE_TERMS = {
    "analysis",
    "answer",
    "brief",
    "briefing",
    "calculation",
    "comparison",
    "digest",
    "explanation",
    "list",
    "recommendation",
    "report",
    "summary",
    "table",
    "timeline",
}
_EXTERNAL_ARTIFACT_FORMATS = {
    "doc",
    "docx",
    "jpeg",
    "jpg",
    "pdf",
    "png",
    "ppt",
    "pptx",
    "svg",
    "xls",
    "xlsx",
    "zip",
}
_EXCLUSION_RE = re.compile(
    r"\b(?:do\s+not|don't|never|avoid|exclude|without)\b",
    re.IGNORECASE,
)
_SOURCE_EVIDENCE_RE = re.compile(
    r"\b(?:source(?:s|\s+links?)?|citation(?:s)?|references?|research)\b",
    re.IGNORECASE,
)
_SOURCE_CONSUMING_ACTIONS = {"create", "export", "store", "publish", "send", "update"}


def _normalized_text(value: object) -> str:
    return " ".join(_WORD_RE.findall(str(value or "").casefold()))


def _find_action(statement: str) -> RequirementAction:
    match = _ACTION_RE.search(statement)
    if not match:
        return "outcome"
    phrase = match.group(1).casefold()
    return next(action for value, action in _ACTION_PHRASES if value == phrase)


def _is_exclusion(statement: str) -> bool:
    """Recognize prohibitions before interpreting their nouns as destinations."""
    return bool(_EXCLUSION_RE.search(statement))


def _positive_requirement_statement(statement: str) -> str | None:
    """Keep work before an inline exclusion while dropping pure prohibitions."""
    match = _EXCLUSION_RE.search(statement)
    if not match:
        return statement
    positive = statement[: match.start()].strip(" ,")
    return positive or None


def _split_request(prompt: str) -> list[str]:
    """Split explicit work into bounded clauses without splitting noun phrases."""
    sentences = [
        value.strip(" ,")
        for value in re.split(r"(?:[.;!?]+|\n+)", " ".join(prompt.split()))
        if value.strip(" ,")
    ]
    clauses: list[str] = []
    for sentence in sentences:
        pieces = re.split(
            rf"\s*(?:,|\bthen\b)\s*(?=(?:and\s+)?(?:{_ACTION_PATTERN})\b)",
            sentence,
            flags=re.IGNORECASE,
        )
        expanded: list[str] = []
        for piece in pieces:
            piece = re.sub(r"^and\s+", "", piece.strip(), flags=re.IGNORECASE)
            action_coordinated = re.split(
                rf"\s+and\s+(?=(?:{_ACTION_PATTERN})\b)",
                piece,
                flags=re.IGNORECASE,
            )
            # Shared-verb coordination: "check weather and the latest rates".
            for coordinated in action_coordinated:
                shared = re.split(
                    r"\s+and\s+(?=(?:the|a|an|my|our|all|current|latest|today(?:'s)?|tomorrow(?:'s)?)\b)",
                    coordinated,
                    flags=re.IGNORECASE,
                )
                expanded.extend(
                    value.strip(" ,") for value in shared if value.strip(" ,")
                )
        previous_action: RequirementAction = "outcome"
        for piece in expanded:
            action = _find_action(piece)
            if action == "outcome" and previous_action != "outcome":
                verb = next(value for value, kind in _ACTION_PHRASES if kind == previous_action)
                piece = f"{verb} {piece}"
            else:
                previous_action = action
            clauses.append(piece)
    return clauses[:30] or ["Complete the requested outcome"]


def _inventory_provider_aliases(item: dict) -> set[str]:
    values = {
        str(item.get("slug") or ""),
        str(item.get("name") or ""),
        str(item.get("canonical_provider") or ""),
        *(
            str(operation).split(".", 1)[0]
            for operation in item.get("allowed_operations") or []
        ),
    }
    aliases = {_normalized_text(value) for value in values if value}
    return {
        alias
        for alias in aliases
        if alias and alias not in _GENERIC_PROVIDER_ALIASES and len(alias) >= 3
    }


def _explicit_provider_aliases(item: dict) -> set[str]:
    """Return provider names without operation namespaces such as ``weather``.

    Operation namespaces are useful for positive capability routing, but treating
    them as provider identities made "do not use weather" require the entire AURA
    connector.  Exclusions keep providers and operations distinct.
    """
    values = {
        str(item.get("slug") or ""),
        str(item.get("name") or ""),
        str(item.get("canonical_provider") or ""),
    }
    aliases = {_normalized_text(value) for value in values if value}
    return {
        alias
        for alias in aliases
        if alias and alias not in _GENERIC_PROVIDER_ALIASES and len(alias) >= 3
    }


def _internal_synthesis_action(
    statement: str,
    action: RequirementAction,
    provider_slugs: list[str],
    format_hints: list[str],
    provider_can_create: bool,
) -> RequirementAction:
    """Classify chat-native deliverables as synthesis, not fictional provider calls."""
    if (
        action != "create"
        or (provider_slugs and provider_can_create)
        or set(format_hints).intersection(_EXTERNAL_ARTIFACT_FORMATS)
    ):
        return action
    words = set(_WORD_RE.findall(statement.casefold()))
    return "synthesize" if words.intersection(_INTERNAL_DELIVERABLE_TERMS) else action


def derive_request_constraints(
    prompt: str, inventory: list[dict]
) -> list[ExclusionConstraint]:
    constraints: list[ExclusionConstraint] = []
    for statement in _split_request(prompt):
        exclusion = _EXCLUSION_RE.search(statement)
        if not exclusion:
            continue
        exclusion_scope = statement[exclusion.start():]
        exclusion_scope = re.split(
            r"\b(?:but|however|instead)\b",
            exclusion_scope,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        normalized = f" {_normalized_text(exclusion_scope)} "
        forbidden_provider_slugs: list[str] = []
        forbidden_operations: list[str] = []
        for item in inventory:
            slug = str(item.get("slug") or "")
            if slug and any(
                f" {alias} " in normalized for alias in _explicit_provider_aliases(item)
            ):
                forbidden_provider_slugs.append(slug)
            for operation in item.get("allowed_operations") or []:
                operation_text = _normalized_text(operation)
                namespace = operation_text.split(" ", 1)[0]
                if namespace and f" {namespace} " in normalized:
                    forbidden_operations.append(str(operation))
        constraints.append(
            ExclusionConstraint(
                key=f"constraint_{len(constraints) + 1}",
                statement=statement,
                forbidden_provider_slugs=list(dict.fromkeys(forbidden_provider_slugs)),
                forbidden_operations=list(dict.fromkeys(forbidden_operations)),
            )
        )
    return constraints


def _content_terms(statement: str, provider_aliases: set[str]) -> list[str]:
    action_words = {
        token
        for phrase, _ in _ACTION_PHRASES
        for token in _WORD_RE.findall(phrase)
    }
    provider_words = {
        token for alias in provider_aliases for token in _WORD_RE.findall(alias)
    }
    return list(
        dict.fromkeys(
            token
            for token in _WORD_RE.findall(statement.casefold())
            if len(token) > 2
            and token not in _STOP_WORDS
            and token not in action_words
            and token not in provider_words
            and not token.isdigit()
        )
    )[:12]


def derive_request_requirements(
    prompt: str, inventory: list[dict]
) -> list[AtomicRequirement]:
    inventory_aliases = [
        (str(item.get("slug") or ""), _inventory_provider_aliases(item))
        for item in inventory
    ]
    requirements: list[AtomicRequirement] = []
    for raw_statement in _split_request(prompt):
        statement = _positive_requirement_statement(raw_statement)
        if not statement:
            continue
        normalized = f" {_normalized_text(statement)} "
        provider_slugs: list[str] = []
        matched_aliases: set[str] = set()
        for slug, aliases in inventory_aliases:
            matching = {
                alias for alias in aliases if f" {alias} " in normalized
            }
            if slug and matching:
                provider_slugs.append(slug)
                matched_aliases.update(matching)
        format_hints = list(
            dict.fromkeys(match.casefold() for match in _FORMAT_RE.findall(statement))
        )
        provider_slugs = list(dict.fromkeys(provider_slugs))
        provider_can_create = any(
            any(
                marker in str(operation).casefold()
                for marker in (
                    "append",
                    "create",
                    "generate",
                    "post",
                    "publish",
                    "upload",
                    "upsert",
                )
            )
            for item in inventory
            if str(item.get("slug") or "") in provider_slugs
            for operation in item.get("allowed_operations") or []
        )
        requirements.append(
            AtomicRequirement(
                key=f"requirement_{len(requirements) + 1}",
                statement=statement,
                action=_internal_synthesis_action(
                    statement,
                    _find_action(statement),
                    provider_slugs,
                    format_hints,
                    provider_can_create,
                ),
                provider_slugs=provider_slugs,
                format_hints=format_hints,
                content_terms=_content_terms(statement, matched_aliases),
                constraint_terms=list(
                    dict.fromkeys(
                        token
                        for token in _WORD_RE.findall(statement.casefold())
                        if token in _EXPLICIT_CONSTRAINT_TERMS
                    )
                ),
            )
        )
    needs_source_grounding = bool(_SOURCE_EVIDENCE_RE.search(prompt)) and any(
        requirement.action in _SOURCE_CONSUMING_ACTIONS for requirement in requirements
    )
    if needs_source_grounding and not any(
        requirement.action == "read" for requirement in requirements
    ):
        all_aliases = {
            alias
            for _, aliases in inventory_aliases
            for alias in aliases
            if f" {alias} " in f" {_normalized_text(prompt)} "
        }
        requirements.insert(
            0,
            AtomicRequirement(
                key="requirement_1",
                statement=(
                    "Gather the requested source evidence before creating the deliverable: "
                    + " ".join(prompt.split())
                )[:1000],
                action="read",
                content_terms=_content_terms(prompt, all_aliases),
            ),
        )
        requirements = [
            requirement.model_copy(update={"key": f"requirement_{index}"})
            for index, requirement in enumerate(requirements, start=1)
        ]
    return requirements


def _operation_document(step: PlanStep, inventory_by_slug: dict[str, dict]) -> str:
    item = inventory_by_slug.get(step.tool_slug, {})
    contract = next(
        (
            value
            for value in item.get("operation_contracts") or []
            if value.get("name") == step.operation
        ),
        {},
    )
    return _normalized_text(
        " ".join(
            [
                step.tool_slug,
                step.operation,
                step.reason,
                step.expected_output,
                json.dumps(step.arguments, sort_keys=True, default=str),
                str(item.get("name") or ""),
                str(item.get("canonical_provider") or ""),
                str(contract.get("description") or ""),
                " ".join(str(value) for value in contract.get("capability_tags") or []),
            ]
        )
    )


def _action_compatible(action: RequirementAction, step: PlanStep, document: str) -> bool:
    operation = step.operation.casefold()
    scope = operation_scope(operation)
    if action == "outcome":
        return True
    if action == "synthesize":
        return True
    if action == "read":
        return scope == "read"
    markers = {
        "create": ("create", "generate", "make", "append", "produce", "upsert"),
        "export": ("export", "render", "download", "convert"),
        "store": ("upload", "save", "store", "copy", "create", "append"),
        "publish": ("publish", "post", "append", "upload", "create"),
        "send": ("send", "email", "notify", "message", "share", "post"),
        "update": ("update", "edit", "patch", "append", "upsert"),
        "delete": ("delete", "destroy", "purge", "revoke", "remove", "cancel"),
        "schedule": ("schedule", "book", "event create", "calendar create"),
    }[action]
    return any(marker in operation or marker in document for marker in markers)


def _result_reachable_steps(plan: WorkflowPlan) -> set[str]:
    by_key = {step.key: step for step in plan.steps}
    contract = plan.result_contract
    if contract is None:
        return set(by_key)
    roots = {
        contract.primary_step_key,
        contract.completion_step_key,
        contract.artifact_step_key,
        *contract.supporting_step_keys,
    }
    roots.discard(None)
    reachable: set[str] = set()
    pending = deque(str(value) for value in roots)
    while pending:
        key = pending.popleft()
        if key in reachable or key not in by_key:
            continue
        reachable.add(key)
        pending.extend(by_key[key].depends_on)
    return reachable


def _depends_transitively(plan: WorkflowPlan, step_key: str, dependency_key: str) -> bool:
    by_key = {step.key: step for step in plan.steps}
    if step_key not in by_key:
        return False
    pending = deque(by_key[step_key].depends_on)
    seen: set[str] = set()
    while pending:
        key = pending.popleft()
        if key == dependency_key:
            return True
        if key in seen or key not in by_key:
            continue
        seen.add(key)
        pending.extend(by_key[key].depends_on)
    return False


def prove_request_graph(
    prompt: str, plan: WorkflowPlan, inventory: list[dict]
) -> RequestGraphProof:
    requirements = derive_request_requirements(prompt, inventory)
    constraints = derive_request_constraints(prompt, inventory)
    inventory_by_slug = {str(item.get("slug") or ""): item for item in inventory}
    documents = {
        step.key: _operation_document(step, inventory_by_slug) for step in plan.steps
    }
    reachable = _result_reachable_steps(plan)
    evidence: list[RequirementEvidence] = []
    fixes: list[str] = []

    for constraint in constraints:
        violating_steps = [
            step.key
            for step in plan.steps
            if step.tool_slug in constraint.forbidden_provider_slugs
            or step.operation in constraint.forbidden_operations
        ]
        if violating_steps:
            fixes.append(
                f"{constraint.key} violates an explicit exclusion in steps "
                f"{', '.join(violating_steps)}: {constraint.statement}"
            )

    for requirement in requirements:
        action_steps = [
            step
            for step in plan.steps
            if _action_compatible(requirement.action, step, documents[step.key])
        ]
        provider_steps = [
            step for step in plan.steps if step.tool_slug in requirement.provider_slugs
        ]
        format_steps = [
            step
            for step in plan.steps
            if any(
                f" {format_hint} " in f" {documents[step.key]} "
                for format_hint in requirement.format_hints
            )
        ]
        semantic_steps = [
            step
            for step in plan.steps
            if set(requirement.content_terms).intersection(documents[step.key].split())
        ]

        if (
            requirement.action in {"synthesize", "outcome"}
            and not requirement.provider_slugs
        ):
            source_steps = provider_steps or semantic_steps or [
                step for step in plan.steps if step.key in reachable and not step.optional
            ]
            if source_steps:
                evidence.append(
                    RequirementEvidence(
                        requirement_key=requirement.key,
                        step_keys=[step.key for step in source_steps],
                        proof_kind="synthesis",
                    )
                )
                continue

        if not action_steps:
            fixes.append(
                f"{requirement.key} has no compatible {requirement.action} action: "
                f"{requirement.statement}"
            )
        if requirement.provider_slugs and not provider_steps:
            fixes.append(
                f"{requirement.key} omits the requested provider destination: "
                f"{requirement.statement}"
            )
        if requirement.format_hints and not format_steps:
            fixes.append(
                f"{requirement.key} omits the requested format "
                f"({', '.join(requirement.format_hints)}): {requirement.statement}"
            )

        compatible_semantic = [
            step for step in action_steps if step in semantic_steps
        ]
        if (
            requirement.content_terms
            and not compatible_semantic
            and not (requirement.provider_slugs and action_steps and provider_steps)
        ):
            fixes.append(
                f"{requirement.key} has no graph step grounded in its requested subject: "
                f"{requirement.statement}"
            )

        selected_action_steps = (
            compatible_semantic
            or [step for step in action_steps if step in provider_steps]
            or action_steps[:1]
        )
        selected_provider_steps = (
            [step for step in provider_steps if step in compatible_semantic]
            or [step for step in provider_steps if step in action_steps]
            or provider_steps[:1]
        )
        selected_format_steps = (
            [
                step
                for step in format_steps
                if step in selected_action_steps or step in selected_provider_steps
            ]
            or format_steps[:1]
        )
        proof_steps = list(
            dict.fromkeys(
                step.key
                for group in (
                    selected_action_steps,
                    selected_provider_steps,
                    selected_format_steps,
                )
                for step in group
            )
        )
        proof_document = " ".join(documents[key] for key in proof_steps)
        constraint_aliases = {
            "celsius": {"celsius", "metric"},
            "fahrenheit": {"fahrenheit", "imperial"},
        }
        proof_words = set(proof_document.split())
        missing_constraints = [
            term
            for term in requirement.constraint_terms
            if not proof_words.intersection(constraint_aliases.get(term, {term}))
        ]
        if missing_constraints:
            fixes.append(
                f"{requirement.key} drops explicit constraints "
                f"({', '.join(missing_constraints)}): {requirement.statement}"
            )
        if proof_steps and all(
            next(step for step in plan.steps if step.key == key).optional
            for key in proof_steps
        ):
            fixes.append(
                f"{requirement.key} is covered only by optional steps: {requirement.statement}"
            )
        unreachable = [key for key in proof_steps if key not in reachable]
        if unreachable:
            fixes.append(
                f"{requirement.key} is disconnected from the final result graph: "
                + ", ".join(unreachable)
            )

        # A composed request such as "export as PDF to Drive" needs both the
        # export action and the destination write, with data flowing between them.
        if (
            requirement.provider_slugs
            and action_steps
            and provider_steps
            and not any(
                action.key == provider.key
                or _depends_transitively(plan, provider.key, action.key)
                or _depends_transitively(plan, action.key, provider.key)
                for action in selected_action_steps
                for provider in selected_provider_steps
            )
        ):
            fixes.append(
                f"{requirement.key} has provider and action steps without a dependency path: "
                f"{requirement.statement}"
            )

        if proof_steps:
            evidence.append(
                RequirementEvidence(
                    requirement_key=requirement.key,
                    step_keys=proof_steps,
                )
            )

    if bool(_SOURCE_EVIDENCE_RE.search(prompt)):
        evidence_by_requirement = {
            item.requirement_key: item.step_keys for item in evidence
        }
        source_steps = list(
            dict.fromkeys(
                step_key
                for requirement in requirements
                if requirement.action == "read"
                for step_key in evidence_by_requirement.get(requirement.key, [])
            )
        )
        consuming_steps = list(
            dict.fromkeys(
                step_key
                for requirement in requirements
                if requirement.action in _SOURCE_CONSUMING_ACTIONS
                for step_key in evidence_by_requirement.get(requirement.key, [])
            )
        )
        if consuming_steps and not source_steps:
            fixes.append(
                "Requested source-backed deliverable has no verified read step for its evidence"
            )
        elif source_steps:
            disconnected_consumers = [
                consumer
                for consumer in consuming_steps
                if not any(
                    consumer == source
                    or _depends_transitively(plan, consumer, source)
                    for source in source_steps
                )
            ]
            if disconnected_consumers:
                fixes.append(
                    "Source-backed provider actions do not depend on the evidence reads: "
                    + ", ".join(disconnected_consumers)
                )

    return RequestGraphProof(
        requirements=requirements,
        constraints=constraints,
        evidence=evidence,
        fixes=list(dict.fromkeys(fixes)),
    )


def attach_request_graph_proof(
    prompt: str, plan: WorkflowPlan, inventory: list[dict]
) -> list[str]:
    proof = prove_request_graph(prompt, plan, inventory)
    if proof.fixes:
        return proof.fixes
    plan.planning_artifacts["request_contract"] = proof.model_dump(mode="json")
    return []


def persisted_request_contract_fixes(plan: WorkflowPlan) -> list[str]:
    """Reject repairs or reused plans that detach the previously proven contract."""
    contract = plan.planning_artifacts.get("request_contract")
    if not isinstance(contract, dict):
        return []
    requirements = {
        str(item.get("key") or "")
        for item in contract.get("requirements") or []
        if isinstance(item, dict)
    }
    evidence = {
        str(item.get("requirement_key") or ""): item
        for item in contract.get("evidence") or []
        if isinstance(item, dict)
    }
    known = {step.key: step for step in plan.steps}
    reachable = _result_reachable_steps(plan)
    fixes: list[str] = []
    for constraint in contract.get("constraints") or []:
        if not isinstance(constraint, dict):
            continue
        forbidden_providers = {
            str(value) for value in constraint.get("forbidden_provider_slugs") or []
        }
        forbidden_operations = {
            str(value) for value in constraint.get("forbidden_operations") or []
        }
        violating = [
            step.key
            for step in plan.steps
            if step.tool_slug in forbidden_providers
            or step.operation in forbidden_operations
        ]
        if violating:
            fixes.append(
                "Persisted request exclusion is violated by steps: "
                + ", ".join(violating)
            )
    for key in sorted(requirements):
        proof = evidence.get(key)
        if not proof:
            fixes.append(f"Persisted request contract has no evidence for {key}")
            continue
        step_keys = {str(value) for value in proof.get("step_keys") or []}
        if not step_keys:
            fixes.append(f"Persisted request contract has no graph source for {key}")
            continue
        missing = sorted(step_keys - set(known))
        if missing:
            fixes.append(
                f"Persisted request contract references missing steps for {key}: "
                + ", ".join(missing)
            )
        optional = sorted(
            step_key
            for step_key in step_keys.intersection(known)
            if known[step_key].optional
        )
        if optional and optional == sorted(step_keys):
            fixes.append(f"Persisted request contract is optional-only for {key}")
        disconnected = sorted(step_keys - reachable)
        if disconnected:
            fixes.append(
                f"Persisted request contract is disconnected for {key}: "
                + ", ".join(disconnected)
            )
    return fixes


def missing_runtime_requirement_evidence(
    plan: dict, artifacts: list[dict]
) -> list[str]:
    contract = (plan.get("planning_artifacts") or {}).get("request_contract") or {}
    evidence = contract.get("evidence") or []
    if not evidence:
        return []
    completed = {
        str(item.get("step_key") or "")
        for item in artifacts
        if item.get("critic", {}).get("action") == "accept"
    }
    missing: list[str] = []
    for item in evidence:
        required = {str(value) for value in item.get("step_keys") or []}
        if required and not required.issubset(completed):
            missing.append(str(item.get("requirement_key") or "requested outcome"))
    return missing
