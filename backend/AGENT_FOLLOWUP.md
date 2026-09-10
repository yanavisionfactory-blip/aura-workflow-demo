# Agent follow-up: repair, provider outcomes, semantic memory

## Automatic replanning

The executor invokes a bounded repair planner after an eligible read failure.
It can propose a replacement read operation/arguments for one failed step, using
the original request, approved plan, connector schemas and accepted prior outputs.
A run gets at most two repair-planner attempts, counted durably before model calls.

If the proposal exactly matches an already approved primary/reduced-scope/fallback
variant, the executor can apply it and continue automatically without changing the
approved plan hash. Any other valid candidate becomes a new draft plan version
and waits for approval. Completed steps and their provider receipts remain intact;
re-approval cannot rewrite or reset those completed actions. Provider writes,
unknown write outcomes, policy violations, and cancelled runs are ineligible for
automatic argument repair. This is bounded single-step replanning, not arbitrary
rewriting of the entire workflow or silent expansion of permissions.

## Connector-specific outcomes

Supported action/read-back pairs:

| Action | Read-back | Deterministic evidence |
| --- | --- | --- |
| Gmail send | `gmail.get` | Message ID, recipient, subject, plain-text body, SENT label |
| Calendar create | `calendar.get` | Event ID, requested title, start/end, description, non-cancelled status |
| Jira issue create/update | `jira.issue.get` | Issue ID/key and requested fields |
| Notion page create/update | `notion.page.get` | Page ID, requested properties/parent/archive state |

Checks use only read operations present in both the approval permission snapshot
and the current enabled connection. They also enforce connector trust and verified
capability manifests. They retry reads up to three times for transient errors or
eventual consistency, never the original write. Receipts are committed first, then
read-back evidence is stored with the step and supplied to the semantic critic.
A missing permission or mismatched/insufficient result pauses verification. A
successful read-back is reused on resume, with the audit event recording when it
was observed. It is evidence of that observation, not continuous state monitoring.

Gmail checks confirm the sent-mail copy, not delivery to another person's inbox.
Notion page reads do not establish requested child-block content: requests with
children remain unverified until that evidence can be supplied. Unknown connectors
continue through the existing semantic verifier and are labeled unsupported for
deterministic read-back; no universal provider-verification claim is made.
Existing Google connections may need capability refresh/reconnection and a new
plan approval to include the new `gmail.get` / `calendar.get` operations. No scopes
or permissions are expanded silently.

The new Google read handlers follow the official
[Gmail message retrieval](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get)
and [Calendar event retrieval](https://developers.google.com/workspace/calendar/v3/reference/events/get)
contracts.

## Semantic memory

A completed, outcome-verified run with a recorded user owner is indexed after
completion. Its request and verified deliverable are embedded using
`MEMORY_EMBEDDING_MODEL` (default `text-embedding-3-small`) through the existing
OpenAI account. Indexing failure does not change a completed run's outcome.
The `workflow_memories` table stores embeddings, content hash, model, owner and
source run; the normal startup migration creates it and enables forced workspace
row-level security. Application queries additionally filter by authenticated user.
Tenant context is now restored after every database checkpoint transaction.

- `POST /v1/memory/search`: `{ "query": "financial performance", "limit": 5,
  "minimum_score": 0.25 }`. Returns cosine-ranked results with source run IDs and
  step keys. Search considers the newest `MEMORY_CANDIDATE_LIMIT` owned memories
  (default 200; maximum 1000), not the entire history. Embedding-model mismatches,
  invalid vectors and no-longer-verified sources are excluded.
- `POST /v1/memory/index/{run_id}`: explicitly indexes/reindexes an eligible run,
  useful after a transient embedding failure. Older runs without recorded ownership
  are not eligible.
- `DELETE /v1/memory/{memory_id}`: clears indexed text/embedding and writes a
  tombstone so automatic indexing cannot resurrect it. This removes search memory,
  not the original workflow run or copies explicitly reused elsewhere.
- Reuse stays explicit through the existing `memory_run_id` + `memory_bindings`
  run-creation fields. Similarity search does not silently inject data into actions.

Embeddings incur model usage. Agent-call cost estimates do not include embedding
billing. Search returns a service-unavailable response if embedding service fails;
it does not substitute fabricated scores or a keyword search. The bounded SQL/JSON
vector scan is suitable for the initial memory volume; a vector index and paginated
candidate retrieval can follow if scale requires them.

## Validation

Tests cover scope-preserving automatic repairs, draft approval for changed reads,
write-repair rejection, immutable completed actions on re-approval, provider
resource/field mismatches, permission gates and read-only retries, semantic ranking,
user/workspace isolation, forgotten-memory tombstones and invalid embeddings.
PostgreSQL CI additionally checks advisory locks, tenant-context restoration across
commits, and the memory-table migration/RLS policy. Provider and embedding responses
in tests are simulated; no customer messages or records are sent by these tests.
