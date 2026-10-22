# Move AURA to Render

The root `render.yaml` prepares a FastAPI API, a Celery worker, Postgres and a
durable Key Value job queue in Frankfurt. GitHub Pages remains the frontend.
Applying the Blueprint creates billable resources and empty datastores; it does
not transfer Railway data or redirect production traffic. Review Render's
current price estimate before applying. These are the smallest paid plans for
an always-on API/worker and persistent datastores. Increase database storage
before creation if the existing database will not fit in 5 GB.

## Prepare the release

Merge the reviewed deployment pull request into `main` after CI passes. In
Render, select the intended workspace and create a Blueprint from:

https://dashboard.render.com/blueprint/new?repo=https://github.com/yanavisionfactory-blip/aura-workflow-demo

Review resource names against that workspace before applying: Render can adopt
an existing resource with the same name. All four resources must share a region.
The database is PostgreSQL 18; confirm the source version is compatible before
copying data. Automatic deploys are off so a source push cannot perform a
production cutover. API and worker releases must use the same tested `main` SHA.

The secure creation form asks for the existing encryption key and previous-key
ring, session key, certification key, OpenAI key, Clerk issuer and Clerk JWKS URL.
Leave the previous-key ring empty only if production does not use retired keys.
If production verifies Clerk using `CLERK_JWT_KEY`, also copy that PEM to the
`aura-runtime` environment group. Keep the same Clerk instance and organization
identities so restored workspace memberships remain valid.

Import the remaining production server configuration into `aura-runtime` using
Render's secure Dashboard, preserving the current values for:

- Native provider client IDs and secrets, including Google, Atlassian, HubSpot,
  Mailchimp, Canva and the other enabled providers.
- Nango and Pipedream credentials and integration/project mappings.
- Browser connector URL/token, resource aliases and enabled connector settings.
- Existing connector signing keys and other enabled runtime configuration.

Keep `RECOVERY_GITHUB_REPOSITORY` and `RECOVERY_GITHUB_TOKEN` unset on the new
runtime initially. The current isolated code-repair workflow deploys its canary
and production release to Railway and reports to the Railway URL. It needs a
Render release/canary adapter before being enabled for this host. Ordinary
persisted workflow recovery remains enabled; this restriction applies to the
external code-promotion pipeline.

Do not import old `DATABASE_URL`, `REDIS_URL`, `PUBLIC_URL` or `FRONTEND_URL`
values. The Blueprint wires the new datastores and actual Render API URL without
guessing a hostname. Database URLs supplied as `postgresql://` are converted to
the installed async-capable psycopg driver while preserving credentials/options.
The worker obtains the core keys from the API. Optional provider configuration
belongs in the shared group so both services receive it.

## Transfer state before serving production

First verify the empty deployment can build, start and reach its private
datastores. This proves infrastructure only. Then suspend the new API and worker
before restoring production records. AURA runs migrations and recovery work at
API startup, so do not restore while the new processes are running.

For the final copy, put the old application into a maintenance window, pause
scheduled dispatch and polling, drain active jobs, and stop its API, workers and
any beat/scheduler process. Include the recovery scheduler embedded in the API.
Make a verified PostgreSQL backup from that frozen source. Restore it only into
the identified new Render database, using an appropriate `pg_dump`/`pg_restore`
version and Render's supported import procedure. Do not issue restore/drop
commands against the source database. Use a restricted transfer environment;
keep dumps and connection credentials out of Git, logs and shared artifacts.

Compare source and target counts for workspaces, memberships, workflows, runs,
steps, approvals, schedules, process instances, connections, manifests and audit
events. Verify encrypted connection records using the original keyring. Check
that object storage and uploaded-file URLs retained by those records are still
available; moving Postgres does not relocate external files.

The new job queue starts empty. Account for every old active, reserved, queued
and ETA job before switching brokers. Workflow schedules/outbox records are in
Postgres, but delayed Celery polling messages are not copied by a database
restore. For each active polling subscription, explicitly hand off its next
delivery to the new worker once, using its preserved subscription/workspace IDs
and `next_poll_at`; preserve cursor/checkpoint fields. Reconcile unfinished runs
through AURA's existing recovery controller. A database import by itself does
not establish a complete queue migration. Keep the old queue available until
this reconciliation is verified, with its consumers stopped.

## Update callbacks and verify

Resume the Render worker, then API, on the same tested commit after the restore
and queue handoff. The API performs its normal additive schema migration on
startup. The worker drains for up to 300 seconds on SIGTERM; one worker child
is configured for the initial 512 MB plan. Measure memory under a real pilot
before increasing concurrency.

Add the actual Render callback URLs to each configured native OAuth provider
application. Review `OAUTH_CALLBACK_OVERRIDES`: old Railway callback overrides
must not silently survive the move. Repoint incoming provider webhooks and
recovery-pipeline callbacks as applicable. Managed broker accounts still need
their existing credentials/references. Registered Frame.io MCP clients are
redirect-bound and may need fresh consent. PageProof's public client metadata
must be reachable at the new API's `/v1/oauth/mcp-client/pageproof`.

Run `bash scripts/smoke-production.sh https://ACTUAL_RENDER_API_HOST` and require
both `/health` and `/ready` to pass. Render's own health check uses `/health` so
API and worker startup order does not deadlock the first deployment. A green
Render deploy is not the full readiness check. Verify Clerk sign-in, restored
history, two-organization isolation, connector reads, one persisted workflow
and its worker receipt before redirecting the frontend. PageProof MCP exposes
metadata only; comment text still needs the supported export input described in
`content-approval.md`.

## Switch traffic and retain a rollback path

Set the GitHub repository Actions variable `AURA_API_URL` to the verified Render
API URL and run the Pages deployment. The browser API address is compiled at
build time. With the variable unset, Pages continues using the existing Railway
endpoint. Verify sign-in and the pilot from the published AURA page, then resume
scheduled/polling work on the new host. Do not resume the old consumers.

Before the new database accepts production writes, rollback can restore the old
Pages API setting and restart the old runtime against its original datastores.
After new writes occur, reconcile/transfer those changes before reverting;
switching back to the old database alone would lose them. Retain the old
resources and verified backup until the migration is accepted.

## References

- [Blueprint fields](https://render.com/docs/blueprint-spec)
- [Compute plans](https://render.com/docs/compute-plans)
- [Private networking](https://render.com/docs/private-network)
- [Postgres imports](https://render.com/docs/postgresql-backups)
- [Environment groups](https://render.com/docs/configure-environment-variables)

Schema/CLI validation checks configuration structure. It does not validate
secret values, import customer data, establish provider consent or prove a live
production migration.
