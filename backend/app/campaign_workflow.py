"""Explicit campaign preparation recipe over released reads and native reports.

The caller supplies identifiers and scenario evidence. This compiler supplies
no client data, provider results, approvals, or publishing capabilities.
"""
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .reports import ReportSource
from .schemas import WorkflowPlan

CAMPAIGN_PREFIX = "AURA_CAMPAIGN_V1\n"
ReadOperation = Literal[
    "google-docs.get-document", "google-drive.list-files",
    "google-ads.list-account-id-options", "google-ads.generate-keyword-ideas",
    "facebook-pages.list-posts",
    "website.source.inspect", "web.page.read", "web.search",
]


class CampaignRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    operation: ReadOperation
    arguments: dict[str, Any]
    title: str = Field(min_length=1, max_length=200)
    depends_on: list[str] = Field(default_factory=list, max_length=8)


class CampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=10_000)
    reads: list[CampaignRead] = Field(min_length=1, max_length=8)
    sources: list[ReportSource] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def distinct_keys(self):
        keys = [read.key for read in self.reads]
        ids = [source.id for source in self.sources]
        if len(set(keys + ids + ["campaign_report"])) != len(keys + ids) + 1:
            raise ValueError("Campaign read keys and source IDs must be distinct")
        return self


def campaign_workflow_recipe(prompt: str, inventory: list[dict]) -> WorkflowPlan | None:
    if not prompt.startswith(CAMPAIGN_PREFIX):
        return None
    request = CampaignRequest.model_validate(json.loads(prompt[len(CAMPAIGN_PREFIX):]))

    def owner(operation):
        matches = [item["slug"] for item in inventory
                   if item.get("connected") and operation in item.get("allowed_operations", [])]
        if len(matches) != 1:
            raise ValueError(f"Campaign recipe requires one connected owner for {operation}")
        return matches[0]

    steps = []
    sources = [source.model_dump() for source in request.sources]
    for read in request.reads:
        steps.append({
            "key": read.key, "agent": "Campaign Preparation Agent",
            "tool_slug": owner(read.operation), "operation": read.operation,
            "arguments": read.arguments, "depends_on": read.depends_on,
            "reason": read.title,
            "expected_output": "Actual read receipt; preserve empty results and provider errors.",
        })
        path = "textContent" if read.operation == "google-docs.get-document" else "output"
        sources.append({"id": read.key, "title": read.title,
                        "content": "{{steps." + read.key + "." + path + "}}"})
    steps.append({
        "key": "campaign_report", "agent": "Campaign Report Analyst",
        "tool_slug": owner("report.compose"), "operation": "report.compose",
        "arguments": {
            "title": request.title, "instructions": request.instructions,
            "sources": sources, "synthetic": False,
        },
        "depends_on": [read.key for read in request.reads],
        "reason": "Prepare the complete unpublished campaign package inside AURA from saved read evidence.",
        "expected_output": "Full draft campaign report, source evidence and explicit manual implementation gaps.",
    })
    # Normal compilation, preflight, grants, approvals and runtime verification
    # still apply. In particular, conservative provider approval flags remain.
    from .agent_runtime import normalize_plan_graph

    return normalize_plan_graph(WorkflowPlan.model_validate({
        "name": request.title,
        "interpretation": "Run the explicitly configured provider reads and compose an unpublished native campaign review.",
        "steps": steps,
        "planning_artifacts": {"planner_recovery_mode": "audited_campaign_recipe", "recipe_version": 1},
    }))
