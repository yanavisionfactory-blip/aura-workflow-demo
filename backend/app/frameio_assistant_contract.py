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


def require_supported_request(prompt, browser_review=False):
    explicit = re.search(r"frame[. ]?io(?:['’]s)?\s+(?:(?:own|native|in.product)\s+)?ai\s+assistant|frame[. ]?io.{0,35}(?:own|native)\s+ai", prompt, re.IGNORECASE)
    if explicit and not browser_review:
        raise FrameioAssistantUnavailable(UNAVAILABLE_MESSAGE)


def validate_native_assistant_plan(prompt, plan):
    from .frameio_browser_contract import OPERATION as BROWSER_OPERATION
    browser_steps = [step for step in plan.steps if step.operation == BROWSER_OPERATION]
    # Explicit native-AI requests must never select the AURA analysis operation
    # or install a substitute fallback, even when a browser is connected.
    only_native = bool(browser_steps) and all(
        step.operation in {BROWSER_OPERATION, "frameio.file.get"}
        and not getattr(step, "fallback_operation", None) for step in plan.steps
    )
    require_supported_request(prompt, browser_review=only_native)
    if any(OPERATION in {step.operation, getattr(step, "fallback_operation", None)} for step in plan.steps):
        raise FrameioAssistantUnavailable(UNAVAILABLE_MESSAGE)
