"""Build a labelled, reproducible fictional packet; never fetch client data."""
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples/executive-review"
PERIODS = {"current": {"from": "2026-10-05", "to": "2026-10-18", "label": "5–18 October 2026"},
           "previous": {"from": "2026-09-21", "to": "2026-10-04", "label": "21 September–4 October 2026"}}
FIELDS = ["id", "provenance", "period", "metric", "value", "entity_id", "event_id", "event_at"]
PAID = {"google_ads": ([24000, 1200, 3000, 48], [23000, 1150, 2800, 45]),
        "facebook": ([8, 18000, 540, 210, 26000, 390, 600, 14], [8, 17000, 510, 190, 23000, 345, 500, 12]),
        "instagram": ([10, 22000, 1100, 160, 25000, 300, 400, 10], [8, 19000, 760, 130, 22000, 275, 350, 9]),
        "linkedin": ([6, 9000, 360, 180, 12000, 180, 500, 8], [6, 8500, 340, 160, 11000, 165, 450, 7]),
        "x": ([12, 8000, 120, 70, 10000, 100, 100, 2], [12, 8200, 123, 75, 10000, 100, 100, 2])}
AGGREGATE = {
    "google_ads": ["impressions", "clicks", "spend", "tracked_lead_credits"],
    "google_business_profile": ["profile_views", "website_clicks", "call_clicks", "directions_requests", "reviews"],
    **{key: ["organic_posts", "organic_impressions", "organic_engagements", "organic_link_clicks", "paid_impressions", "paid_clicks", "spend", "tracked_lead_credits"] for key in ("facebook", "instagram", "linkedin", "x")},
    "analytics": ["sessions", "engaged_sessions", "form_submit_events", "booking_click_events"],
    "reporting": ["target_qualified_leads", "target_booked", "target_attended", "target_customers", "paid_budget"],
}
VALUES = {**PAID, "google_business_profile": ([3200, 140, 42, 18, 5], [2900, 125, 39, 15, 4]),
          "analytics": ([2400, 1560, 70, 45], [2200, 1430, 62, 35]),
          "reporting": ([40, 32, 24, 8, 4500], [30, 26, 20, 7, 4300])}
DEFINITIONS = {
    "impressions": "Paid search impressions; additive disjoint campaign rows.",
    "clicks": "Paid search ad clicks, not unique visitors.",
    "spend": "Media spend in USD, excluding tax, fees and agency costs.",
    "tracked_lead_credits": "Platform-attributed lead action credits, including repeat/overlapping actions; not deduplicated CRM leads or customers.",
    "profile_views": "Illustrative location profile views; not unique leads.",
    "website_clicks": "Profile website-click action count.", "call_clicks": "Profile call-button clicks, not connected calls or leads.",
    "directions_requests": "Profile direction-request actions, not appointments.", "reviews": "New reviews posted in the window.",
    "organic_posts": "Posts published in the period; organic scope.", "organic_impressions": "Organic content impressions, excluding paid impressions.",
    "organic_engagements": "Organic reactions, comments, saves and shares; impression denominator.",
    "organic_link_clicks": "Organic outbound link clicks, not unique leads.",
    "paid_impressions": "Paid campaign impressions; separate from organic impressions.", "paid_clicks": "Paid ad link clicks.",
    "leads": "Distinct prospect IDs first received in this period after spam/test exclusion; repeated rows deduplicated.",
    "qualified_leads": "Distinct qualified prospect IDs among the leads first received in the same period, as of the cutoff.",
    "customers": "Distinct customer IDs with first accepted paid order in the period, regardless of original lead period.",
    "booked": "Distinct appointment IDs created in the period, including later cancellations; unique people reported separately.",
    "attended": "Distinct appointment IDs completed in the period; may have been booked before the window.",
    "cancelled": "Distinct appointment cancellation events in the period; not subtracted from booking-created counts.",
    "rescheduled": "Distinct reschedule events; not counted as new appointment IDs.",
    "sessions": "Illustrative analytics sessions, not unique people.", "engaged_sessions": "Sessions meeting the demo engagement rule; subset of sessions.",
    "form_submit_events": "Form event count including repeats; not unique CRM leads.", "booking_click_events": "Booking CTA event count; not completed bookings.",
    "target_qualified_leads": "Fictional approved-for-scenario fortnight qualified-lead volume target.",
    "target_booked": "Fictional fortnight booking-created count target.", "target_attended": "Fictional fortnight completed-appointment target.",
    "target_customers": "Fictional fortnight first-customer count target.", "paid_budget": "Fictional fortnight paid media budget in USD; not a live budget change.",
}
SYSTEMS = {"google_ads": "Google Ads compatible fictional CSV", "google_business_profile": "Business Profile compatible fictional location CSV",
           "facebook": "Facebook fictional paid and organic export", "instagram": "Instagram fictional paid and organic export",
           "linkedin": "LinkedIn fictional paid and organic export", "x": "X fictional paid and organic export",
           "crm": "Generic fictional CRM ledger; vendor not asserted", "appointments": "Generic fictional sales-meeting ledger; vendor not asserted",
           "analytics": "GA4-shaped fictional event export; actual analytics product unconfirmed",
           "reporting": "Generic fictional goals and reporting export; reporting vendor not asserted"}
PREFIXES = {"google_ads": "GA", "google_business_profile": "GBP", "facebook": "FB", "instagram": "IG", "linkedin": "LI", "x": "X", "crm": "CRM", "appointments": "APT", "analytics": "ANA", "reporting": "REP"}


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = []
    for key in SYSTEMS:
        rows = []
        def add(period, metric, value, entity="", event=""):
            prefix = "C" if period == "current" else "P"
            rows.append({"id": f"{PREFIXES[key]}-{prefix}-{len(rows)+1:03d}", "provenance": "SIMULATED", "period": period,
                         "metric": metric, "value": value, "entity_id": entity, "event_id": event,
                         "event_at": ("2026-10-10" if period == "current" else "2026-09-26") + "T12:00:00-05:00"})
        for index, period in enumerate(("current", "previous")):
            prefix = "C" if period == "current" else "P"
            if key in AGGREGATE:
                for metric, value in zip(AGGREGATE[key], VALUES[key][index], strict=True):
                    add(period, metric, value)
            elif key == "crm":
                for metric, count in zip(("leads", "qualified_leads", "customers"), ([60, 36, 8] if index == 0 else [50, 25, 6]), strict=True):
                    for n in range(count):
                        add(period, metric, 1, f"{prefix}{'K' if metric == 'customers' else 'L'}{n+1:03d}")
                add(period, "leads", 1, f"{prefix}L001")  # Explicit duplicate record exercises identity dedupe.
            else:
                counts = [30, 22, 4, 2] if index == 0 else [24, 19, 3, 1]
                people = [27, 20, 4, 2] if index == 0 else [22, 18, 3, 1]
                for metric, count, unique in zip(("booked", "attended", "cancelled", "rescheduled"), counts, people, strict=True):
                    for n in range(count):
                        add(period, metric, 1, f"{prefix}L{n % unique+1:03d}", f"{prefix}{metric[:1]}{n+1:03d}")
        metrics = {row["metric"] for row in rows}
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
        filename = f"SIMULATED_{key}.csv"
        (OUT / filename).write_text(output.getvalue())
        sources.append({"source_key": key, "synthetic": True, "csv_text": output.getvalue(), "periods": PERIODS,
                        "metadata": {"filename": filename, "system": SYSTEMS[key], "actual_system_status": "unconfirmed",
                                     "timezone": "America/Chicago", "currency": "USD", "as_of": "2026-10-20T09:00:00-05:00",
                                     "date_basis": "Complete local calendar days; platform interaction date. Lifecycle records use their declared event date.",
                                     "attribution": ("Illustrative 30-day click attribution for search lead credits." if key == "google_ads" else
                                                     "Illustrative 7-day click / 1-day view lead credits; organic scope separate." if key in PAID else
                                                     "No cross-platform attribution. Source event-date counts only; no causal or cohort conversion claim."),
                                     "definitions": {metric: DEFINITIONS[metric] for metric in sorted(metrics)},
                                     "limitations": ["Every input value and record is fictional and is not Goelzer Industries performance.",
                                                     "Actual client account and software are unconfirmed; vendor reporting API not called.",
                                                     "Conversion windows may still be open; values are one illustrative cutoff, not an incrementality result."]}})
    config = {"synthetic": True, "version": 1, "agency": "Luce Media", "review_date": "2026-10-20", "timezone": "America/Chicago", "currency": "USD",
              "client": {"name": "Goelzer Industries", "public_relationship_url": "https://lucemedia.net/commercial-printer-success-story/",
                         "website": "https://www.goelzerind.com/", "context": "A real envelope manufacturer named in Luce Media's public case study. Public relationship evidence does not confirm current engagement, channel adoption or account access."},
              "brief": "SIMULATED scenario objective: generate qualified B2B envelope quote inquiries, book sales consultations and acquire first-order customers while respecting the illustrative media budget. No new offer, guarantee or real client approval is asserted.",
              "stack": [{"role": "CRM", "demo_source": "generic fictional CRM ledger"}, {"role": "Appointment system", "demo_source": "generic fictional sales-meeting ledger"},
                        {"role": "Analytics", "demo_source": "GA4-shaped fictional event export"}, {"role": "Reporting software", "demo_source": "generic goals CSV and AURA review display"}],
              "previous_review": {"provenance": "SIMULATED", "summary": "Fictional prior review: prioritize source definitions, weekday quote follow-up and sales-calendar routing; assess the current period against explicit fortnight targets.",
                                  "actions": [{"id": "PR1", "title": "Reconcile lead qualification", "status": "partial", "note": "Illustrative qualification rules still need a real-client owner."},
                                              {"id": "PR2", "title": "Review consultation capacity", "status": "open", "note": "Fictional sales-calendar capacity review remains open."}]},
              "team_updates": [{"id": "TU1", "provenance": "SIMULATED", "date": "2026-10-19", "role": "Paid media lead", "update": "Scenario note: prospecting audience mix changed; treat it as a possible explanation, not measured causality."},
                               {"id": "TU2", "provenance": "SIMULATED", "date": "2026-10-19", "role": "Sales operations lead", "update": "Scenario note: calendar capacity and response times may affect bookings; validate with linked records before attributing changes."}]}
    request = {"config": config, "sources": sources}
    serialized = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    assert len(serialized) + len("AURA_EXECUTIVE_REVIEW_V1\n") < 50_000, "Request exceeds audited planner input size"
    (OUT / "request.json").write_text(serialized)
    packaged = ROOT / "backend/app/fixtures/executive_goelzer_v1.json"
    packaged.parent.mkdir(parents=True, exist_ok=True)
    packaged.write_text(serialized)
    print(f"Wrote ten SIMULATED CSV exports and {len(serialized)}-character AURA request")
    return request


if __name__ == "__main__":
    build()
