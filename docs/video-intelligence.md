# AURA video production review

`intelligence.video.review` accepts an uploaded MP4/MOV input reference, filename,
and review instructions. `frameio.video.review` accepts the connected account UUID,
an exact file/version UUID, and review instructions. Both run AURA Intelligence and
save the finished chronological Markdown review plus structured findings in AURA.
They do not call Frame.io AI Assistant or post comments to Frame.io.

The Frame.io operation fetches a fresh authenticated efficient rendition. It rejects
missing media and silent thumbnail renditions. Adobe credentials never go to a CDN
or model. Signed playback URLs remain transient; saved source evidence contains
the exact account/file/version identifiers, rendition type, file size and SHA-256.

FFmpeg decodes the media locally. Vision receives approximately two frames per
second plus scene changes and the last frame when declared in the container.
Actual frame PTS values accompany each image. Audio receives overlapping stereo
WAV segments covering the first audio stream. Visual and audio intervals overlap
at boundaries so transitions are not split between isolated calls. The final review combines both
analyses and states sampling limits. Visual sampling cannot establish every
single-frame defect or lip sync; audio issue timestamps are approximate and need
confirmation in an editor. A missing audio track is explicitly reported.

Limits: MP4/MOV, 50 MB, 120 seconds, up to 4K and 500 selected frames. Oversized,
undecodable or incomplete inputs fail explicitly. Decoder subprocesses are reaped
on cancellation; downloaded media, JPEGs and WAVs are removed after each attempt.
No binary media is placed in model-review text or saved provider results.

## Deployment

The backend Dockerfile installs `ffmpeg` and `ffprobe`. For a Railpack build, set
`RAILPACK_DEPLOY_APT_PACKAGES=ffmpeg` on the API, worker and release canary (preserve
other existing packages). Both executors need the same release. Existing
`OPENAI_API_KEY` is reused. Vision uses `OPENAI_MODEL`; audio uses
`VIDEO_AUDIO_MODEL` (default `gpt-audio-1.5`). Both must be available to that key.
`VIDEO_REVIEW_TIMEOUT_SECONDS` defaults to 150 seconds and remains bounded by the
delivery deadline/model-call budget. No additional user AI connection is required.

Existing connections refresh their native operation contracts automatically;
generate a new plan so the new read operation is included in its approved snapshot.
Do not replay the old metadata-only plan and expect it to inspect media.

## Validation

Run `pytest -q tests/test_video_review.py tests/test_frameio_adobe.py
tests/test_frameio_screen.py tests/test_native_connectors.py tests/test_llm_planner.py`
from `backend`, and `node --test tests/resultPresentation.test.mjs
tests/toolResultViews.test.mjs` from the repository root. The video tests generate
and decode a real MP4, verify multimodal model payloads, exact Frame.io binding,
stream limits, redirect validation, cancellation cleanup, output provenance and
failure behavior. Model responses are mocked in unit tests; a production run is
required to verify live model access and end-to-end results.
