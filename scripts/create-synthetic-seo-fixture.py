"""Create the public walkthrough fixture from newly authored demo content only.

This script does not read any emails, exports, attachments or account data.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
articles = [
    {
        "id": "dallas", "location": "Dallas",
        "title": "AC Repair in Dallas: Make Your First Service Conversation Count",
        "angle": "A practical first-visit guide: observations, questions and a clear next step.",
        "body": """A cooling problem is easier to discuss when you can explain what changed. Before arranging AC repair in Dallas, make a short note of the rooms affected, when the problem started and whether it happens throughout the day. You do not need a diagnosis. Useful observations give the service team a better starting point.

Northstar Home Comfort is a fictional residential HVAC company created for this demonstration. This draft shows how an agency could turn a service brief into helpful local content, then review the wording, search metadata and handoff before publication.

## Start with the problem you can observe

Describe the difference between normal operation and what you notice now. Is one room uncomfortable while the rest of the home feels normal? Is the system running at different times than usual? Has the issue appeared once or become a repeating pattern? Record these details in ordinary language instead of guessing which component is responsible.

If you have an earlier service summary, keep it available. The equipment model and approximate installation date may also help the service team prepare. Share only records you have; missing paperwork should not lead you to invent an equipment history.

## Explain what you want from the visit

A request for repair and a request for a routine maintenance appointment may involve different work. Tell the team whether your main concern is a current cooling problem, recurring performance or a discussion about future replacement. Ask which appointment type fits that concern.

Before agreeing to a visit, confirm the service area, appointment arrangements and any assessment fee. Do not assume a business offers same-day or round-the-clock service unless it has confirmed that directly. This demonstration does not make availability or price promises.

## Ask for a clear explanation of the findings

During the conversation, ask the technician to connect their findings with the symptoms you described. Request an explanation of the proposed work, what is included in the estimate and whether additional work would require another approval. A clear scope helps you understand the decision in front of you.

If more than one option is proposed, ask how the options differ. The aim is to understand the recommendation, not to choose a repair based on a single online description. Diagnosis and equipment work belong with a qualified professional.

## Compare repair and replacement questions

An older system or a repeated problem can raise questions about repair and replacement. Ask for a written comparison that addresses the current issue, the proposed scope and any relevant equipment information. An article cannot determine which option is appropriate for your home.

Keep the comparison focused on information the provider can substantiate. Savings estimates, warranty terms and equipment claims need their own supporting documentation. Avoid treating an attractive headline or an unverified promise as evidence of the result you will receive.

## Keep a useful record after the appointment

Save the written findings, the approved estimate and any follow-up instructions supplied by the provider. These records can help you explain the history if another concern appears later. If you are unclear about a recommendation, ask for clarification before approving additional work.

For a real Dallas service page, the next step would be a confirmed contact route and a client-approved explanation of how appointments are requested. This demonstration intentionally leaves that destination unconnected. An agency reviewer should confirm business details, claims, images and the final call to action before publishing.""",
        "seo": {"title": "AC Repair Dallas: Plan Your Service Conversation", "description": "Prepare for an AC repair conversation in Dallas with useful symptom notes, service questions and a written review of the proposed work. Fictional demo.", "focusKeyword": "ac repair dallas"},
    },
    {
        "id": "plano", "location": "Plano",
        "title": "Planning AC Service in Plano: Turn Repeated Comfort Concerns into Useful Notes",
        "angle": "Recurring comfort patterns and maintenance history, with a distinct homeowner checklist.",
        "body": """A comfort problem that comes and goes can be difficult to describe when an appointment finally arrives. If you are planning AC repair in Plano, build a simple record of the pattern: which rooms are affected, what time it happens and how long the change lasts. A short set of observations is more useful than an unsupported guess about the cause.

This article is a newly written example for Northstar Home Comfort, a fictional company. Its purpose is to demonstrate location-specific content preparation and agency review, rather than advertise an operating service.

## Build a brief comfort diary

Choose a few details you can record consistently. Note the date, the room and the change you noticed. You might describe a bedroom that feels different from the rest of the house or a concern that returns at a particular time. Keep the description factual and avoid drawing conclusions from one observation.

Bring those notes to the service conversation. Ask the provider which details would help them understand the request and whether a recurring concern needs a different appointment from a general maintenance visit.

## Gather the records you already have

Previous estimates, appointment summaries and equipment documents can help explain the system's history. Place them together so the team can distinguish a new concern from work discussed earlier. If the information is incomplete, say so clearly.

You do not need to open equipment or attempt a repair to prepare for an appointment. Let a qualified professional determine which checks and work are appropriate. This article offers a communication checklist, not a technical diagnosis.

## Separate the current problem from maintenance planning

Start with the issue you want addressed now. Then ask whether the provider recommends a separate discussion about routine maintenance. Keeping those questions distinct makes it easier to understand the appointment scope and the cost of any additional service.

Confirm what a proposed maintenance visit includes, how recommendations will be documented and whether new work requires your approval. Do not assume that a particular package, membership or guarantee exists unless the business has verified it.

## Finish with an agreed next step

Ask for the findings and recommended next step in writing. If you receive several options, request a plain-language comparison of the work included in each. Keep any appointment instructions and follow-up documents with your earlier records.

A real Plano page would end with the business's verified service coverage and contact details. The agency should add those only after client review. This unpublished demonstration leaves bookings disconnected and makes no promises about response time, price or outcomes.""",
        "seo": {"title": "AC Repair Plano: Notes for a Better Service Visit", "description": "Document recurring comfort concerns before arranging AC service in Plano. Review maintenance history, appointment scope and next steps. Fictional demo.", "focusKeyword": "ac repair plano"},
    },
    {
        "id": "richardson", "location": "Richardson",
        "title": "AC Repair in Richardson: Understand the Estimate Before You Approve Work",
        "angle": "Estimate scope and approval questions, rather than a renamed Dallas article.",
        "body": """When a cooling problem leads to a service recommendation, the next decision is often about scope: what work is proposed, what the estimate includes and what happens if the findings change. Homeowners considering AC repair in Richardson can prepare a few questions that make that decision easier to understand.

Northstar Home Comfort is a fictional business used in this AURA walkthrough. This unpublished article demonstrates an estimate-focused local version with its own structure and search metadata. It is not a quote, diagnosis or offer of service.

## Describe the concern before discussing a solution

Begin with what you noticed and when it started. Explain whether the problem affects one space or several and whether it has happened before. Previous appointment notes may provide context, but avoid treating an earlier recommendation as a diagnosis of the current issue.

Ask the provider how the visit will be arranged and what the initial assessment includes. Clarify any assessment fee and the process for receiving an estimate. A documented starting point reduces confusion about what you have authorized.

## Read the proposed scope in plain language

An estimate should give you a basis for discussing the recommendation. Ask the provider to explain the work in terms you understand, including what is included and what remains outside the proposed scope. If an item is unclear, request a written explanation before making a decision.

Where the recommendation includes parts, follow-up work or another appointment, ask how those items are represented. Confirm which details are estimates and which are fixed terms. Only the service provider can verify the commercial terms it offers.

## Confirm how changes will be approved

Ask what happens if the technician identifies an additional issue during the work. Will the provider explain the finding and seek approval for a revised scope? Who should receive that request? Agreeing on a point of contact is useful when someone else in the household will be present.

Do not approve a broader recommendation solely because it appears in a general article. Ask how it relates to the findings at your property and which alternatives the provider considers appropriate. Equipment assessment and repairs require a qualified professional.

## Save the decision and follow-up record

Keep the approved estimate, the service summary and any instructions the provider supplies. Record questions that remain open and ask when they will be addressed. These documents create a clear history for a later conversation without relying on memory.

Before a real Richardson article goes live, the agency should verify service coverage, business credentials, contact details, image permissions and all specific claims. This demonstration includes none of those as confirmed facts. Its final step is editorial approval, with publication and appointment requests left disconnected.""",
        "seo": {"title": "AC Repair Richardson: Review the Proposed Scope", "description": "Questions to ask about an AC repair estimate in Richardson: included work, approval of changes and follow-up records. Unpublished fictional demo.", "focusKeyword": "ac repair richardson"},
    },
]
for article in articles:
    article.update({"notice": "Fictional business · newly written demonstration copy · unpublished · client review required. No real service or booking is offered.", "sourceWordCount": len(article["body"].split()), "status": "unpublished", "approval": "pending"})

sample_rows = [
    ("ac repair dallas", 900, "HIGH", 80),
    ("air conditioning repair dallas", 900, "HIGH", 80),
    ("ac service dallas", 300, "MEDIUM", 55),
    ("hvac maintenance dallas", 180, "MEDIUM", 40),
    ("heat pump repair dallas", 120, "MEDIUM", 45),
    ("ac repair plano", 500, "HIGH", 75),
    ("ac maintenance plano", 150, "MEDIUM", 35),
    ("air conditioning service plano", 250, "MEDIUM", 50),
    ("ac repair richardson", 400, "HIGH", 70),
    ("hvac service richardson", 200, "MEDIUM", 45),
    ("emergency ac repair dallas", 350, "HIGH", 90),
    ("commercial ac repair dallas", 160, "HIGH", 85),
]
data = {
    "client": "Northstar Home Comfort · fictional", "agency": "Agency demonstration", "fictional": True,
    "snapshotDate": "2026-10-23", "simulation": True,
    "source": {"label": "Newly authored synthetic walkthrough fixture", "id": "synthetic-hvac-v1", "provenance": "All article text and sample keyword metrics were created for this public demonstration. No private attachment, export or live account data is included."},
    "keywords": {"primary": "ac repair dallas", "target": "Illustrative targeting: Dallas, Plano and Richardson · English · Google Search", "retrievedAt": "Simulated dataset created 23 October 2026 · no provider retrieval", "totalIdeasReported": len(sample_rows), "localVolumeVerified": {"dallas": False, "plano": False, "richardson": False}, "rows": [{"keyword": kw, "volume": vol, "competition": comp, "index": idx, "lowBidMicros": None, "highBidMicros": None} for kw, vol, comp, idx in sample_rows]},
    "articles": articles,
    "limits": [
        "Every keyword metric is simulated; live research is required before a real content decision.",
        "Business claims, service coverage, images and the contact destination require client confirmation.",
        "Imagify is a pending image-review step; no image upload or optimization runs in this demo.",
        "No live SEO Writing, Geo+, WordPress, RankMath or Asana action is performed.",
        "Exact-site audits, backlinks, rankings, traffic and inquiries are outside this simulation.",
        "All three articles are unpublished; reviewer assignment and approval remain pending.",
    ],
}
(ROOT / "src/showcase/first-choice-seo/data.json").write_text(json.dumps(data, indent=2) + "\n")
print("Created fully synthetic fixture: three new articles and twelve illustrative keyword rows.")
