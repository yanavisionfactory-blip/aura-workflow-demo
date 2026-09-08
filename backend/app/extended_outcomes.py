"""Provider-specific outcome evidence, including compound and asynchronous writes."""
from dataclasses import replace
import hashlib

EXTRA_READBACK = {
    "airtable.create": "airtable.record.get", "sheets.append": "sheets.read",
    "notion.blocks.children.append": "notion.blocks.children.list",
    "slack.post": "slack.message.get",
    "hubspot.contact.update": "hubspot.contact.get", "hubspot.company.update": "hubspot.company.get",
    "mailchimp.member.upsert": "mailchimp.member.get",
    "mailchimp.campaign.create": "mailchimp.campaign.get", "mailchimp.campaign.send": "mailchimp.campaign.get",
    "canva.design.create": "canva.design.get", "canva.export.create": "canva.export.get",
    "tiktok.video.upload.init": "tiktok.post.status.get", "tiktok.video.publish.init": "tiktok.post.status.get",
}


def build_extended(operation, a, receipt):
    from .outcome_checks import OutcomeCheck
    read = EXTRA_READBACK.get(operation)
    if not read:
        return None
    rid = str(receipt.get("id") or "")
    if operation == "airtable.create":
        records = receipt.get("records", [])
        if not a.get("records") or len(records) != len(a["records"]) or len(records) > 10:
            raise ValueError("Record receipts do not cover the approved batch")
        checks = tuple(OutcomeCheck(read, {"base_id": a["base_id"], "table_id": a["table_id"], "record_id": record["id"]},
            record["id"], {"fields": expected["fields"]}) for record, expected in zip(records, a["records"], strict=True))
        if len({c.resource_id for c in checks}) != len(checks):
            raise ValueError("Duplicate record receipts")
        return replace(checks[0], kind="compound", checks=checks)
    if operation == "sheets.append":
        rid = receipt.get("spreadsheetId", "")
        if rid != a["spreadsheet_id"]:
            raise ValueError("Spreadsheet receipt changed account resource")
        return OutcomeCheck(read, {"spreadsheet_id": rid, "range": receipt["updates"]["updatedRange"]}, rid,
            {"values": a["values"], "range": receipt["updates"]["updatedRange"]}, "sheets")
    if operation == "notion.blocks.children.append":
        ids = [item["id"] for item in receipt.get("results", [])]
        if len(ids) != len(a["children"]) or len(ids) != len(set(ids)):
            raise ValueError("Block receipts do not cover the approved children")
        return OutcomeCheck(read, {"block_id": a["block_id"]}, a["block_id"], {"ids": ids, "children": a["children"]}, "notion_blocks")
    if operation == "slack.post":
        if receipt.get("channel") != a["channel"]:
            raise ValueError("Message receipt changed destination")
        rid = receipt.get("ts", "")
        return OutcomeCheck(read, {"channel": a["channel"], "ts": rid}, rid, {"channel": a["channel"], "text": a["text"]}, "slack")
    if operation.startswith("hubspot."):
        key = "contact_id" if ".contact." in operation else "company_id"
        rid = rid or a[key]
        if rid != str(a[key]):
            raise ValueError("CRM receipt changed resource")
        properties = {k: "" if v is None else str(v).lower() if isinstance(v, bool) else str(v) for k,v in a["properties"].items()}
        return OutcomeCheck(read, {key: rid, "properties": list(properties)}, rid, {"properties": properties, "archived": False})
    if operation == "mailchimp.member.upsert":
        email = a["email_address"].strip().lower()
        rid = hashlib.md5(email.encode(), usedforsecurity=False).hexdigest()
        if receipt.get("id") != rid:
            raise ValueError("Member receipt changed resource")
        return OutcomeCheck(read, {"list_id": a["list_id"], "subscriber_hash": rid}, rid,
            {"list_id": a["list_id"], "email_address": email, "merge_fields": a.get("merge_fields", {}), "status": receipt["status"]})
    if operation.startswith("mailchimp.campaign."):
        rid = rid or a.get("campaign_id", "")
        expected = {"status": "sent"} if operation.endswith("send") else {key: a[key] for key in ("type", "recipients", "settings")}
        return OutcomeCheck(read, {"campaign_id": rid}, rid, expected)
    if operation == "canva.design.create":
        rid = receipt.get("design", {}).get("id", "")
        return OutcomeCheck(read, {"design_id": rid}, rid, {"title": a.get("title"), "design_type": a["design_type"], "asset_id": a.get("asset_id")}, "canva_design")
    if operation == "canva.export.create":
        rid = receipt.get("job", {}).get("id", "")
        return OutcomeCheck(read, {"export_id": rid}, rid, {}, "canva_export")
    rid = receipt.get("data", {}).get("publish_id", "")
    return OutcomeCheck(read, {"publish_id": rid}, rid,
        {"status": "SEND_TO_USER_INBOX" if operation == "tiktok.video.upload.init" else "PUBLISH_COMPLETE"}, "tiktok_job")


def leaves(check):
    return [leaf for child in check.checks for leaf in leaves(child)] if check.kind == "compound" else [check]


def evaluate_extended(check, observed):
    from .outcome_checks import _matches, _same_id, evaluate_outcome_check
    def result(status, reason):
        return {"status": status, "reasons": [reason]}
    if check.kind == "compound":
        rows = observed.get("checks", [])
        if len(rows) != len(check.checks):
            return result("unverified", "Read-back does not cover every required resource")
        verdicts = [evaluate_outcome_check(c, row) for c,row in zip(check.checks, rows, strict=True)]
        if any(v["status"] != "verified" for v in verdicts):
            return {"status": "unverified", "reasons": [reason for v in verdicts if v["status"] != "verified" for reason in v["reasons"]]}
        return result("verified", "All requested resources and content matched provider reads")
    if check.kind == "sheets":
        matched = _matches(check.expected, observed)
    elif check.kind == "slack":
        messages = observed.get("messages", [])
        matched = observed.get("channel") == check.expected["channel"] and len(messages) == 1 and messages[0].get("ts") == check.resource_id and messages[0].get("text") == check.expected["text"]
    elif check.kind in {"notion_blocks", "notion_children"}:
        if observed.get("_aura_completeness", {}).get("complete") is not True:
            return result("unverified", "Notion read-back did not cover all pages and nested blocks")
        import copy
        blocks = copy.deepcopy(observed.get("results", []))
        def expand(block):
            kind = block.get("type")
            if block.get("has_children") and kind:
                nested = copy.deepcopy(observed.get("nested_children", {}).get(block.get("id"), []))
                block.setdefault(kind, {})["children"] = [expand(c) for c in nested]
            return block
        blocks = [expand(b) for b in blocks]
        if check.kind == "notion_blocks":
            indexed = {b.get("id"): b for b in blocks}
            blocks = [indexed.get(identifier) for identifier in check.expected["ids"]]
        matched = _matches(check.expected["children"], blocks)
    elif check.kind == "canva_design":
        design = observed.get("design", {})
        if not _same_id(check.resource_id, design.get("id")):
            return result("failed", "Read-back design differs from the action receipt")
        if check.expected.get("title") is not None and design.get("title") != check.expected["title"]:
            return result("failed", "Read-back design title differs from the approved title")
        expected_type = check.expected["design_type"]
        if expected_type.get("type") == "custom" or check.expected.get("asset_id"):
            return result("unverified", "Design metadata cannot establish custom geometry or asset content")
        name = expected_type.get("name")
        matched = bool(name) and name in design.get("design_types", [])
    elif check.kind == "canva_export":
        job = observed.get("job", {})
        if not _same_id(check.resource_id, job.get("id")):
            return result("failed", "Read-back export differs from the action receipt")
        if job.get("status") != "success":
            return result("pending" if job.get("status") == "in_progress" else "failed", "Export job is not successfully complete")
        matched = bool(job.get("urls")) and all(isinstance(url, str) and url.startswith("https://") for url in job["urls"])
    elif check.kind == "tiktok_job":
        if observed.get("_aura_requested_publish_id") != check.resource_id or observed.get("error", {}).get("code") != "ok":
            return result("unverified", "Posting status is not correlated with the recorded job")
        matched = observed.get("data", {}).get("status") == check.expected["status"]
        if not matched:
            return result("pending" if observed.get("data", {}).get("status") in {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"} else "unverified", "Posting job has not reached the requested completed state")
    else:
        return None
    return result("verified", "Requested outcome matched resource-specific provider evidence") if matched else result("failed", "Provider read-back does not match the requested outcome")


async def observe_check(executor, check):
    """All calls here are read operations. Caller supplies shared time/request budgets."""
    if check.kind == "compound":
        return {"checks": [await observe_check(executor, child) for child in check.checks]}
    return await executor.execute(check.operation, check.arguments)


def required_reads(operation, arguments):
    from .outcome_checks import READBACK_OPERATIONS
    read = READBACK_OPERATIONS.get(operation)
    required = {read} if read else set()
    if operation == "notion.page.create" and arguments.get("children"):
        required.add("notion.blocks.children.list")
    return required
