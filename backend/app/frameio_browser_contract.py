"""Contract for an attended Frame.io native-assistant browser execution.

This is not a Frame.io API endpoint. An authenticated browser agent observes
the native UI and returns its response to the approved AURA run.
"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

OPERATION = "frameio.assistant.browser_review"
WAIT_SECONDS = 600
SESSION_SECONDS = 900
OWNER_PREFIX = "webmcp:"
NOT_CONNECTED = (
    "An active browser executor with Frame.io AI Assistant open is required. "
    "The existing Frame.io OAuth connection remains connected. "
    "This review cannot run unattended or use AURA Intelligence as a substitute."
)


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: UUID
    project_id: UUID
    file_id: UUID

    @property
    def url(self):
        return f"https://app.frame.io/project/{self.project_id}/view/{self.file_id}"


class ReviewRequest(Target):
    browser_session_id: UUID
    instructions: str = Field(min_length=20, max_length=6000)


class BrowserResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation_id: UUID
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_url: str = Field(max_length=500)
    user_message_id: str = Field(min_length=1, max_length=200)
    assistant_message_id: str = Field(min_length=1, max_length=200)
    submitted_prompt: str = Field(min_length=20, max_length=10000)
    response_markdown: str = Field(min_length=80, max_length=100000)
    analysis_events: list[str] = Field(min_length=1, max_length=20)
    audio_status: str = Field(pattern=r"^(reviewed|unassessed|absent)$")
    limitations: list[str] = Field(min_length=1, max_length=30)


def review_plan(prompt, inputs, inventory):
    raw = (inputs or {}).get("frameio_browser_review")
    if raw is None:
        return None
    from .plan_preflight import PlanPreflightError
    from .schemas import PlanStep, WorkflowPlan

    args = ReviewRequest.model_validate(raw)
    if not any(item.get("slug") == "frameio" and OPERATION in
               item.get("allowed_operations", []) for item in inventory):
        raise PlanPreflightError("The connected Frame.io account lacks the browser-review operation.")
    return WorkflowPlan(
        name="Frame.io AI Assistant video review",
        interpretation=prompt,
        steps=[PlanStep(
            key="frameio_native_review", agent="Frame.io AI Assistant", tool_slug="frameio",
            operation=OPERATION, arguments=args.model_dump(mode="json"),
            reason="Submit the video and prompt to Frame.io's own AI Assistant through an active browser executor.",
            expected_output="Frame.io's original chronological review, timestamps, corrections and disclosed limitations.",
        )],
        planning_artifacts={"execution_mode": "attended_browser_agent", "analysis_provider": "frameio_ai_assistant"},
    )
