# Autonomous processes

AURA processes coordinate multiple already-approved workflows as one durable business process.
They add a lifecycle above workflows; they do not replace workflow planning, schedules, approvals,
connector checks, execution preflight, or result history.

The responsibility boundary is:

> The process coordinator decides when and which declared stage follows. The workflow runtime
> decides how to execute that approved stage. The safety layer decides what is currently allowed.

## Durable records

- `process_definitions` store the objective, shared context, trigger, ordered stage graph, approval
  mode, and failure policy.
- `process_instances` store one live business case and its current stage, timer, and state.
- `process_events` provide workspace-scoped idempotency for business events and scheduled starts.
- `process_stage_runs` link every stage attempt to its normal `workflow_runs` record.

Process v1 permits only declared, forward-only transitions. A stage can start immediately, after a
bounded wait, or after a named event. Definitions can start manually, from a calendar trigger, or
through `POST /v1/process-events`.

## Runtime behavior

The elected API recovery loop claims due process definitions and instances with database row locks.
For each stage it clones the exact approved source workflow through the existing governed run
builder. Policy, connector health, operation certification, per-write approval, idempotency, and the
transactional dispatch outbox therefore remain unchanged.

A completed workflow advances the process to its declared next stage. Its bounded result, variables,
and structured step outputs become `process_context` for the following workflow together with the
user-approved transition instructions. A failed or cancelled workflow follows the definition's
explicit policy: pause for review, retry the same approved stage up to three times, or stop and mark
the case for notification. Pause prevents the process from advancing after the current workflow.
Stop prevents all later stages but does not pretend that an already-dispatched external action was
cancelled.

Before every automatic run AURA rechecks that the original creator is still an active workspace
member and still has the role required for consequential automation. Revoked or reduced authority
falls back to review. External agents receive no additional connector credentials or execution
authority from a process.

## User surfaces

Successful workflow results retain **Run again**, **Schedule**, and **New workflow**. Process creation
lives under **My workflows → Workflows**: **Build a process** enters multi-select mode, requires at
least two completed approved workflows, and then opens a builder for drag ordering, editable context
handoffs, shared instructions, a manual/event/calendar trigger, approval mode, and failure policy.
The separate **Processes** tab exposes definitions, stages, cases, edit, run, pause, resume, and stop
controls.
