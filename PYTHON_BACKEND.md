# AURA Python control plane

The GitHub Pages site is only the React client. Real execution is provided by `backend/`, a separately deployed Python service.

## Runtime architecture

- FastAPI exposes workspaces, tools, OAuth callbacks, runs, approvals, and run-state APIs.
- PostgreSQL stores workflows, steps, approvals, encrypted tool connections, and audit events.
- Redis and Celery provide recoverable background planning and execution.
- OpenAI Agents SDK runs structured, role-specific agents behind the control-plane API.
- The agent hierarchy includes an Intent & Scope Agent, Tool Router, Plan Builder, Static Plan
  Evaluator, AURA Senior Orchestrator, named Execution Agents, Tool Output Critic, Unified Response
  Synthesizer, Outcome Verifier, bounded Replanner, and Approval Argument Resolver. A deterministic
  workflow state manager remains the durable source of truth around those model roles.
- Planning is separated into Propose, Supervise, and Authorize phases. The Senior Orchestrator
  reviews a deterministically valid plan and can require one bounded planner repair. Execution cannot
  begin until capability checks and human approval pass.
- Before execution, the Senior Orchestrator assigns every incomplete approved step to a named
  Execution Agent. That agent's exact `execute` directive triggers the credential-isolated provider
  gateway. It cannot change the approved step key, tool, operation, arguments, permissions, or
  destination; invalid widening is discarded and logged. The same boundary applies to approved
  fallback and reduced-scope recovery calls.
- After a delivery stops, an Autonomous Delivery Supervisor selects only from policy-generated safe
  recovery options. It can retry transient reads on a fresh durable delivery, resume review from a
  saved provider receipt, repeat final verification, revalidate an existing managed connection, or
  reconcile a supported uncertain update through read-back. Recovery state, attempt boundaries and
  the next dispatch time are persisted in the run. It cannot approve work, change arguments, create
  a login session, reactivate an explicitly revoked connection, or repeat an uncertain write.
- Each real provider result is evaluated against its step contract. Safe reads may be retried once;
  consequential actions are never automatically replayed after an uncertain result.
- Final synthesis uses only critic-accepted artifacts and includes step-level traceability.
- Production requests use verified Clerk session JWTs plus an AURA workspace UUID. The server maps
  Clerk users and organizations to active AURA membership records, then sets a transaction-local
  PostgreSQL tenant context. Signed workspace capability tokens remain available only as a migration
  path and for local development.
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
- Non-consequential steps use persisted attempts with three retries and 1s/2s/4s backoff per bounded
  recovery cycle. Approved read-only fallback tools and reduced-scope arguments may recover
  automatically. Attempt numbers remain globally monotonic for auditability. Consequential actions
  always inspect their complete attempt history and are never automatically replayed after an
  uncertain outcome.
- Accepted outputs are stored as versioned artifacts. Exhausted recovery returns an explicit partial
  result and `waiting_for_action`; `/v1/runs/{run_id}/resume` supports retry, approved fallback,
  optional-step skip, or cancellation without rerunning completed steps.

## Compatibility note

When Clerk is configured, call `POST /v1/auth/bootstrap` with the Clerk session token in
`Authorization: Bearer …`. Store the returned `workspace_id`, send it as `X-Workspace-ID`, and send
the Clerk token on every protected request. Set `ALLOW_LEGACY_WORKSPACE_TOKENS=false` after the web
client cutover. Development can temporarily keep the signed workspace-token contract enabled.

Clerk token verification validates the RS256 signature, expiry, optional issuer, organization status,
and the `azp` browser origin against `CLERK_AUTHORIZED_PARTIES`. AURA database membership remains the
authorization boundary; a valid identity token alone never grants workspace access.

## Production roadmap

| Phase | Scope | Production outcome |
|---|---|---|
| 3. Real user accounts | B2C-first signup and login with an automatically provisioned personal workspace | Every customer is isolated without requiring organization membership |
| 4. Production secrets | Encrypted per-user tokens, rotation, revocation and audit records | No credentials exposed to frontend or agents |
| 5. Workflow engine | Trigger → conditions → actions, schedules, retries, branching and reusable variables | Workflows survive restarts |
| 6. Trigger infrastructure | Webhooks where available; polling with checkpoints otherwise | No duplicate or lost executions |
| 7. Execution safety | Approval before sensitive actions, idempotency, rate limits, retry policy and dead-letter queue | Actions cannot accidentally run twice |
| 8. Observability | Execution history, understandable errors, provider health and reconnect warnings | Users can diagnose failures themselves |
| 9. Billing and limits | Plans, usage metering, connector/run limits and Stripe billing | Usage is enforced and billable |
| 10. Optional team and enterprise accounts | Opt-in organizations, invitations, shared workspaces, member roles, SSO and enterprise administration | Personal accounts remain the default while teams can collaborate when they choose |

Organizations are a later B2B/enterprise capability, not an onboarding requirement. AURA must always
allow an individual to create an account and use a private personal workspace without creating or
joining an organization.

## Universal connector protocol

The backend normalizes every external system into a verified capability manifest. The same registry
accepts OAuth applications, OpenAPI and custom REST services, MCP servers, external agents, plugin
manifests, webhooks and an optional isolated browser-connector worker. Plans consume declared
capabilities instead of inventing brand-specific actions.

- `GET /v1/connectors/catalog` reports supported adapter types and whether browser execution is available.
- `POST /v1/connectors/discover` discovers, normalizes, tests and encrypts a provider connection.
- Agent and plugin manifests are read from `.well-known/aura-agent.json` and
  `.well-known/aura-plugin.json` by default.
- OpenAPI operations become typed, approval-classified capabilities. MCP tools are discovered from the
  live server. Custom APIs must supply a capability manifest; arbitrary undeclared HTTP operations are
  never inferred by a model.
- `POST /v1/connections/{id}/test` re-verifies health and `DELETE /v1/connections/{id}` revokes the
  local credential and disables the provider.
- Missing capabilities put a run into `waiting_for_connection`. The requirements are available at
  `/v1/runs/{id}/connection-requirements`; after a verified provider is selected,
  `/v1/runs/{id}/resume-after-connection` re-plans from the original objective.
- External agents receive a scoped capability invocation with delegation disabled. They cannot expand
  the approved plan or silently call another agent.

Arbitrary website operation requires a separately deployed isolated browser worker configured through
`BROWSER_CONNECTOR_URL`. Without that worker, the browser adapter refuses connection instead of storing
passwords or presenting a theatrical success state.
- Provider credentials are encrypted with Fernet and are never passed into model context.
- Provider writes pause for approval. Approved payloads may be edited before execution.
- Idempotency keys prevent an already-completed provider action from being treated as a new step.
- `AGENT_MANAGED_EXECUTION_ENABLED=true` enables senior supervision and per-call execution-agent
  decisions. Production agent-managed runs remain sequential so parallel prefetch cannot bypass the
  delegation boundary. Every supervision and execution decision is written to the audit trail.

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
