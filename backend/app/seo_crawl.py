"""Deterministic review of user-supplied crawler exports; never crawls a website."""
import base64
import csv
import hashlib
import io
import re
from collections import Counter
from urllib.parse import unquote_to_bytes, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .schemas import WorkflowPlan

CRAWL_REQUEST = re.compile(
    r"^Analyze the attached Screaming Frog crawl exports for (https://[^\s]+) inside AURA\.",
    re.IGNORECASE,
)


class CrawlDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=500)
    file_url: str = Field(min_length=1, max_length=8_000_000)


class CrawlReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    website: str = Field(min_length=8, max_length=2000, json_schema_extra={"format": "uri"})
    documents: list[CrawlDocument] = Field(min_length=1, max_length=8)

    @field_validator("website")
    @classmethod
    def website_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Confirm a public HTTPS client website")
        return value


def comparison_url(value):
    """Keep path case, queries and trailing slashes; drop fragments only."""
    parsed = urlsplit(value.strip())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/",
                       parsed.query, ""))


def _number(row, field):
    try:
        return float(row.get(field, "") or 0)
    except ValueError:
        return 0


def analyze_crawl(arguments: dict) -> dict:
    request = CrawlReviewRequest.model_validate(arguments)
    files, seen, internal, edge_rows = [], {}, [], []
    target = urlsplit(request.website).hostname.lower()
    warnings = []
    for document in request.documents:
        if not document.file_url.startswith("data:") or "," not in document.file_url:
            raise ValueError("Crawl exports must be uploaded CSV files, not remote URLs")
        metadata, encoded = document.file_url.split(",", 1)
        try:
            raw = (base64.b64decode(encoded, validate=True) if ";base64" in metadata.lower()
                   else unquote_to_bytes(encoded))
            text = raw.decode("utf-8-sig")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Upload a UTF-8 CSV export") from exc
        if len(raw) > 6_000_000:
            raise ValueError("Each crawl CSV must be smaller than 6 MB")
        reader = csv.DictReader(io.StringIO(text))
        fields = reader.fieldnames or []
        if len(fields) > 300:
            raise ValueError("Crawl CSV has more than 300 columns")
        rows = []
        for index, row in enumerate(reader, 2):
            if index > 50_001:
                raise ValueError("Crawl CSV has more than 50,000 rows")
            rows.append({**row, "_csv_row": index, "_file": document.name})
        digest = hashlib.sha256(raw).hexdigest()
        duplicate = seen.get(digest)
        kind = ("internal_url_inventory" if {"Address", "Status Code"} <= set(fields)
                else "link_edges" if {"Source", "Destination"} <= set(fields)
                else "unsupported")
        files.append({"filename": document.name, "sha256": digest, "rows": len(rows),
                      "columns": len(fields), "kind": kind, "duplicate_of": duplicate})
        if duplicate:
            warnings.append(f"{document.name} is byte-identical to {duplicate}; counted once.")
            continue
        seen[digest] = document.name
        if kind == "internal_url_inventory":
            # Keep the richest inventory. URL tab exports of the same crawl
            # remain documented corroboration, not additional crawl records.
            if not internal or len(fields) > len(internal[0]) - 2:
                internal = rows
            if "inlink" in document.name.lower():
                warnings.append(f"{document.name} contains URL rows, not source/destination links.")
        elif kind == "link_edges":
            edge_rows.extend(rows)
        else:
            warnings.append(f"{document.name} has no supported URL or link-edge header schema.")
    if not internal:
        raise ValueError("No Internal All URL inventory found in the attached exports")
    foreign = [row["Address"] for row in internal
               if urlsplit(row.get("Address", "")).hostname != target]
    if foreign:
        raise ValueError("The inventory contains a different host; confirm the exact client website")
    by_url = {comparison_url(row["Address"]): row for row in internal}
    if len(by_url) != len(internal):
        warnings.append("Repeated comparison URLs exist; inspect the preserved source row numbers.")
    html = [row for row in internal if row.get("Status Code") == "200"
            and "text/html" in row.get("Content Type", "").lower()]
    canonical_conflicts = []
    for row in html:
        canonical = row.get("Canonical Link Element 1", "").strip()
        alternate = by_url.get(comparison_url(canonical)) if canonical else None
        if (alternate and alternate.get("Status Code", "").startswith("3")
                and comparison_url(alternate.get("Redirect URL", ""))
                == comparison_url(row["Address"])):
            canonical_conflicts.append({"url": row["Address"], "csv_row": row["_csv_row"],
                                       "canonical": canonical, "canonical_csv_row": alternate["_csv_row"],
                                       "canonical_status": alternate["Status Code"],
                                       "redirect_to": alternate.get("Redirect URL", "")})
    redirects = [{"url": row["Address"], "csv_row": row["_csv_row"],
                  "status": row["Status Code"], "redirect_to": row.get("Redirect URL", ""),
                  "inlinks": row.get("Inlinks", ""), "unique_inlinks": row.get("Unique Inlinks", "")}
                 for row in internal if row.get("Status Code", "").startswith("3")]
    snippets = [{"url": row["Address"], "csv_row": row["_csv_row"],
                 "title_pixels": row.get("Title 1 Pixel Width", ""),
                 "description_pixels": row.get("Meta Description 1 Pixel Width", ""),
                 "missing_description": not bool(row.get("Meta Description 1", "").strip())}
                for row in html if (_number(row, "Title 1 Pixel Width") > 600
                                    or _number(row, "Meta Description 1 Pixel Width") > 1050
                                    or not row.get("Meta Description 1", "").strip())]
    timestamps = sorted({row.get("Crawl Timestamp") for row in internal
                         if row.get("Crawl Timestamp")})
    if not edge_rows:
        warnings.append("Detailed link edges are missing. Aggregate Inlinks are occurrences, "
                        "not unique source pages; orphan pages cannot be inferred.")
    checks = [
        {"id": "T01", "group": "Technical SEO", "priority": "P1", "state": "Observed",
         "title": "Resolve canonical URLs that redirect back to the declaring 200 URL",
         "affected": canonical_conflicts, "fix": "Confirm the preferred URL policy, then align "
         "canonical declarations with final 200 URLs and verify a fresh crawl plus URL Inspection.",
         "effort": "4–8 engineering hours plus 2–4 QA hours (provisional)",
         "dependencies": "Owner approval of URL policy; SEO and engineering review",
         "reasoning": "Conflicting canonical and redirect signals. This is not an HTTP loop "
         "or proof of Google exclusion."},
        {"id": "T02", "group": "Technical SEO", "priority": "P2", "state": "Review",
         "title": "Review redirect policy", "affected": redirects,
         "fix": "Verify whether each move is permanent before selecting a redirect status.",
         "effort": "1–2 incremental review hours; overlaps T01",
         "dependencies": "T01 URL policy", "reasoning": "307 status alone is not a defect."},
        {"id": "L01", "group": "Internal linking", "priority": "P2", "state": "Observed",
         "title": "Inspect links to redirected URL variants",
         "affected": [row for row in redirects if _number(row, "inlinks") > 0],
         "fix": "Obtain valid link edges or inspect templates; repoint applicable hrefs to final URLs.",
         "effort": "2–4 template hours plus 2 QA hours (provisional)",
         "dependencies": "T01 and valid source/destination links",
         "reasoning": "Inlink aggregates show links to redirecting variants; source pages are unknown."},
        {"id": "C02", "group": "Content", "priority": "P3", "state": "Heuristic review",
         "title": "Review titles and descriptions against real search intent", "affected": snippets,
         "fix": "Use real query evidence before editing priority page snippets; review blank descriptions.",
         "effort": "2–4 hours for first 10 priority pages (provisional)",
         "dependencies": "Confirmed business goals and keyword/ranking baseline",
         "reasoning": "600/1050 pixel values are review heuristics, not Google limits."},
        {"id": "B01", "group": "Backlinks", "priority": "P2", "state": "Missing evidence",
         "title": "Obtain provider backlink and competitor research", "affected": [],
         "fix": "Review actual Semrush/Ahrefs responses in the linked provider runs.",
         "effort": "2–4 hours after usable access", "dependencies": "Target-specific provider data",
         "reasoning": "A crawl cannot establish backlink quality, toxicity or search visibility."},
    ]
    return {"source_tool": "Screaming Frog", "mode": "supplied_export", "website": request.website,
            "summary": f"Analyzed {len(internal)} crawl URL records inside AURA; "
            f"found {len(canonical_conflicts)} canonical/redirect conflicts.",
            "files": files, "counts": {"url_records": len(internal), "unique_comparison_urls": len(by_url),
            "http_status": dict(Counter(row.get("Status Code") for row in internal)),
            "html_200": len(html), "indexable_html": sum(row.get("Indexability") == "Indexable"
                                                        for row in html),
            "canonical_conflicts": len(canonical_conflicts), "link_edge_rows": len(edge_rows)},
            "crawl_period": {"first_raw": timestamps[0] if timestamps else None,
                             "last_raw": timestamps[-1] if timestamps else None,
                             "timezone": "Not supplied", "export_created_at": "Not supplied"},
            "warnings": warnings, "issues": checks,
            "unverified_checks": ["Current Mantas Auk engagement and owner business goals",
                                  "Crawl rendering/robots/settings", "Sitebulb findings",
                                  "Sitemap, hreflang, Search Console and analytics",
                                  "Financial claims and Spanish translation expert review"],
            "website_modified": False}


def crawl_review_recipe(prompt: str, inventory: list[dict], input_names: set[str]):
    match = CRAWL_REQUEST.match(prompt)
    if not match:
        return None
    documents_key = next((key for key in ("attached_documents", "documents") if key in input_names), None)
    if not documents_key:
        raise ValueError("Attach the Screaming Frog CSV exports to this workflow")
    if not any(item.get("slug") == "aura" and "seo.crawl.analyze" in item.get("allowed_operations", [])
               for item in inventory):
        raise ValueError("The AURA crawler-export review capability is unavailable")
    website = match[1]
    CrawlReviewRequest.website_url(website)
    return WorkflowPlan.model_validate({
        "name": "Screaming Frog crawl evidence — " + urlsplit(website).hostname,
        "interpretation": "Parse the uploaded crawl CSV files inside AURA and preserve row evidence.",
        "steps": [{"key": "crawl", "agent": "Crawl Evidence Analyst", "tool_slug": "aura",
                   "operation": "seo.crawl.analyze", "arguments": {"website": website,
                   "documents": "{{inputs." + documents_key + "}}"},
                   "reason": "Validate and deduplicate the supplied Screaming Frog CSV exports, "
                   "join canonical/redirect evidence and show URL-level findings inside AURA.",
                   "expected_output": "Source hashes, dates, counts, affected URLs, fixes and evidence gaps.",
                   "consequential": False}],
        "planning_artifacts": {"planner_recovery_mode": "supplied_crawl_review"},
    })
