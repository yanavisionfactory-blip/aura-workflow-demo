# Campaign export reporting pilot

The authenticated `AURA_CAMPAIGN_REPORT_V1` command creates one new workbook through the existing native Google Workspace connection. It reads the attached Excel export pack inside AURA, preserves literal source rows, calculates formulas and independently reads back every generated calculation before completion. It returns the Google workbook and its authenticated Excel export link, plus a short client-summary draft. No advertising API query, campaign modification, email or sharing operation is performed.

Attach exactly one XLSX workbook with the tabs `Google Ads`, `Meta Ads` and `GA4`. The first row must use the source column labels defined in `extract_export_rows` in `backend/app/campaign_report.py`. Derived columns and the supplied Summary are not trusted as raw inputs. The source cells must be literal values. Duplicate period/campaign/channel identities, missing periods, unequal period lengths, mismatched weekday mixes, negative or nonfinite values, duplicate row references, missing exports and oversized archives are rejected.

Submit this prefix followed by a JSON object (example metadata only):

```text
AURA_CAMPAIGN_REPORT_V1
{"attachment_name":"sample.xlsx","client_name":"Anonymized client","data_status":"anonymized_sample","currency":"USD","prior_start":"2026-09-07","prior_end":"2026-09-20","current_start":"2026-09-21","current_end":"2026-10-04","google_attribution":"Not supplied","meta_attribution":"7-day click / 1-day view","ga4_attribution":"Data-driven key events","source_timezone":"Not supplied"}
```

Review the period and attribution metadata against the export's notes before Start. The parser derives the original file SHA-256 and source row numbers. Normalized inline packets using `CampaignReportFields` are also accepted. The file fingerprint identifies the uploaded bytes; verification establishes arithmetic and saved content, not vendor authenticity or attribution validity.

Revenue per session uses GA4 purchase revenue / sessions. Frequency is calculated per Meta campaign from its own impressions / reach. The workflow never sums campaign reach or presents an account-level frequency without deduplicated account reach. Google and Meta outcomes remain separate. The source's blended totals are labelled overlapping platform credits. GA4 transactions / sessions is labelled as that ratio, not a session key-event rate. Zero denominators remain unavailable rather than becoming zero performance.

The workbook contains Summary, Google Ads, Meta Ads, GA4 and Notes. Editable inputs are blue; formulas retain native spreadsheet formulas. Replacing same-grain inputs updates formulas. New row counts or periods require a new validated run. The client-summary draft describes the executed snapshot and should be regenerated with the next run.

Creating the workbook is one atomic provider POST. The existing runtime persists the write receipt before the independent GET. Resuming that receipt performs verification without another create. An unknown write outcome must be reconciled, never blindly retried. Intentionally running the workflow again creates a separate workbook for repeatability comparison.

The existing native Google grant must permit spreadsheet writes and read-back. The report operation does not expand OAuth scopes. Approval and workspace/account preflight remain in force. Excel export requires the connected Google user's access; no public link sharing is enabled. A successful workbook read-back does not claim that an Excel download has occurred. Validate the downloaded file during the live pilot.

Pilot hands-on baseline, assisted time and usefulness rating are participant measurements. A complete repeat run must be observed separately. Synthetic regression tests and successful deployment alone do not establish pilot success.
