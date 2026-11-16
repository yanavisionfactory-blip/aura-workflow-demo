# Drive → Slides live acceptance

Run this after deploying the folder/Slides and original-brief fixes (#687 and
#692), and any subsequent provenance change. Passing fixture tests or merging
a PR does not prove a live Google import. Record the deployed API/worker version
and frontend version; do not infer deployment from `main`.

## Fixture and preflight

Use a dedicated QA folder in the selected Google account, with a unique parent
name containing Unicode and an emoji, and a child named `Brisa Studio`.
Resolve the exact two-segment path. Record both provider folder IDs and the
child's actual parent. Keep a conflicting text file outside the child folder.
Do not use customer documents, change permissions, or revoke production tokens
to test failures.

Inside the child folder, prepare three small UTF-8 text/plain files:

| File | Synthetic contents | Expected handling |
| --- | --- | --- |
| `Notes_07.txt` | Portuguese proposal: AI background music for independent cafes; proposed 14-day pilot in 3 venues; proposed 29 EUR/month; `BRISA-QA-A7F2` | Read and use despite neutral filename |
| `Запись_02.txt` | Russian note: commercial rights unverified; atmosphere, repetition and willingness-to-pay feedback; proposed success criterion 2 of 3 venues; `RIGHTS-UNVERIFIED-B4` | Read and preserve uncertainty |
| `AI_music_restaurants.txt` | Unrelated SEO keyword list with `SEO-DECOY-Q9` | Read for relevance, exclude from project evidence |

The outside file contains conflicting 999 EUR/90-day values and
`OUTSIDE-SCOPE-Z8`. It must not be read or cited by the scoped workflow.
Keep the expected values/control markers in the evaluator's manifest, not the
execution prompt, so returning them demonstrates a real source read.

Check actual selected-account access, not just an enabled badge. Google Slides
must expose populated create/import and saved-presentation reads; a separate
Google Drive connection does not establish this. First run a read-only AURA
workflow against the fixture path and inspect its provider receipt.

## Live happy path

Ask AURA to create one five-slide Russian deck from that exact folder: offer and
audience; proposed pilot/pricing; feedback/success hypothesis; rights caveat;
source links and the control markers actually read. Label all content synthetic.
Retain the complete user request through discovery and composition. Use the
selected account's default output location; moving the output into a named
folder is a separate acceptance case.

Review the actual plan before starting. Require the source read → typed
`report.compose` → populated `google-slides.create-presentation` dependency
chain. Record the run ID and the approved presentation. The import is one
non-retried write. Read the result by the returned presentation ID and compare
every approved title/item and the count of five slides. Inspect all five slides
for clipping, legibility and usable source links. Preserve the original receipt
when resuming or investigating a verification failure.

## Acceptance matrix

| Case | Required evidence | Failure condition |
| --- | --- | --- |
| Live account preflight | Verified Drive and Slides operations on selected accounts | Missing/expired access treated as ready |
| Unicode nested path | Exact returned parent/child IDs and parent relationship | First-match guessing, changed scope, fabricated ID |
| Actual source reads | Provider IDs, content hashes, two source markers | Metadata-only read or invented content |
| Semantic relevance | Two relevant files; SEO distractor excluded | Filename keyword match becomes evidence |
| Provenance transfer | `sources` binding carries folder identity, file identity and read counts | `material_1` reported as a Drive ID or coverage note counted as a file |
| Content | 14 days, 3 venues, 29 EUR, proposed 2/3 criterion, rights unverified | Invented outcomes or copyright-free claim |
| Google import/readback | One import receipt; matching ID; five populated slides | Empty deck, mismatched content, creation replay |
| Refresh/resume | Same run and presentation, no second create dispatch | Duplicate artifact or lost checkpoint |
| Missing/ambiguous folder | Specific blocker before composition/write | Search escapes requested folder |
| Unsupported/partial source | Explicit coverage limitation; block required missing inputs | Unread files silently counted as reviewed |
| Read 429/5xx | Bounded retry with saved attempt evidence | Infinite retry or replay of a write |
| Lost write response | Reconcile existing artifact, or explicit uncertain outcome | Blind create retry or unsupported success |
| Visual result | All five slides reviewed | Text readback mistaken for layout verification |

Inject provider errors and duplicate responses only in an isolated test setup.
Live missing/ambiguous-folder checks may use dedicated QA-only fixtures. Never
alter the customer's access or live data to manufacture a negative case.

## Verdict and evidence

Use PASS only when every required case for that run has direct evidence.
Missing credentials or environment are BLOCKED; unexecuted checks are NOT_RUN.
Metadata and provider-side success are separate from model quality and visual
acceptance. A successful HTTP response, green connection badge, generated plan,
or a UI `Completed` label cannot alone establish the verdict.

Retain a private evidence packet: run ID, build versions, plan, selected account
references (no credentials), returned source folder IDs, source hashes, typed
presentation, provider write/read receipts, verification results, attempts and
visual review. Keep private customer IDs and run links out of this public repo.

Focused deterministic checks (provider/model responses are controlled fixtures):

```sh
cd backend
python -m pytest -q tests/test_semantic_materials.py tests/test_project_presentation_brief.py tests/test_presentation_draft.py tests/test_reports.py
```

After a fix, repeat the original live case before declaring it resolved. Use
distinct output names for separate attempts; resume within an attempt must
reuse its existing artifact. Gate release on the controlled regressions plus a
recorded live result, and retain the last known working release for rollback.
