# AURA

AURA is a multi-tenant workflow automation application. The React frontend authenticates with Clerk and sends the current session token to the Python control plane. Workflows, runs, schedules, autonomous process cases, access requests, connection state, and orchestration records are stored by workspace.

## Luce Media biweekly executive review

The authenticated command `AURA_EXECUTIVE_REVIEW_V1` followed by
`{"fixture":"goelzer_industries_v1"}` executes eleven persisted backend steps:
ten independent CSV processors and executive-review model drafting. It uses
Goelzer Industries as real public client context, based only on Luce Media's
[public case study](https://lucemedia.net/commercial-printer-success-story/).
Every metric, goal, lifecycle record, previous-review entry and team update is
explicitly **fictional**, not that company's actual performance. Current
engagement, client accounts and actual software products remain unconfirmed.

The AURA results page is the main deliverable. It includes the executive summary,
performance/target table, agenda, proposed action register and ten tool views:
Google Ads, Google Business Profile, Facebook, Instagram, LinkedIn, X/Twitter,
CRM, appointments, analytics, and reporting/goals. Each view retains CSV rows,
definitions, input SHA-256, actual AURA execution receipt and computed totals.
Only currency-aligned spend is aggregated. Leads, bookings, attendance and first
customers stay distinct; platform lead credits are not deduplicated CRM outcomes.

This is **real AURA export processing**, not vendor reporting API execution or
static playback. It does not upload fabricated metrics into vendors, create a
Google Doc, send messages, assign tasks, change campaigns or schedule meetings.
The packet uses 5–18 October versus 21 September–4 October 2026, America/Chicago,
USD, at one illustrative cutoff. Targets are explicit fortnight scenario inputs.
Actual CRM/appointment/reporting vendors are not guessed from public services.

The exact labelled exports are in `examples/executive-review/`; the compact
command loads the same packaged input bytes from `backend/app/fixtures/` so a
large CSV packet does not exceed the task field's limit. Regenerate both with
`python3 scripts/build-executive-review-fixture.py`. Full inline packets are also
accepted. Tests cover arithmetic, deduplication, comparable periods, provenance,
target definitions, evidence resolution, compilation, real provider dispatch,
native result selection and all ten rendered tool views.

`main` is the single controlled release source for the GitHub Pages frontend and Python control plane. Production changes must be reconciled and tested on a branch from `main`, then merged through one reviewed pull request.

For a Render deployment, use the root [`render.yaml`](render.yaml) and follow
[`docs/render-migration.md`](docs/render-migration.md). The Blueprint prepares a
FastAPI web service, Celery worker, private Postgres database and durable job
queue. Existing production data and encryption keys must be transferred before
the frontend is switched to the new API.

## Frontend

```bash
npm install
cp .env.example .env.local
npm run dev
```

Required browser configuration:

```env
VITE_AURA_API_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

## Backend

See [`docs/PYTHON_BACKEND.md`](docs/PYTHON_BACKEND.md), [`docs/autonomous-processes.md`](docs/autonomous-processes.md), [`backend/RELIABILITY.md`](backend/RELIABILITY.md), and [`docs/production-deployment.md`](docs/production-deployment.md) for PostgreSQL, Redis, Clerk, encryption, worker, and connector-network configuration. Start the API and Celery worker before using the frontend.

Planning defaults to one structured LLM call followed by deterministic operation,
argument, dependency, connection and approval checks. The browser displays an
immediate outline and refines it while the executable plan is compiled. Set
`PLANNER_MODE=agent` on the backend for the previous planner during rollout;
`PLANNER_MODE=llm` is the default. A failed validation never turns a language
outline into an executable plan.

## Release validation

For the Frame.io and PageProof content-approval pilot, see
[`docs/content-approval.md`](docs/content-approval.md). It documents the direct
connections, PageProof comments import, exact evidence requirements and live-run
limitations.

Pull requests run the frontend tests and build, the complete Python test suite, and the isolated execution load evaluation. GitHub Pages publishes the frontend after the pull request is merged to `main`; Railway should also deploy the `backend/` directory from `main`.

## Tenant boundary

Every persisted customer record carries a `workspace_id`. API authorization verifies Clerk organization membership, and PostgreSQL row-level security enforces the same workspace boundary in the database.

## SEO audit preview

A saved Screaming Frog export analysis can be opened at `/runs/:runId/demo/seo-audit` to preview the standard audit result with simulated Semrush, Ahrefs and Sitebulb outputs. The preview reads the original crawl through the authenticated workspace API and resolves example targets to the uploaded CSV rows. Vendor metrics, fictional `.example` referring/competitor domains, scenario hints and recommendations are labelled as simulated. It never calls providers, persists a successful run, creates destination records or modifies a website. The original saved result and provider failure receipts are unchanged.

The separate `/showcase/seo-audit/` entry is a public, backend-free copy of one prepared workflow. It now imports the application's real `WorkspaceShell`, `CommandInput`, `PlanStep`, `PreviewView`, `ExecutionView` and `SeoAuditResult` components, using the normal Tailwind theme. Reference screenshots in the supplied investor presentation informed the input and review sequence. It does not claim a pixel-verified copy of the currently inaccessible Base44 preview.

The flow is task → plan → source/result review → approval → local execution playback → final result. Each tool has its own output; the result also contains affected URLs, a roadmap, backlog and source checks. The anonymized fixture retains real Screaming Frog findings and explicitly simulated Semrush, Ahrefs and Sitebulb examples. Client engagement, owner goals, export settings and reporting/task destination confirmations remain outstanding. Google Docs and Jira are examples; no document, ticket, provider request or site edit is made.

`npm run build` builds the normal application first, then the isolated React showcase. Build-time aliases replace API clients and attachment stores with local adapters; a build guard rejects live account modules. The public HTML also sets `connect-src 'none'`. No customer CSV attachment, private hostname, saved run ID or credential is included. The fixture builder accepts only an explicit local source-run JSON.

`?tour=1` plays a captioned guided walkthrough through the same React interface. It supports pause, previous, next and exploration. The old SVG renderer, poster and authored MP4 have been removed. A new hosted video has not been captured. The optional **Record walkthrough** control asks the browser to share a tab, records that tab with `MediaRecorder`, starts the guided tour, and offers a local WebM/MP4 download (browser-dependent). Recording is silent and is never uploaded. Declining screen sharing leaves the demo usable. Feedback is copied locally, never submitted.

Tests server-render every phase and all four per-tool views, verify source counts and anonymization, and compile the isolated graph. This is not browser visual or interaction verification; use the supported browser when available to check animations, screen recording and final layout.

## SmartSites weekly account-review example

`/showcase/weekly-account-review/` is a second, isolated AURA demo using the same workspace, command input, plan-step, review and execution React components. `?tour=1` starts a captioned, pauseable walkthrough; `?screen=results` opens the review directly. It does not alter the existing SEO demo or authenticated workflow backend.

No approved SmartSites client exports, brand brief, account mapping or reporting destination have been verified. Northline Home is a fictional client and **all** account metrics are authored sample data. Its assumed scope is Google Ads, Meta Ads and Klaviyo email. Microsoft Advertising, Amazon Ads, Mailchimp, HubSpot and SMS are explicitly excluded; no outputs are manufactured for them.

The checked packet compares 12–18 October with 5–11 October 2026 in America/Chicago, USD, at one illustrative cutoff. It keeps each platform's attribution and date basis separate. Paid spend can be summed across Google and Meta; revenue, order credits and ROAS are never blended. Source tables retain stable sample row references, query breakdowns are not double counted, reach is not summed, and email click rates use weighted per-message denominators. Open conversion windows, audience-mix changes and unconfirmed value definitions stay visible.

### Execute the synthetic-data review in AURA

The authenticated runtime also accepts `AURA_WEEKLY_REVIEW_V1` followed by the JSON in
`examples/weekly-review/request.json`. This is a real four-step backend workflow:
three `weekly.source.analyze` CSV processors, followed by `weekly.review.prepare`,
which recalculates the evidence and calls the configured model to generate three
experiments, six creative variants and a prioritized backlog. No prewritten
experiments, creative copy or backlog is included in that request.

The saved result uses AURA's interactive weekly-review component, with independent
Google Ads, Meta Ads and Klaviyo source views, retained CSV bytes, SHA-256 hashes,
execution receipts, filters, evidence links and draft previews. The static showcase
remains local playback. The authenticated run is identified by its backend receipts
and model call, rather than by the presence of a connection badge.

This export-processing route **does not call those vendors' reporting APIs or upload
metrics to their accounts**. Its input metrics are explicitly simulated; its AURA
execution is real. Google Ads test accounts do not serve ads and have empty serving
metrics, so fabricated spend, impressions and conversions cannot be presented as
vendor-generated performance. No campaigns, budgets, customer events, external tasks
or messages are created by this workflow. Live vendor connectivity checks remain
separate runs and must never be relabelled as successful synthetic-data processing.

The result includes three evidence-supported experiment proposals, six draft creative variants (Search messages, Meta concepts and Klaviyo subjects), and eight backlog items with owners, effort, dependencies and acceptance checks. Weekly changes are descriptive materiality flags, not causal or statistically significant findings. Test power, assets, client approvals and the selected Client Hub setup remain review gates.

The weekly build reuses local fixture adapters, excludes live account modules at build time and sets `connect-src 'none'`. Its CSV/JSON downloads, draft-copy control, feedback and optional browser tab recording stay local. It creates no campaigns, platform drafts, tasks, messages, website edits, budget changes or external reports. Public references substantiate agency services and metric conventions only; they do not substantiate simulated performance. Tests cover arithmetic, scope, metric alignment, evidence resolution, draft limits, every native phase and all guided result views. Supported-browser visual checks and tab recording are not verified by server rendering.

## Approved client weekly reviews

The task screen now includes **Prepare weekly account review** (`?weekly=1`).
Select the actual client, approved scope, goals/brand brief and reporting setup;
provide normalized, approved exports only for included platforms. Meta Ads and Amazon Ads can instead use explicitly authorized, labelled simulations; they do not become live connections or actual client results. The authenticated
V2 workflow supports any subset of Google Ads, Meta Ads, Microsoft Advertising,
Amazon Ads, Klaviyo, Mailchimp and HubSpot marketing email cohorts. It prepares
three evidence-linked experiment proposals, six draft variants and a backlog,
keeping outcome/value attribution separate and an unconfirmed destination visible.
It performs no vendor reporting API calls or external writes. Workspace connections
are shown separately from client/account/export approval. See
[the runbook and export contract](docs/weekly-account-review.md) for limits and
required inputs. The public Northline showcase remains explicitly fictional.
