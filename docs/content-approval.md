# Content approval pilot with Frame.io and PageProof

The pilot covers intake, initial review, supervisor review, a revision loop,
final sign-off, and the handoff for publishing or scheduling. The participant's
rule is that no content goes live without the supervisor's direct approval.
The workflow applies to marketing material including blog posts, emails,
LinkedIn posts, and Google content. The interview names Frame.io and PageProof
but does not assign either product to a particular stage or require both for
every asset. Confirm that mapping for the selected test item.

AURA currently supports a bounded part of this process: preparing a revision
brief from Frame.io comments and an attached PageProof comments export. It
retains source and version identifiers and waits for both inputs before
drafting the brief. The editor makes the changes, and the supervisor makes the
review and approval decisions. AURA does not edit the audiovisual asset or
provide final sign-off.

## Six-stage sandbox run

Use one authorized, non-sensitive test item in the user's own provider
workspace. This is a sandbox exercise on the existing AURA service, not a
claim that a separate infrastructure environment has been provisioned. Leave
publishing and scheduling out of the executable plan; the last deliverable is
a handoff package retained inside AURA. Do not use production client material
or send invitations as a side effect of setup.

| Stage | Pilot action | Required evidence or decision |
| --- | --- | --- |
| Intake | Record the draft, intended channel, deadline, review criteria, creator, initial reviewer, and supervisor. Bind each chosen proofing source to its exact asset/version. | Completed [intake record](pilots/content-approval/intake-template.json); missing IDs remain null until selected. |
| Initial review | Read the selected Frame.io file/comments and import the matching PageProof comments print sheet. Prepare a source-linked review and revision brief in AURA. | Successful feedback receipts; brand voice, accuracy, and messaging criteria; conflicts and unanswered questions retained. |
| Supervisor review | The named supervisor reviews the actual brief and draft, then records changes requested or a decision to proceed. | Human decision tied to the exact version. Approval to execute an AURA plan is not content approval. |
| Revision loop | The creator produces a real revised file. Re-run the read/import/brief phase for that new version, comparing with the prior action list. | New file/version references and fresh feedback; no placeholder upload, invented resolution, or automatic carryover of approval. |
| Final sign-off | The supervisor explicitly approves the current version in the designated review system. | Approver, exact version, decision, timestamp, and evidence reference. Completed comments alone are insufficient. |
| Handoff | Prepare the approved file reference, channel, proposed scheduling details, and sign-off evidence inside AURA. | Verified sign-off for that version; publishing/scheduling remain manual during this pilot. |

AURA plans are forward-only dependency graphs. Run the automated feedback phase
once per review round, with human checkpoints between runs. Do not model a
human revision loop as invented provider calls or claim a persistent supervisor
approval gate has been implemented. The current native Frame.io connection has
read operations only; provider uploads and final approvals remain human actions.

The first-run [prompt template](pilots/content-approval/first-review-prompt.txt)
is a preparation artifact. Replace every bracketed field with selected evidence
and attach the actual export before creating an executable plan. It is not a
completed workflow and cannot be run with placeholders.

## Readiness before the first live run

- Frame.io: the intended Adobe identity has access to the intended Frame.io
  account. AURA's authenticated identity/account probe succeeds, followed by a
  scoped file/comment read. Record a refresh check separately.
- PageProof: a team member authorizes AURA and a metadata read succeeds. Its
  comments print sheet is still required. If registration remains blocked,
  explicitly agree an export-only PageProof phase and label it accordingly;
  do not describe that as a connected PageProof test.
- Inputs: the draft and review criteria, exact source IDs/versions, reviewer
  roles, deadline with timezone, and matching comments export are present.
- Boundaries: the plan contains only the chosen reads/import and in-AURA brief.
  No upload, external comment, email, approval, publishing, or scheduling action
  is implicitly authorized by preparing or executing that plan.
- Later rounds: the creator provides a real revised file, and the supervisor
  provides version-specific approval evidence before the handoff phase.

Meeting deadlines was the concrete success criterion in the interview. Capture
intake-to-sign-off elapsed time, active handling time, revision rounds, manual
handoffs, missed/conflicting comments, and deadline met/missed as proposed pilot
measurements. Establish the manual baseline and target with the participant;
no numerical improvement target was agreed in the call.

## Connect and select evidence

If a provider rejects AURA before sign-in, use the operator instructions in
[`backend/docs/proofing-oauth-setup.md`](../backend/docs/proofing-oauth-setup.md).
That guide covers exact callback registration and the supported server-side
configuration for provider-issued MCP clients.

1. In **Connect → Find apps**, choose **Frame.io**. With the native credentials
   configured, new connections use Adobe consent and the read-only Frame.io V4
   API. Select the identity and account containing the test asset. This is a
   separate route from Frame.io MCP; see the
   [native Adobe setup](../backend/docs/frameio-adobe-setup.md). Existing MCP
   connections retain their separate registration and grant.
2. Choose **PageProof** to read proof metadata through its official MCP service.
   PageProof documents that this connection excludes comment text and file
   imagery. It cannot replace the feedback input.
3. In PageProof, generate a comments print sheet for the chosen proof/version.
   Attach the PDF in AURA with **Attach docs**, and state the proof ID and version
   in the task. Searchable PDFs, UTF-8 text, CSV and JSON exports are supported;
   image-only, encrypted, empty and oversized exports stop with an explanation.
4. Supply the exact Frame.io asset/version. Ask AURA to read its comments and
   replies, import the attached PageProof comments, retain page/time references,
   flag conflicting requests, and prepare a revision brief **inside AURA**.
   The native route needs the account UUID and exact file UUID, not a version
   stack alias or a guessed latest file.
5. Review the brief. Any external comment or upload retains the normal action
   preview and approval. Supply a real revised file before re-review; a
   placeholder cannot satisfy that step. Verify the actual version and obtain
   the supervisor's approval evidence through the designated review system;
   do not infer approval from a successful read or comment completion.

An import receipt identifies `input_mode=user_supplied_export` and
`vendor_api_called=false`; its SHA-256 and PDF page references identify the
retained source. The proof/version binding is supplied by the user, and the
receipt does not claim that the export is current or that the proof is approved.
An unreadable export or missing source is never recorded as an empty successful
review. Missing feedback, a mismatched source, implicit source fallbacks, and
writes that can run before successful feedback reads fail plan validation.

## Connection behavior and verification

The MCP endpoints are `https://mcp.frame.io/v1/mcp` and
`https://mcp.pageproof.com/mcp`. The following MCP rules do not describe the
separate native Adobe API route. Public OAuth metadata is resolved only through
reviewed vendor domains. PKCE, resource binding, tenant membership and the
existing one-use callback checks remain required. Provider rejection of AURA's
client registration remains an explicit setup blocker. A public tools listing
alone is insufficient: an authenticated read probe must pass before a connection
is enabled. Frame.io's `mandatory_init` runs before the selected operation in
each new MCP session; writes and deletes retain consequential permissions.

Live metadata verification on 21 October 2026 found that Frame.io requires a
confidential registered client; its generated client secret stays encrypted on
the server. PageProof advertises one exact Azure-hosted issuer, OIDC discovery
and Client ID Metadata Documents instead of dynamic registration. AURA publishes
its secret-free client identity at `/v1/oauth/mcp-client/pageproof`, with the
configured callback URI. These flows retain PKCE and resource binding; other
Azure origins are not accepted. Provider metadata and client-setup compatibility
are separate from the user's consent and authenticated account verification.

Tests use mocked vendor boundaries to cover metadata discovery, domain rejection,
consent routing, authenticated probes and session initialization. They also
exercise the actual native import dispatch and plan validation. A live vendor
run still requires consented test accounts, authorized feedback, the selected
asset/version and a real revised file. Passing these tests does not establish
vendor authorization or a completed live workflow.

Vendor references:

- [Frame.io MCP](https://next.developer.frame.io/platform/docs/mcp/frame-io-mcp)
- [PageProof MCP and metadata limits](https://help.pageproof.com/en/articles/17274621-connect-pageproof-mcp-to-an-ai-assistant)
- [PageProof comments print sheet](https://help.pageproof.com/en/articles/417244-generating-a-print-sheet-of-comments)
