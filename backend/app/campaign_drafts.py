"""Bounded campaign production over native tools, with no send or activation step."""
import html
import json
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import WorkflowPlan

DRAFT_PREFIX = "AURA_CAMPAIGN_DRAFT_V1\n"


class ExactFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def literal_text(cls, value):
        if isinstance(value, str) and (not value.strip() or "{{" in value or "}}" in value):
            raise ValueError("Supply literal nonempty campaign fields, not workflow references")
        return value


class DraftCampaignFields(ExactFields):
    audience_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    audience_name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=150)
    preview_text: str = Field(min_length=1, max_length=150)
    from_name: str = Field(min_length=1, max_length=100)
    reply_to: str = Field(min_length=3, max_length=254)

    @field_validator("reply_to")
    @classmethod
    def email(cls, value):
        if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", value):
            raise ValueError("Supply the client's reply email address")
        return value


class CampaignDraftRequest(DraftCampaignFields):
    client: str = Field(min_length=1, max_length=100)
    brief_reference: str = Field(min_length=1, max_length=500)
    headline: str = Field(min_length=1, max_length=90)
    body: str = Field(min_length=1, max_length=4000)
    cta_label: str = Field(min_length=1, max_length=90)
    cta_url: str = Field(min_length=1, max_length=2000)
    create_graphic: bool = False
    graphic_line: str | None = Field(default=None, min_length=1, max_length=90)

    @field_validator("cta_url")
    @classmethod
    def https_destination(cls, value):
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or any(ch.isspace() for ch in value)):
            raise ValueError("Supply an HTTPS destination without credentials or whitespace")
        return value

    @model_validator(mode="after")
    def graphic_copy(self):
        if self.create_graphic and not self.graphic_line:
            raise ValueError("Provide a short approved line for the Canva graphic")
        return self


class CampaignContentFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    expected_list_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    html: str = Field(min_length=1, max_length=50000)
    plain_text: str = Field(min_length=1, max_length=10000)


def email_content(fields: CampaignDraftRequest) -> dict:
    """Escape supplied copy; retain the provider's address and unsubscribe merge tags."""
    esc = html.escape
    paragraphs = "".join(f"<p>{esc(line)}</p>" for line in fields.body.split("\n\n") if line)
    body = (
        '<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{esc(fields.subject)}</title></head>'
        '<body style="margin:0;background:#ffffff;color:#17202a;font:16px/1.6 Arial,sans-serif">'
        '<div lang="en" dir="ltr" style="max-width:600px;margin:0 auto;padding:24px">'
        f'<h1 style="font-size:26px">{esc(fields.headline)}</h1>{paragraphs}'
        f'<p><a style="color:#174e78" href="{esc(fields.cta_url, quote=True)}">'
        f'{esc(fields.cta_label)}</a></p>'
        '<p style="font-size:14px">*|LIST:ADDRESS|*<br>'
        '<a style="color:#174e78" href="*|UNSUB|*">Unsubscribe from these emails</a></p>'
        '</div></body></html>'
    )
    plain = (f"{fields.headline}\n\n{fields.body}\n\n{fields.cta_label}: {fields.cta_url}"
             "\n\n*|LIST:ADDRESS|*\nUnsubscribe: *|UNSUB|*")
    return {"html": body, "plain_text": plain}


def campaign_draft_recipe(prompt: str, inventory: list[dict]) -> WorkflowPlan | None:
    if not prompt.startswith(DRAFT_PREFIX):
        return None
    # Never reapply the literal first-draft recipe over reviewed revisions.
    if "The user reviewed the proposed workflow and requested this change:" in prompt:
        return None
    fields = CampaignDraftRequest.model_validate(json.loads(prompt[len(DRAFT_PREFIX):]))

    def require(slug, operations):
        matches = [item for item in inventory if item.get("slug") == slug
                   and item.get("connected")
                   and set(operations) <= set(item.get("allowed_operations") or [])]
        if len(matches) != 1:
            raise ValueError(f"Connect {slug} with the campaign draft and verification capabilities")

    require("mailchimp", {"mailchimp.audience.get", "mailchimp.campaign.draft.create",
                          "mailchimp.campaign.get", "mailchimp.campaign.content.set",
                          "mailchimp.campaign.content.get"})
    if fields.create_graphic:
        require("canva", {"canva.presentation.create", "canva.import.get"})

    steps = [{
        "key": "audience", "agent": "Campaign Production Agent", "tool_slug": "mailchimp",
        "operation": "mailchimp.audience.get",
        "arguments": {"list_id": fields.audience_id, "expected_name": fields.audience_name},
        "reason": "Verify the exact client audience by ID and name before creating anything.",
        "expected_output": "Actual Mailchimp audience identity and metadata.",
    }]
    if fields.create_graphic:
        steps.append({
            "key": "graphic", "agent": "Campaign Production Agent", "tool_slug": "canva",
            "operation": "canva.presentation.create",
            "arguments": {"title": fields.client, "subtitle": fields.title,
                          "layout": "creative", "canvas": "square",
                          "phases": [{"period": "Draft for review", "title": fields.headline,
                                      "items": [fields.graphic_line, fields.cta_label]}]},
            "reason": "Create an editable campaign graphic from the exact supplied copy.",
            "expected_output": "Populated Canva design and verified import receipt.",
            "consequential": True, "depends_on": ["audience"],
        })
    steps.extend([{
        "key": "campaign", "agent": "Campaign Production Agent", "tool_slug": "mailchimp",
        "operation": "mailchimp.campaign.draft.create",
        "arguments": fields.model_dump(include=set(DraftCampaignFields.model_fields)),
        "reason": "Create the reviewed regular email campaign as an unsent Mailchimp draft.",
        "expected_output": "Campaign ID, selected audience, exact settings and unsent status.",
        "consequential": True, "depends_on": [steps[-1]["key"]],
    }, {
        "key": "content", "agent": "Campaign Production Agent", "tool_slug": "mailchimp",
        "operation": "mailchimp.campaign.content.set",
        "arguments": {"campaign_id": "{{steps.campaign.id}}",
                      "expected_list_id": fields.audience_id, **email_content(fields)},
        "reason": "Save the reviewed HTML and plain text, then verify content, audience and unsent status.",
        "expected_output": "Exact saved content and matching draft-state readbacks; no send.",
        "consequential": True, "depends_on": ["campaign"],
    }])
    result_contract = {"primary_step_key": "content", "completion_step_key": "content",
                       "supporting_step_keys": [step["key"] for step in steps[:-1]]}
    plan = WorkflowPlan.model_validate({
        "name": f"Campaign production — {fields.client}",
        "interpretation": "Verify the selected audience and save a complete unsent email campaign"
                          + (" plus an editable Canva graphic." if fields.create_graphic else ".")
                          + " Review each external write before execution. No send or schedule step.",
        "steps": steps, "result_contract": result_contract,
        "planning_artifacts": {
            "planner_recovery_mode": "audited_campaign_draft_v1",
            "brief_reference": fields.brief_reference,
            "input_provenance": "user_supplied_copy_and_account_mapping",
            "objective_spec": {
                "goal": "Prepare actual campaign drafts in the selected client tools.",
                "deliverables": ["Unsent Mailchimp campaign with complete content"]
                                + (["Editable Canva graphic"] if fields.create_graphic else []),
                "constraints": ["No sends, scheduling, live ads or budget changes",
                                "Use the supplied client audience and copy only",
                                "Review every write and verify its saved result"],
                "success_metrics": ["Campaign content, audience and unsent status match readbacks"],
                "required_inputs": [],
            },
        },
    })
    from .agent_runtime import normalize_plan_graph
    return normalize_plan_graph(plan)
