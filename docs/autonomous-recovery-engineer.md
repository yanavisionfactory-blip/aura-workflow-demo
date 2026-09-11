# Autonomous Recovery Engineer

This release completes AURA's backend recovery architecture. Every persisted run-status
change is now a request to the Run Supervisor; a SQLAlchemy flush guard rejects legacy
components that assign `WorkflowRun.status` directly. The same transaction records a
`run.transitioned` audit event and, when needed, a plan, execution, or memory outbox
intent.

The result is browser-independent recovery: closing the demo tab does not stop planning,
connection recovery, execution, receipt verification, or the elected recovery scheduler.
Technical failures stay backstage as `recovering`. A user is interrupted only for a
decision AURA cannot safely make: authentication/CAPTCHA, account or exact-resource
selection, plan or consequential-action approval, or an external effect whose outcome
cannot be reconciled.

## Implemented capability map

| Capability | Permanent backend behavior |
| --- | --- |
| Central run-state ownership | `run_supervisor.transition_run` is the only authorized persisted mutation path. The model flush hook rejects bypasses and emits audit/outbox rows atomically. |
| Connection refresh and capability probes | Execution preflight refreshes managed and native OAuth connections, standards-based custom OAuth tokens, rediscovered OpenAPI/MCP-style manifests, and a live non-auth-failure endpoint probe. A pass is immutable-plan-bound and expires after `CONNECTION_PROBE_TTL_SECONDS`. |
| Repair malformed plans and arguments | The Recovery Engineer decodes fenced JSON, converts keyed step objects to arrays, restores mechanical required fields, normalizes graphs and aliases, then recompiles connector contracts. Invalid inputs never reach a provider. |
| Replan while preserving completed steps | A candidate replan is merged with the exact serialized completed checkpoints. Any changed or missing completed checkpoint is restored, and known or uncertain writes are never replayed. |
| Substitute equivalent tools/providers | Substitution is limited to non-consequential reads already present in the approval permission snapshot. Permission scope, typed output validation, evidence contract, dependencies, and literal resource identity must remain equivalent. |
| Standalone Recovery Engineer | An elected scheduler sweep classifies saved failures into typed phases/categories, selects only typed repair tools, records bounded attempts, and redispatches through the transactional outbox. Human blockers are excluded. |
| Isolated automatic code repair | A content-free incident can trigger the GitHub recovery workflow. Codex receives phase/category/fingerprint only. The gate permits a small `backend/app/` diff and rejects tests, workflows, dependencies, deployment, security, identity, database, configuration, secrets, binaries, symlinks, and oversized changes. |
| Tests → canary → rollback | The workflow compiles and runs the complete backend suite, builds the frontend integration bundle, opens an immutable repair PR, deploys a separate Railway canary, requires both `/health` and `/ready`, then deploys production. A failed production health gate redeploys and verifies the exact baseline SHA. Only a promoted repair is merged. |
| Golden workflow matrix | `backend/tests/golden/recovery_matrix.json` covers planning, connections, execution, verification, delivery, human gates, repair-budget escalation, and code isolation. `test_recovery_golden_matrix.py` executes the matrix plus transition ownership, plan/argument repair, checkpoint preservation, equivalent-provider constraints, sandbox boundaries, and signed callbacks. |

## Recovery lifecycle

1. The Run Supervisor checkpoints the failed phase, category, stable fingerprint, attempt
   count, completed steps, and next allowed action. Raw credentials and provider payloads
   are excluded.
2. Safe workflow repair is tried first: refresh, normalize, receipt read-back, retry, or
   replan of only the remaining steps. Each attempt is bounded and delayed through the
   outbox.
3. Repeatable application defects escalate to an isolated `RecoveryIncident`. Persistent
   external outages exhaust into an internal quarantine rather than looping, spending, or
   claiming success forever.
4. The isolated runner may propose a source repair but cannot deploy it directly. Static
   boundaries and the full test matrix must pass before a canary exists.
5. Canary readiness gates production. Failed production readiness automatically restores
   the exact baseline commit and proves its health. The runner sends a five-minute HMAC
   timestamped callback; a promoted incident requeues the saved run from its checkpoint.
6. A run is complete only after the existing final outcome verifier accepts evidence from
   persisted provider receipts.

## Required activation configuration

The runtime is safe when the isolated pipeline is unconfigured: code incidents remain in
`awaiting_sandbox` and are not repeatedly dispatched. To activate automatic repair, set
the following values.

### Railway API service

| Variable | Value/purpose |
| --- | --- |
| `RECOVERY_ENGINEER_ENABLED` | `true` |
| `MAX_RECOVERY_ENGINEER_ATTEMPTS` | Bounded workflow-repair attempts; default `3` |
| `CONNECTION_PROBE_TTL_SECONDS` | Maximum age of a plan-bound successful probe; default `60` |
| `RECOVERY_GITHUB_REPOSITORY` | `yanavisionfactory-blip/aura-workflow-demo` |
| `RECOVERY_GITHUB_TOKEN` | Fine-grained token able to dispatch workflows in that repository; never expose it to the browser |
| `RECOVERY_PIPELINE_CALLBACK_SECRET` | Random callback HMAC secret; identical to the GitHub Actions secret |

### GitHub Actions secrets and environments

| Secret | Scope |
| --- | --- |
| `OPENAI_API_KEY` | Repository secret used only by `openai/codex-action` in the isolated runner |
| `RAILWAY_TOKEN` | Recovery canary and production environments |
| `RAILWAY_PROJECT_ID` | Railway project identifier |
| `RAILWAY_CANARY_SERVICE_ID` / `RAILWAY_CANARY_ENVIRONMENT_ID` / `RAILWAY_CANARY_URL` | Dedicated canary service, isolated environment, and public health URL |
| `RAILWAY_PRODUCTION_SERVICE_ID` / `RAILWAY_PRODUCTION_ENVIRONMENT_ID` / `RAILWAY_PRODUCTION_URL` | Production service, environment, and health URL |
| `RECOVERY_PIPELINE_CALLBACK_SECRET` | Same value as Railway runtime configuration |

Create GitHub environments named `recovery-canary` and `recovery-production`. The canary
must use separate non-customer data stores and no production provider credentials. Keep
the workflow file on the default branch because GitHub accepts `repository_dispatch`
only there; the repair checkout and generated PR deliberately target
`python-control-plane`, the Railway deployment branch.

## Release acceptance

A release is accepted only when all of the following are true:

- no production module outside `run_supervisor.py` assigns `run.status`;
- the backend suite and golden matrix pass;
- the frontend production build passes;
- the workflow YAML parses and references the production control-plane base;
- the deployed `/ready` response reports fresh recovery-scheduler ticks, PostgreSQL,
  Redis, identity, OpenAI, encryption, and origin checks as ready;
- an injected safe test incident reaches canary, and a forced health failure demonstrates
  baseline rollback before automatic repair is enabled for live incidents.
