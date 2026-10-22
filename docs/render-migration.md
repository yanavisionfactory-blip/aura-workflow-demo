# Move AURA's control plane to Render

Status: deployment proposal; no paid Render resources, production data transfer, frontend switch, or Railway shutdown has been performed.

The existing four-tool simulation service already runs at https://aura-commerce-tools.onrender.com. It is separate from the FastAPI/Celery control plane. This Blueprint runs AURA's actual API and worker on Render with PostgreSQL and a durable Key Value queue. It does not proxy back to Railway.

## Reviewed target

Use the user-confirmed My Workspace in Oregon. The new AURA Control Plane project contains aura-control-api, aura-control-worker, aura-control-db and aura-control-queue. Existing Render services have different names and are not managed by this Blueprint.

The minimum proposed always-on compute is two 0.5c-512mb services, a 0.1c-256mb Postgres database with 5 GB storage, and a 256mb Key Value queue with noeviction. Render's published baseline for these four compute plans is $30/month before database storage, usage, taxes, and any workspace fees. This is a starting configuration, not a guaranteed capacity or total-cost ceiling. Confirm the Dashboard quote and approved spending limit before applying the Blueprint.

References checked October 22, 2026:
- https://render.com/docs/blueprint-spec
- https://render.com/docs/compute-plans
- https://render.com/docs/private-network
- https://render.com/docs/configure-environment-variables
- https://render.com/articles/production-rails-hosting-guide (the plan-price table applies to these compute plans, independent of the app framework)

## Required source access and secrets

The current Railway app connection returned UNAUTHORIZED / requires reauthentication. Reconnect that app before extracting the source database, configuration or credentials. Never paste secrets into a PR, commit, workflow output, browser screenshot or chat.

The source is project 5d7502dc-9152-4f6d-b1e2-6fe3ba7fbf8c, production environment 3f00203a-dff3-4808-9c6b-e18ea5912f48; API 4dae3f58-70dd-44e4-804f-e21441c4ec41 and worker 33c7fb6a-2fcd-446b-b8ff-969f6bcb93fd. Inspect the current configuration and source database service, version and size before provisioning. Verify the selected 5 GB target and PostgreSQL 18 are compatible; adjust the proposal first if necessary.

Provide the API's sync:false values securely in Render. Reuse the current CREDENTIAL_ENCRYPTION_KEY, SESSION_SIGNING_KEY, OpenAI key and Clerk identity settings. If the source verifies Clerk with JWKS instead of PEM, replace the CLERK_JWT_KEY entries with the existing CLERK_JWKS_URL setting before applying. Do not create a new encryption key for an existing encrypted database.

Copy all additional current runtime configuration that the app uses into the shared aura-control-runtime group, including any previous encryption keys, model selection, Nango, Pipedream, native OAuth clients, browser worker connection, release-signing keys and recovery callbacks. Preserve the current origin list if it contains additional approved origins. Service-level DATABASE_URL, REDIS_URL and PUBLIC_URL must continue to use the new Render resources. Never copy the old infrastructure URLs over those values.

## Controlled migration and validation

1. Review and merge this PR after CI passes. Keep the GitHub Pages frontend pointing to its current backend until the Render target is verified. Resource auto-deploy is off; use reviewed main commits.
2. Approve the Render cost, provision the new project, and configure secrets using Render's protected environment settings. Both API and worker share the same database, queue and credential keys. Keep target scheduling and workers paused while importing an existing database.
3. Arrange the cutover window. Quiesce the source API's write intake and scheduler, drain active Celery work, and pause the source worker. Preserve the original Railway resources for rollback. Do not run both schedulers against independent copies of the same workflow state.
4. Take a verified source PostgreSQL backup through an authorized connection. Restore into the new empty Render database, preserving application schema, rows, row-level-security policies and workflow/step IDs. Use the appropriate Postgres client version. Do not restore over an existing target database. Import over an internal Render connection or a narrowly approved temporary external IP rule; leave the final database private.
5. Compare workspace, connection, workflow, run, step, approval and audit counts. Verify the completed four-tool run fe396038-2b56-4ce4-acaa-1706c84ce6a7 and its four receipts. Check that the existing credential key decrypts stored connections without printing any credential values.
6. Update any registered OAuth/recovery callback origins required by the new API hostname. Review provider settings before changing them. The simulated MCP connectors themselves need no vendor credentials or callback change.
7. Start the Render API and worker with their preserved settings. Require both deploys live, a responding execution worker, and GET /ready passing; /health alone is not application readiness. Run scripts/smoke-production.sh against the actual Render URL.
8. Verify Clerk login, tenant isolation, an existing saved result, a new exactly-four-tool simulated run with Seller first, individual approvals, source reports, retained receipts, and draft-only outputs. Test a worker restart without repeating completed steps.
9. Set VITE_AURA_API_URL in .github/workflows/pages.yml to the verified Render API URL, rebuild the frontend, and verify the same saved run in the user's workspace. Existing source IDs are preserved by the database migration.
10. Keep Railway paused during verification. If rollback is required after new writes, reconcile the target state before routing back; an old database snapshot cannot safely replace later writes. Decommission Railway only after an explicitly reviewed retention/cutover decision.

The API binds 0.0.0.0:$PORT and receives termination signals through exec. The worker uses concurrency 1 on the smallest starting compute plan and a 300-second drain window. PostgreSQL connection URLs from Render are normalized to SQLAlchemy's installed async psycopg driver. The queue and database deny public inbound access. AURA's existing authorization and exact action approvals remain enabled.
