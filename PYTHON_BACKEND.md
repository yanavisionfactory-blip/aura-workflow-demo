# AURA Python control plane

The GitHub Pages site is only the React client. Real execution is provided by `backend/`, a separately deployed Python service.

## Runtime architecture

- FastAPI exposes workspaces, tools, OAuth callbacks, runs, approvals, and run-state APIs.
- PostgreSQL stores workflows, steps, approvals, encrypted tool connections, and audit events.
- Redis and Celery provide recoverable background planning and execution.
- OpenAI Agents SDK runs structured, role-specific agents behind the control-plane API.
- The backend uses seven explicit runtime roles from the AURA orchestration design:
  Intent & Scope, Tool Router, Plan Builder, Static Plan Evaluator, deterministic Workflow
  State Manager, Tool Output Critic, and Unified Response Synthesizer.
- Planning is separated into Propose and Authorize phases. Execution cannot begin until the
  deterministic capability check, model-based preflight evaluation, and human plan approval pass.
- Each real provider result is evaluated against its step contract. Safe reads may be retried once;
  consequential actions are never automatically replayed after an uncertain result.
- Final synthesis uses only critic-accepted artifacts and includes step-level traceability.
- Workspace context is a signed capability token issued in the existing workspace `id` field. The
  server verifies active tenant membership and sets a transaction-local PostgreSQL tenant context.
- PostgreSQL Row-Level Security is enabled and forced on every tenant-owned control-plane table,
  including worker access to runs, steps, tools, artifacts, approvals, policy and audit records.
- Every plan is stored as a version with a canonical SHA-256 digest. Approval locks that version and
  stores immutable policy, permission, risk, cost, approver and hash snapshots. Execution refuses a
  plan or step set that differs from the approved snapshot.
- Policy defaults are centralized: +10% cost warning, +25% cost pause, $100 absolute cap, 0.70 trust
  execution floor, 0.85 healthy trust floor, 0.75 risk pause and 0.90 risk block. Only the tenant cost
  cap is tenant-configurable in v1; core safety thresholds cannot be weakened by tenants.
- Tool health is updated from successes, failures, timeouts and latency. Policy is rechecked at every
  step boundary against current trust and permissions; revoked access blocks and expanded access
  pauses for re-approval.
- Non-consequential steps use persisted attempts with three retries and 1s/2s/4s backoff. Approved
  read-only fallback tools and reduced-scope arguments may recover automatically. Consequential
  actions are never automatically replayed after an uncertain outcome.
- Accepted outputs are stored as versioned artifacts. Exhausted recovery returns an explicit partial
  result and `waiting_for_action`; `/v1/runs/{run_id}/resume` supports retry, approved fallback,
  optional-step skip, or cancellation without rerunning completed steps.

## Compatibility note

The frontend contract is unchanged: it continues storing the workspace response's `id` and sending
it as `X-Workspace-ID`. The value is now a signed tenant token rather than a raw database UUID.
Existing browser storage created before this release must be cleared once so the frontend requests a
new signed workspace context.
- Provider credentials are encrypted with Fernet and are never passed into model context.
- Provider writes pause for approval. Approved payloads may be edited before execution.
- Idempotency keys prevent an already-completed provider action from being treated as a new step.

## Supported real operations

| Connection | Operations |
|---|---|
| Google OAuth | Gmail read/send, Calendar read/create, Sheets read (write requires a separate explicit scope grant) |
| Airtable OAuth | Records read/create |
| Slack OAuth | Post approved messages |
| API key/OpenAPI tool | Allow-listed HTTP operations under one configured base URL |
| MCP | Discover and call allow-listed tools on trusted Streamable HTTP MCP servers |

## Run locally

1. Copy `backend/.env.example` to `backend/.env`.
2. Generate keys:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

3. Add `OPENAI_API_KEY` and the OAuth client credentials you want to offer.
4. Configure each provider callback as `https://YOUR_API/v1/oauth/PROVIDER/callback`.
5. Start everything with `docker compose up --build`.

The public GitHub demo must set `VITE_AURA_API_URL` to the deployed API URL. A Python backend cannot run on GitHub Pages.
