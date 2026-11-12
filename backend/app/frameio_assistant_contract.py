"""Keep unsupported native-assistant requests out of executable workflows."""
import re

from .plan_preflight import PlanPreflightError

OPERATION = "frameio.assistant.review"
UNAVAILABLE_MESSAGE = (
    "Frame.io's own AI Assistant is not available through AURA's connected tool. "
    "The Frame.io connection does not expose that assistant. "
    "Signing in again will not add this capability."
)


class FrameioAssistantUnavailable(PlanPreflightError):
    public_message = UNAVAILABLE_MESSAGE


def require_supported_request(prompt):
    explicit = re.search(r"frame[. ]?io(?:['’]s)?\s+(?:(?:own|native|in.product)\s+)?ai\s+assistant|frame[. ]?io.{0,35}(?:own|native)\s+ai", prompt, re.IGNORECASE)
    if explicit:
        raise FrameioAssistantUnavailable(UNAVAILABLE_MESSAGE)


def validate_native_assistant_plan(prompt, plan):
    require_supported_request(prompt)
    if any(OPERATION in {step.operation, getattr(step, "fallback_operation", None)} for step in plan.steps):
        raise FrameioAssistantUnavailable(UNAVAILABLE_MESSAGE)
