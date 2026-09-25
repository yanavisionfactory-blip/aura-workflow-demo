"""Deterministic coverage for explicitly requested consequential operations."""

from __future__ import annotations

import re


def requested_external_operations(prompt: str) -> set[str]:
    """Recognize explicit Gmail delivery, without treating an email draft as a send."""
    text = prompt.casefold()
    if re.search(r"\b(?:do not|don't|never|without)\s+(?:send|email|mail|deliver)\b", text):
        return set()
    send_to_mail = re.search(
        r"\b(?:send|deliver|forward)\b[^.!?\n]{0,140}\b(?:email|e-mail|gmail)\b",
        text,
    )
    mail_to_send = re.search(
        r"\b(?:gmail|e-mail|email)\b[^.!?\n]{0,90}\b(?:send|deliver)\b",
        text,
    )
    email_as_verb = re.search(r"\bemail\s+(?:me|us|them|it|this|the|a|an)\b", text)
    return {"gmail.send"} if send_to_mail or mail_to_send or email_as_verb else set()


def missing_requested_operations(prompt: str, operations: set[str]) -> set[str]:
    return requested_external_operations(prompt) - operations


def validate_requested_operations(prompt: str, plan, available: set[str]) -> None:
    required = requested_external_operations(prompt) & available
    missing = required - {step.operation for step in plan.steps}
    if missing:
        # This is fed into the model's bounded repair pass, then into the
        # durable Recovery Engineer if the model still omits the action.
        raise ValueError(
            "Requested external action is absent from the executable plan: "
            + ", ".join(sorted(missing))
            + ". Add the exact approved operation with its real inputs and dependencies."
        )
