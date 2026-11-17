# Economy runtime and model request limits

Managed reasoning for every planning and composition call can exhaust a prepaid
API balance. Spend alerts do not necessarily enforce a budget. Repeated top-ups
alone do not address unbounded recovery or expensive default routing.

The existing direct Responses/Agents SDK path uses gpt-5.4-mini and retains the
same planner schema validation, source checks, action approvals, idempotency and
saved-receipt verification. It does not automatically escalate to a managed model.

Apply these non-secret settings to the isolated canary first:

```text
MANAGED_AGENTS_ENABLED=false
OPENAI_MODEL=gpt-5.4-mini
DIRECT_MODEL_PROBE_ENABLED=true
MAX_MODEL_CALLS_PER_DELIVERY=16
MAX_MODEL_CALLS_PER_RUN=40
MODEL_MAX_OUTPUT_TOKENS=12000
```

Require the exact candidate release to pass `/ready`, including `direct_model`,
before applying the same settings to the production worker and API. The direct
probe performs one tool-free structured planner request with a 2,048-token output
limit. Zero API credit must fail this gate; configured credentials alone are not
proof that planning works. Keep the existing production release if the gate fails.

Every bounded model call in a traced workflow reserves a durable audit slot before
network execution. Planning, execution, retries and recovery share the same run
limit; restarts and manual retries cannot replenish it. Failed/ambiguous calls
keep their reservation. PostgreSQL advisory transaction locks serialize admission
across workers without locking the caller's workflow row. Admission storage errors
stop the call. The ledger stores only counters, run/workspace IDs and limits.

Direct structured calls and SDK agents cap output at 12,000 tokens, preserving
smaller specialist limits. Transport retries are disabled for workflow model
clients; retries must go through AURA's normal bounded paths. Local run limits and
provider quota failures require operator action and never request source-code repair.

These controls limit requests and generated tokens; they are **not a guaranteed
dollar cap**, since input tokens, images, audio, search tools and pricing also affect
charges. They are per run, not an organization-wide daily budget. A new run has a
new allowance. Managed sessions retain their own output contract; keep that runtime
disabled for the economy rollout. Confirm actual cost and quality with one fresh
synthetic Drive-to-Canva workflow after the balance is positive, then test the pilot
against its authorized materials. Never repeat previously completed provider writes.
