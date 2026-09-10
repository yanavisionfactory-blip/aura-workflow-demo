import test from 'node:test';
import assert from 'node:assert/strict';
import {
  alternativeRecoveryPrompt,
  needsRecovery,
  recoveryForRun,
  startupRunDisposition,
} from '../src/lib/runRecovery.mjs';

const run = (patch = {}) => ({ id: 'saved-run', status: 'waiting_for_action',
  steps: [{ id: 'done', status: 'completed', consequential: false },
    { id: 'failed', position: 1, status: 'failed', consequential: false }],
  plan: { steps: [{}, {}] }, ...patch });

test('all real interrupted states route to recovery, not final results', () => {
  for (const status of ['waiting_for_action', 'blocked', 'failed']) assert.equal(needsRecovery(status), true);
  for (const status of ['completed', 'awaiting_approval', 'running', 'cancelled']) assert.equal(needsRecovery(status), false);
});

test('startup monitors active work without hijacking the home screen for human decisions', () => {
  for (const status of ['queued', 'planning', 'running']) {
    assert.equal(startupRunDisposition({ status }), 'monitor');
  }
  for (const status of ['awaiting_approval', 'waiting_for_action', 'blocked', 'failed']) {
    assert.equal(startupRunDisposition({ status }), 'attention');
  }
  for (const status of ['completed', 'cancelled', 'unknown']) {
    assert.equal(startupRunDisposition({ status }), 'ignore');
  }
});

test('alternative recovery plans preserve safety boundaries and user direction', () => {
  const saved = run({
    prompt: 'Review creator candidates',
    error: 'client_id=SECRET-EXAMPLE',
  });
  const automatic = alternativeRecoveryPrompt(saved);
  assert.match(automatic, /different policy-safe approach/);
  assert.match(automatic, /do not repeat any external action whose outcome is uncertain/);
  assert.equal(automatic.includes('SECRET-EXAMPLE'), false);

  const userDirected = alternativeRecoveryPrompt(saved, 'Use the second verified Google account');
  assert.match(userDirected, /Use the second verified Google account/);
  assert.match(userDirected, /ask for approval before every new consequential action/);
});
test('read retries target the saved failed step and keep completed work', () => {
  const r = recoveryForRun(run());
  assert.equal(r.stepId, 'failed'); assert.equal(r.index, 1); assert.equal(r.canRetry, true);
  assert.equal(r.canSkip, false); assert.equal(r.buttonLabel, 'Retry this step');
});
test('writes and unknown consequential classification never offer replay', () => {
  for (const consequential of [true, undefined]) {
    const r = recoveryForRun(run({ steps: [{ id: 'write', status: 'failed', consequential }] }));
    assert.equal(r.canRetry, false); assert.equal(r.buttonLabel, 'Check status');
  }
});
test('skip is only offered for an explicitly optional failed step', () => {
  assert.equal(recoveryForRun(run({ plan: { steps: [{}, { optional: true }] } })).canSkip, true);
  assert.equal(recoveryForRun(run({ status: 'blocked', plan: { steps: [{}, { optional: true }] } })).canSkip, false);
});
test('retry budget and unknown network state prevent more mutations', () => {
  const exhausted = recoveryForRun(run({ execution_context: { __aura_recovery__: { failed: 3 } } }));
  assert.equal(exhausted.canRetry, false); assert.match(exhausted.fix, /retry limit/);
  assert.equal(recoveryForRun(run({ status: 'unknown' })).canRetry, false);
});
test('configuration errors explain operator action without leaking raw diagnostics', () => {
  const r = recoveryForRun(run({ error: 'connection configuration client_id=SECRET-EXAMPLE' }));
  assert.equal(r.canRetry, false); assert.match(r.why, /Signing in again/);
  assert.equal(JSON.stringify(r).includes('SECRET-EXAMPLE'), false);
});
test('final verification resumes review only, without a completed step ID', () => {
  const r = recoveryForRun(run({ steps: [{ id: 'done', status: 'completed' }], result: { verification: { passed: false } } }));
  assert.equal(r.canRetry, true); assert.equal(r.stepId, null);
  assert.equal(r.buttonLabel, 'Check the final result again');
});
test('generic failures do not invent a cause or an applied fix', () => {
  const r = recoveryForRun(run());
  assert.match(r.why, /doesn't identify a specific cause/);
  assert.equal(r.buttonLabel.includes('Apply fix'), false);
});

test('Google resource authorization blockers explain the exact recovery path', () => {
  const result = recoveryForRun(run({
    steps: [{
      id: 'resolve-sheet',
      position: 0,
      status: 'failed',
      consequential: false,
      tool_slug: 'google',
      operation: 'drive.spreadsheet.resolve',
      error: 'This app connection needs your attention before AURA can continue.',
    }],
  }));
  assert.match(result.what, /Google Drive resource/);
  assert.match(result.why, /connected Google account/);
  assert.match(result.fix, /reconnect.*both original sheets/i);
  assert.equal(result.buttonLabel, 'Retry after reconnecting');
  assert.equal(JSON.stringify(result).includes('12Chkm'), false);
});

test("backend proof of no dispatch allows a consequential preparation retry", () => {
  const run = {status: "waiting_for_action", steps: [{id: "s", status: "failed", consequential: true,
    recovery: {phase: "before_action", can_retry: true}}]};
  const result = recoveryForRun(run);
  assert.equal(result.canRetry, true);
  assert.match(result.what, /before sending/);
  assert.doesNotMatch(result.fix, /already have happened/);
});

test("a dispatched write remains protected from duplicate retry", () => {
  const result = recoveryForRun({status: "waiting_for_action", steps: [{id: "s", status: "failed", consequential: true,
    recovery: {phase: "after_dispatch", can_retry: false}}]});
  assert.equal(result.canRetry, false);
  assert.match(result.fix, /already have happened/);
});

test("structured OAuth blockers offer the exact reconnect action", () => {
  const result = recoveryForRun(run({
    blocker: {
      code: "oauth_required",
      action: "reconnect_account",
      message: "Google Workspace authorization is no longer usable.",
      tool_slug: "google",
      connection_id: "google-connection",
      connected_account: "owner@example.com",
    },
  }));
  assert.equal(result.blockerAction, "reconnect_account");
  assert.equal(result.toolSlug, "google");
  assert.equal(result.connectionId, "google-connection");
  assert.equal(result.connectedAccount, "owner@example.com");
  assert.equal(result.canRetry, true);
  assert.equal(result.buttonLabel, "Reconnect account");
});

test("resource ambiguity stops for a human choice instead of inventing a retry", () => {
  const result = recoveryForRun(run({
    blocker: {
      code: "resource_ambiguous",
      action: "choose_resource",
      message: "AURA found two spreadsheets named Creator Outreach.",
      resource_name: "Creator Outreach",
    },
  }));
  assert.equal(result.canRetry, false);
  assert.equal(result.canSkip, false);
  assert.equal(result.resourceName, "Creator Outreach");
  assert.match(result.why, /two spreadsheets/);
});

test("uncertain external effects never expose a replay button", () => {
  const result = recoveryForRun(run({
    blocker: {
      code: "external_effect_uncertain",
      action: "inspect_run",
      message: "The provider may have received this action.",
      step_id: "failed",
    },
  }));
  assert.equal(result.stepId, "failed");
  assert.equal(result.canRetry, false);
  assert.match(result.fix, /provider result/);
});
