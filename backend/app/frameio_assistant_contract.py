"""Prevent an explicit native assistant request being silently substituted."""
import re


def validate_native_assistant_plan(prompt, plan):
    explicit = re.search(r"frame[. ]?io(?:['’]s)?\s+(?:(?:own|native|in.product)\s+)?ai\s+assistant|frame[. ]?io.{0,35}(?:own|native)\s+ai", prompt, re.IGNORECASE)
    if any(step.operation == "frameio.assistant.review" and step.fallback_operation for step in plan.steps):
        raise ValueError("Native Frame.io assistant reviews must not fall back to another analysis engine")
    if not explicit:
        return
    operations = {step.operation for step in plan.steps}
    if "frameio.assistant.review" not in operations or operations & {"frameio.video.review", "intelligence.video.review"}:
        raise ValueError("The user requested Frame.io's own AI Assistant. Use frameio.assistant.review; do not substitute AURA Intelligence or a composed report.")
