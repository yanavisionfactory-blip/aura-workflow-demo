# Production deployment

## Railway API and worker

Configure the same environment on the API and Celery worker services:

```env
ENVIRONMENT=production
PUBLIC_URL=https://<api-domain>
OAUTH_CALLBACK_OVERRIDES={}
FRONTEND_URL=https://yanavisionfactory-blip.github.io
DATABASE_URL=<Railway PostgreSQL URL using postgresql+psycopg://>
REDIS_URL=<Railway Redis URL>
OPENAI_API_KEY=<secret>
OPENAI_MODEL=gpt-5.4-mini
CREDENTIAL_ENCRYPTION_KEY=<current Fernet key>
CREDENTIAL_ENCRYPTION_PREVIOUS_KEYS=<retired Fernet keys, comma-separated>
SESSION_SIGNING_KEY=<at least 32 random characters>
CLERK_JWT_KEY=<Clerk PEM public key>
CLERK_ISSUER=<Clerk issuer URL>
CLERK_AUTHORIZED_PARTIES=https://yanavisionfactory-blip.github.io
ALLOW_LEGACY_WORKSPACE_TOKENS=false
NANGO_API_KEY=<Nango environment API key>
PIPEDREAM_CLIENT_ID=<Pipedream OAuth client ID>
PIPEDREAM_CLIENT_SECRET=<Pipedream OAuth client secret>
PIPEDREAM_PROJECT_ID=<Pipedream Connect project ID>
PIPEDREAM_ENVIRONMENT=production
CONNECTOR_ENGINEER_SIGNING_KEY=<at least 32 random characters>
```

With `NANGO_API_KEY` present, AURA discovers existing Nango integrations and provisions a
neutral provider-named integration the first time an app is needed. A static integration map is
not required. `NANGO_INTEGRATION_MAP` remains an optional JSON override only for migrations or
non-standard integration IDs. The key needs integration list/create, provider list, connect-session,
connection read/list/delete, and credential-read access; Nango's default full-access environment key
is the simplest initial configuration.

Set `NANGO_AUTO_PROVISION_INTEGRATIONS=false` only when an operator intentionally wants discovery
without provisioning. When Nango is not configured, AURA's existing native OAuth adapters remain
available.

Pipedream Connect is AURA's embedded long-tail connector plane. The Connector Broker selects a
native or signed Nango release first and falls back to Pipedream for apps with a managed account
flow and a certified action, MCP tool, or allowlisted Proxy operation.
The browser receives only an origin-bound, short-lived Connect token and an opaque AURA user
reference. Pipedream client credentials, provider credentials, raw endpoints, and action transport
metadata remain server-side. Do not put any `PIPEDREAM_*` secret in GitHub Pages, build arguments,
or a variable prefixed with `VITE_`.

At first use, AURA imports Pipedream's data-only action contracts, validates their JSON schemas and
permission annotations in isolation, signs the resulting versioned capability pack, and caches it.
Subsequent connections reuse the signed pack. Account connection performs only an ownership,
health, identity, and scope probe; it does not execute a customer action canary. OAuth providers
show their consent screen; API-key and service-account providers show Pipedream's managed secure
credential form. AURA receives only the opaque account reference. Apps without a complete managed
auth and certified execution route remain **Coming soon** or **Request app**.

Native OAuth providers declare their callback route in the provider registry. The public AURA API
does not accept arbitrary provider API keys, custom OAuth client secrets, or raw connector
credentials. Those legacy submission routes are intentionally absent.
If an existing provider application has a different registered callback, set one deployment
override instead of changing code:

```env
OAUTH_CALLBACK_OVERRIDES={"jira":"https://<api-domain>/v1/oauth/jira/callback"}
```

Each override must be an absolute callback URL with no query string or fragment. Production
readiness fails when the registry contains an invalid or non-HTTPS callback. Keys are native
provider slugs only.

Add each provider's client ID and secret to both services. Never add provider secrets to GitHub Pages, source control, build arguments, or variables prefixed with `VITE_`.

Set the API start command to the Dockerfile default. Set the worker command to:

```bash
celery -A app.worker.celery worker --loglevel=INFO
```

Use a modest worker concurrency for the Railway service size, for example `--concurrency=4`, rather than Celery's CPU-derived default.

The API's elected recovery loop dispatches persisted workflow schedules, due process stages, and
interrupted-run recovery by default, so schedules and autonomous processes do not depend on an open
browser or a separate service. If
`RECOVERY_SCHEDULER_ENABLED=false` on every API replica, run one separate scheduler service:

```bash
celery -A app.worker.celery beat --loglevel=INFO
```

Only one beat service should run. Multiple workers remain safe: due schedules, process cases, and
stale runs are claimed with database row locks, and generated steps retain stable idempotency keys.

## GitHub Pages

Create the repository Actions secret `CLERK_PUBLISHABLE_KEY`. The public Clerk publishable key is the only authentication value compiled into the browser. The API address is configured by `VITE_AURA_API_URL`.

## Experimental live-tool review

The cloud-browser takeover spike is a dark launch and does not replace the existing approval
renderer. Leave it disabled for the normal release. To test it, deploy the isolated browser worker,
configure the API with `BROWSER_CONNECTOR_URL`, `BROWSER_CONNECTOR_TOKEN`, and
`LIVE_TOOL_REVIEW_ENABLED=true`. Keep `VITE_LIVE_TOOL_REVIEW_ENABLED=false` in production until
the browser worker can establish an authenticated provider session without showing a login page.
When both flags are deliberately enabled, the live surface still requires `?liveToolReview=1`.
Turning either flag off restores the established review UI without a code rollback. Interactive
sessions are memory-only, credential-isolated, and expire after ten minutes of inactivity. The standard schema preview and
approval payload remain authoritative while the spike is evaluated. Provider controls that would
send, publish, share, download, or delete stay blocked inside the experimental browser; the
established approval execution path remains the only way to perform the final action. Interactive sessions use their own concurrency limit
(`INTERACTIVE_BROWSER_CONCURRENCY`, default `1`) so a takeover cannot consume the browser slots used
by normal workflow reads.

## Encryption-key rotation

1. Generate a new Fernet key and move the old `CREDENTIAL_ENCRYPTION_KEY` into `CREDENTIAL_ENCRYPTION_PREVIOUS_KEYS`.
2. Deploy the API and worker with the new keyring.
3. As a workspace administrator, call `POST /v1/security/rotate-credentials` once for every workspace.
4. Confirm the audit event `credentials.encryption_rotated` and successful connector tests.
5. Remove retired keys only after every workspace reports zero rotated connections on a second pass.

## Release checks

`GET /health` confirms the process is alive. `GET /ready` additionally checks PostgreSQL, Redis, Clerk, OpenAI, credential encryption, authorized browser origins, and that legacy workspace tokens are disabled.

Run the smoke test after each deployment:

```bash
bash scripts/smoke-production.sh https://<api-domain>
```

Before launch, create two Clerk organizations and verify that workflows, history, schedules, access requests, and connections created in one organization return `404` or `403` from the other.
