# AURA

AURA is a multi-tenant workflow automation application. The React frontend authenticates with Clerk and sends the current session token to the Python control plane. Workflows, runs, schedules, autonomous process cases, access requests, connection state, and orchestration records are stored by workspace.

`main` is the single controlled release source for both the GitHub Pages frontend and the Railway Python control plane. Production changes must be reconciled and tested on a branch from `main`, then merged through one reviewed pull request.

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
