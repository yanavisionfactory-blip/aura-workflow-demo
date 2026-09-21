# Activating AURA isolated code repair

AURA runtime recovery and source-code recovery are separate systems. Runtime recovery
is always bounded inside the durable workflow engine. Source-code recovery is disabled
until an operator provisions the isolated GitHub/Railway release channel and explicitly
sets `RECOVERY_CODE_REPAIR_ENABLED=true`.

## Security contract

The production API sends only incident UUIDs, a typed phase/category, and a content-free
fingerprint to GitHub. It never sends prompts, provider payloads, credentials, receipts,
or raw errors. Codex runs in an isolated checkout without production credentials. A
deterministic gate permits edits only under `backend/app/`, blocks security, identity,
database, configuration, deployment, workflow, and test changes, and caps the diff.

Every accepted repair must pass the complete backend matrix and frontend build, deploy
to a separate Railway canary, pass `/health` and `/ready`, and then pass production
health after promotion. Failed promotion deploys the recorded baseline. Only a promoted
repair is squash-merged. The pipeline signs its result with HMAC; production resumes the
saved workflow checkpoint only after verifying that callback.

## GitHub repository configuration

Create the GitHub environments `recovery-canary` and `recovery-production`. Do not add a
required human reviewer if the intended contract is unattended recovery. Add these
Actions secrets without placing their values in source, logs, tickets, or chat:

- `OPENAI_API_KEY`
- `RAILWAY_TOKEN`
- `RAILWAY_PROJECT_ID`
- `RAILWAY_CANARY_SERVICE_ID`
- `RAILWAY_CANARY_ENVIRONMENT_ID`
- `RAILWAY_CANARY_URL`
- `RAILWAY_PRODUCTION_SERVICE_ID`
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID`
- `RAILWAY_PRODUCTION_URL`
- `RECOVERY_PIPELINE_CALLBACK_SECRET`

The canary service/environment pair must not equal the production pair. The callback
secret must be at least 32 random characters and must exactly match the production API
variable of the same name.

The workflow needs repository Actions enabled with read/write workflow permissions so
its scoped `GITHUB_TOKEN` can create the recovery branch and pull request and squash-merge
only after canary promotion.

## Production API configuration

Set these Railway variables on both API and worker where settings are loaded:

- `RECOVERY_GITHUB_REPOSITORY=yanavisionfactory-blip/aura-workflow-demo`
- `RECOVERY_GITHUB_TOKEN=<fine-grained token stored only in Railway>`
- `RECOVERY_PIPELINE_CALLBACK_SECRET=<same random secret as GitHub Actions>`
- `RECOVERY_CODE_REPAIR_ENABLED=true`

For a pilot, the fine-grained token needs access only to this repository and permission
to create a repository dispatch (`Contents: read and write`). Replace it with a dedicated
GitHub App installation before broad production rollout. Never reuse a personal all-repo
classic token.

Enable the final boolean only after every other value and canary target is present. Once
enabled, `/ready` fails closed if the local dispatch/callback configuration is incomplete.

## Activation proof

Run the `AURA isolated recovery pipeline` manually with synthetic UUIDs and category
`activation_probe`. A successful preflight proves secret presence and target isolation;
the repair job is expected to stop because no reproducible source defect exists. Then
exercise a controlled test-only defect in a non-production branch and require evidence
for branch creation, tests, canary health, signed callback, promotion or rollback, and
checkpoint resume before declaring the feature active.
