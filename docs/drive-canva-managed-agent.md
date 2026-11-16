# Managed OpenAI agent runtime for AURA

## Scope and activation

When enabled, every workflow uses OpenAI's managed agent sessions for planning,
execution decisions, text composition, verification and recovery. The user's
chosen sources and destinations remain authoritative across Canva, Google apps,
CRM, email, research and other connected providers. Specialized multimodal and
built-in web-search calls keep their native model/tool contracts under the same
workflow supervisor; image/audio inputs are never flattened into text. AURA's provider gateway, account binding, immutable plans,
approval checks, completed checkpoints and uncertain-write reconciliation remain
authoritative. The managed reasoning sessions receive no provider credentials,
MCP servers, browser, shell or direct write tools.

Set `MANAGED_AGENTS_ENABLED=true` on the API and execution-worker services only
after the isolated canary succeeds. Defaults: `MANAGED_AGENTS_MODEL=gpt-6-astra`,
`MANAGED_AGENTS_TIMEOUT_SECONDS=90`, `MANAGED_AGENTS_SPEND_LIMIT_CENTS=100` per
session. Existing per-delivery time and model-call limits still apply. No
`PLANNER_MODE` or global agent-execution flag change is necessary.

The existing server `OPENAI_API_KEY` must permit `api.agents.read`,
`api.agents.write` and `api.responses.write`. Startup makes one synthetic,
bounded, tool-free turn and deletes that readiness session afterwards. `/ready`
requires `checks.managed_agents=true` when enabled; a configured string alone
cannot pass this check. Canary mode still forbids customer routes and migrations.

Managed sessions retain the input evidence in OpenAI; they are not equivalent to
the existing `store=False` Responses calls. Apply the application's data retention
policy to these sessions. Audit rows contain only opaque session/turn identifiers,
call fingerprints, model identity and usage; no evidence text or credentials.

## Recovery contract

Each call is keyed by workspace, run, agent, model, instructions, bounded input and
output schema. Its session ID is committed in a tenant-scoped audit row before
submitting input. Event submission uses the API's idempotency key. After a lost
acknowledgement or worker restart, AURA checks the saved session's root turn and
retrieves its final output instead of repeating submitted work. An interrupted
session creation can leave an empty idle session, but cannot start model work or
any external effect. Run execution locks serialize run deliveries.

Only a completed root turn with one completed final message that validates
against the original output schema is accepted. Idle sessions, commentary,
failed/cancelled turns and unexpected required actions are not success. AURA
does not silently replace a failed managed composition with an unverified result.
Existing bounded deterministic manager fallbacks remain separately labelled.

## Live acceptance across workflows

Run the synthetic readiness probe, inspect real managed-session metrics, and
exercise read-only tasks outside Canva (for example a source-grounded report).
Regression tests cover CRM, Calendar, email drafts, Sheets and Canva routing,
shared call budgets, multimodal inputs and tenant isolation. Use only already
authorized provider writes in live acceptance; enabling this runtime grants no
new account permissions or blanket send authority.

### Drive → Canva acceptance

Use an isolated synthetic Drive parent with Unicode and an emoji in its name,
containing a project child folder. Put two relevant text documents in the child,
one irrelevant keyword distractor, and one contradictory document outside it.
Keep expected markers and values in the test oracle, not the execution prompt.

Ask AURA to read the exact parent/child path, create four populated presentation
pages in **Canva**, and return the created design's edit/view link. Do not request
sharing, messaging, source edits or Google output files. Review the visible plan:

1. Semantic Drive discovery preserves the path and reads actual contents.
2. `report.compose` receives verified `sources` with `presentation=true`.
3. `canva.presentation.create` receives `layout=slides` and the composed phases.
4. Import completion and final design readback use the actual returned job/design
   IDs. Polling an existing import is a read; it must not create a second import.

| Case | Required evidence |
| --- | --- |
| Normal run | Relevant source markers; correct folder IDs; one populated Canva design; real Canva URL |
| Scope | Outside-folder conflicting value excluded; irrelevant keyword file not used as evidence |
| Destination | Canva remains the destination; no Google Slides/Docs/Sheets output creation |
| Agent | Plan and composition carry real managed session IDs; metrics identify `openai_agents_api` |
| Model disconnect | Existing session/turn resumed, no repeated submitted turn |
| Provider timeout | Existing job reconciled; no blind repeat of import/create |
| Missing authorization | Specific account/permission blocker, no fabricated success |
| Visual/content check | Open the Canva design; four pages, readable text, expected content; inspect/export through allowed operations |

Test doubles prove control flow, not Canva or OpenAI account access. A release is
accepted only after a live run and its saved provider receipts pass this matrix.
The startup synthetic probe certifies API access only, not Drive → Canva success.

Rollback: turn `MANAGED_AGENTS_ENABLED` off and redeploy both API and worker.
Keep recorded provider receipts and managed sessions; never recreate an uncertain
Canva write while changing runtimes.

References: [Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview),
[sessions and events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events),
[required key permissions](https://developers.openai.com/api/docs/guides/agents-api/quickstart).
