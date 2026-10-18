"""Opt-in agency recipe: fixed orchestration, live providers, reviewed content.

Destination identifiers are supplied in the request from previously verified
outputs. No customer, account, site, or document is embedded in this recipe.
"""

import json
import logging

from pydantic import BaseModel, ConfigDict, Field

from .schemas import WorkflowPlan

logger = logging.getLogger(__name__)
MARKER = "AURA_AGENCY_RECIPE_CONFIG:"


class ArticleTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    post_id: int = Field(gt=0)
    location: str = Field(min_length=1, max_length=80)
    min_words: int = Field(ge=300, le=2000)
    max_words: int = Field(ge=300, le=2500)


class AgencyRecipeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client: str = Field(min_length=2, max_length=150)
    intake_document: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    prior_research_document: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    prior_report_document: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    completed_research_document: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")
    account_id: str = Field(pattern=r"^\d+$")
    geo_target: str = Field(pattern=r"^geoTargetConstants/\d+$")
    language: str = Field(pattern=r"^languageConstants/\d+$")
    seed_keywords: list[str] = Field(min_length=1, max_length=4)
    draft_search: str = Field(min_length=2, max_length=150)
    articles: list[ArticleTarget] = Field(min_length=1, max_length=3)
    handoff_issue: str = Field(pattern=r"^[A-Z][A-Z0-9_]*-\d+$")


async def agency_workflow_recipe(prompt, inventory, manifests):
    """Compile only an explicitly selected recipe, never override a revision."""
    if MARKER not in prompt or "The user reviewed the proposed workflow" in prompt:
        return None
    config_text = prompt.rsplit(MARKER, 1)[1].strip()
    config = AgencyRecipeConfig.model_validate(json.loads(config_text))
    if len({item.post_id for item in config.articles}) != len(config.articles):
        raise ValueError("Agency recipe article targets must be distinct")
    if any(item.min_words > item.max_words for item in config.articles):
        raise ValueError("Agency recipe word count range is invalid")

    def owner(operation):
        matches = [item["slug"] for item in inventory
                   if operation in item.get("allowed_operations", [])]
        if len(matches) != 1:
            raise ValueError(f"Agency recipe requires one verified owner for {operation}")
        return matches[0]

    steps = []

    def add(key, operation, arguments, reason, *, after=(), write=False, optional=False):
        steps.append({
            "key": key, "agent": "Agency Workflow Agent", "tool_slug": owner(operation),
            "operation": operation, "arguments": arguments, "reason": reason,
            "expected_output": reason, "depends_on": list(after),
            "consequential": write, "optional": optional,
        })

    read_doc = "google-docs.get-document"
    create_doc = "google-docs.create-document"
    for key, document, reason in (
        ("intake", config.intake_document, "Read and reuse the completed intake, questionnaire and unsent email template."),
        ("prior_research", config.prior_research_document, "Read prior research as dated background, not fresh metrics."),
        ("prior_report", config.prior_report_document, "Read the earlier report and distinguish reused results."),
    ):
        add(key, read_doc, {"documentId": document}, reason)
    add("ads_accounts", "google-ads.list-account-id-options", {},
        "Read available accounts; use the previously verified account selected in this request.", after=["intake"])
    add("keyword_ideas", "google-ads.generate-keyword-ideas", {
        "accountId": config.account_id,
        "additionalFields": {
            "keywordSeed": {"keywords": config.seed_keywords},
            "geoTargetConstants": [config.geo_target], "language": config.language,
            "keywordPlanNetwork": "GOOGLE_SEARCH", "includeAdultKeywords": False, "pageSize": 20,
        },
    }, "Retrieve fresh, real Keyword Planner ideas with the verified location and language.", after=["ads_accounts", "prior_research"])

    # The connected MCP service owns its operation names and input schema. Pick
    # an actual keyword-suggestion read, not a title generator or a made-up API.
    candidates = []
    for item in ([] if config.completed_research_document else inventory):
        if "ubersuggest" not in (item["slug"] + " " + item.get("name", "")).lower():
            continue
        for cap in manifests.get(item["slug"], {}).get("capabilities", []):
            name = cap.get("name", "")
            text = (name + " " + cap.get("description", "")).lower()
            if name not in item.get("allowed_operations", []) or "keyword" not in text:
                continue
            if any(term in name.lower() for term in ("title", "article", "delete", "create", "update")):
                continue
            # External MCP contracts can conservatively mark every operation
            # for approval. Keep that review boundary instead of hiding an
            # otherwise available keyword read from the recipe.
            score = sum(term in name.lower() for term in ("keyword", "suggest", "related", "idea"))
            candidates.append((score, name, item["slug"], cap))
    from .agent_runtime import materialize_action_arguments, normalize_plan_graph

    if candidates:
        _, support_operation, support_slug, support_cap = min(candidates, key=lambda x: (-x[0], x[1]))
        logger.info("Agency recipe keyword support operation=%s schema_fields=%s", support_operation,
                    sorted(support_cap.get("input_schema", {}).get("properties", {})))
        support_args = await materialize_action_arguments(
            "Prepare arguments for keyword suggestions for " + "; ".join(config.seed_keywords)
            + ". Use US English. Use only supported targeting. Do not invent identifiers or results.",
            {"tool_slug": support_slug, "operation": support_operation, "arguments": {},
             "reason": "Supporting real US keyword suggestions; city targeting only if supported."},
            {"steps": {}}, capability_manifest=manifests[support_slug],
        )
        add("keyword_support", support_operation, support_args,
            "Retrieve real Ubersuggest supporting keyword suggestions; record actual geography.", after=["keyword_ideas"])
    else:
        add("keyword_support", read_doc, {"documentId": config.prior_research_document},
            "Reuse the prior real Ubersuggest findings from the research document. Explicitly disclose reuse "
            "and that no fresh Ubersuggest operation was available; do not invent new provider results.", after=["keyword_ideas"])
    add("research", create_doc, {
        "title": f"{config.client} — Fresh keyword research",
        "content": "Content will be written from the completed keyword reads. Include up to 20 real ideas, "
        "metrics and units, actual targeting and retrieval time, sources, intent clusters and an evidence-based "
        "primary keyword choice. Label US-level supporting data and reused background. Do not sum variants or "
        "equate advertising competition with organic difficulty. Exclude private account identifiers.",
    }, "Compose and save the complete sourced research document for review.", after=["keyword_support"], write=True)
    add("research_read", read_doc, {"documentId": "{{steps.research.documentId}}"},
        "Read the saved research body and verify real metrics and selected keyword.", after=["research"])
    add("drafts", "wordpress-org.search-posts", {"search": config.draft_search, "statuses": ["draft"]},
        "Read the existing full draft bodies before editing; do not duplicate posts.", after=["research_read"])
    writes = []
    for index, article in enumerate(config.articles):
        key = f"article_{index + 1}"
        add(key, "wordpress-org.update-post", {
            "post": str(article.post_id), "status": "draft",
            "content": f"Content will be written for {article.location}, {article.min_words}–{article.max_words} "
            "words. Reuse the matching original body and improve it using accepted fresh research and the client "
            "brief. Return the COMPLETE HTML body and accurate title for review, with useful distinct local wording, "
            "headings, homeowner FAQs and a clearly labelled demonstration CTA. No invented business claims or "
            "contact details. Keep unpublished. Preserve the target post ID and draft status.",
        }, f"Prepare and review the full {article.location} article, then update existing draft {article.post_id}.",
            after=["drafts", "research_read"], write=True)
        writes.append(key)
    add("drafts_verified", "wordpress-org.search-posts", {"search": config.draft_search, "statuses": ["draft"]},
        "Verify all saved target IDs, titles, complete bodies, word counts and draft status.", after=writes)
    seo_reads = []
    for index, article in enumerate(config.articles):
        suffix = str(index + 1)
        analysis = "analysis_" + suffix
        current = "seo_before_" + suffix
        update = "seo_update_" + suffix
        readback = "seo_verified_" + suffix
        add(analysis, "rankmath.post_analysis.get", {"post_id": article.post_id},
            f"Inspect saved {article.location} content structure and analysis inputs; do not claim a new score.", after=["drafts_verified"])
        add(current, "rankmath.post_seo.get", {"post_id": article.post_id},
            f"Read the current {article.location} SEO metadata.", after=[analysis])
        add(update, "rankmath.post_seo.update", {
            "post_id": article.post_id, "title": "SEO title to be written from the saved article",
            "description": "Description will be written accurately from the saved article and selected keyword. "
            "Return complete proposed SEO title, meta description and location-appropriate focus keyword for review. "
            "No invented claims. Preserve the target post ID.", "focus_keyword": "Keyword to be written from research",
        }, f"Review and save all three RankMath metadata fields on {article.location} draft {article.post_id}.",
            after=[current, "research_read"], write=True)
        add(readback, "rankmath.post_seo.get", {"post_id": article.post_id},
            f"Verify the exact saved {article.location} SEO title, description and focus keyword.", after=[update])
        seo_reads.append(readback)
    add("image_stats", "imagify.stats.get", {}, "Read actual Imagify totals without inventing savings.", after=seo_reads)
    add("media", "wordpress-org.list-media-options", {"page": 0},
        "Discover actual demo media IDs. If empty, optimization is not executed; never invent an image ID.", after=["image_stats"])
    add("handoff_before", "jira.issue.get", {"issue_id_or_key": config.handoff_issue},
        "Read and reuse the existing handoff issue and its actual URL.", after=["media"])
    add("report", create_doc, {
        "title": f"{config.client} — Verified agency workflow results",
        "content": "Content will be written as a complete agency review report from accepted results. Include the "
        "brief, intake link and reuse, fresh sourced keyword table and research link, all three actual draft links "
        "and verified word counts/status, per-article on-page findings, proposed versus verified saved RankMath "
        "metadata, real Imagify totals and discovered media, failed actions and outstanding work. Crawl, backlinks, "
        "rankings, traffic and leads are not measured unless supported by exact-site evidence. Include the existing "
        "Jira issue URL without prematurely claiming its later update, and three agency feedback questions. "
        "Clearly disclose that AURA composed content and location variants; do not claim unavailable vendors ran. "
        "No credentials, account identifiers or access codes. Use complete polished Markdown with clickable links.",
    }, "Compose and review the final report from real, verified outputs.", after=["handoff_before", *seo_reads], write=True)
    add("report_read", read_doc, {"documentId": "{{steps.report.documentId}}"},
        "Read and verify the saved final report body and links.", after=["report"])
    add("handoff_update", "jira.issue.update", {
        "issue_id_or_key": config.handoff_issue,
        "fields": {"description": "{{steps.report_read.textContent}}"},
    }, "Update the existing handoff with the verified report, actual output links and remaining review actions.",
        after=["report_read"], write=True)
    add("handoff_verified", "jira.issue.get", {"issue_id_or_key": config.handoff_issue},
        "Verify the existing Jira handoff now contains the saved output links and review actions.", after=["handoff_update"])
    add("final_report_verified", read_doc, {"documentId": "{{steps.report.documentId}}"},
        "Verify the final deliverable after team handoff and report executed, reused and outstanding work.", after=["handoff_verified"])
    if config.completed_research_document:
        completed = {"ads_accounts", "keyword_ideas", "keyword_support", "research", "research_read"}
        steps = [step for step in steps if step["key"] not in completed]
        for step in steps:
            step["depends_on"] = [key for key in step["depends_on"] if key not in completed or key == "research_read"]
        steps.insert(3, {
            "key": "research_read", "agent": "Agency Workflow Agent", "tool_slug": owner(read_doc),
            "operation": read_doc, "arguments": {"documentId": config.completed_research_document},
            "reason": "Read and reuse the completed, verified live research. Keyword calls and the research write "
            "already completed in the previous run; do not repeat them or claim new retrievals.",
            "expected_output": "Verified saved research body and source links from the completed stages.",
            "depends_on": ["intake"],
        })
    plan = WorkflowPlan.model_validate({
        "name": f"Agency SEO workflow — {config.client}" + (" — Resume" if config.completed_research_document else ""),
        "interpretation": ("Resume from the verified completed research without repeating successful keyword calls "
                           "or research writes. " if config.completed_research_document else "")
        + "Run the selected agency recipe through live connected providers with full write review and saved-result readbacks.",
        "steps": steps,
    })
    plan.planning_artifacts = {"planner_recovery_mode": "audited_agency_recipe",
                               "recipe_version": 1, "source": "explicit_request_configuration",
                               "resumed_after_research": bool(config.completed_research_document)}
    return normalize_plan_graph(plan)
