# Pipedream browser connection compatibility

`@pipedream/sdk` is pinned to 3.1.6 while this compatibility patch is needed.
`npm install` and `npm ci` apply it through `patch-package --error-on-fail`.

The hosted Connect iframe currently posts failed outcomes as
`{ type: "error", message: "…" }`. SDK 3.1.6 reads only `error`, which loses
the provider's explanation and makes AURA show a generic failure instead.
The patch accepts both payload fields.

It also validates the sender's origin and window against the current Connect
iframe, and removes its listener when an outcome is complete. Unrelated browser
messages must not cancel a connection or count as successful authorization.

The frame is assigned before insertion so an early provider response can be
validated. Both ESM and CommonJS browser builds are patched and covered by
`tests/pipedreamMessages.test.mjs`.

Provider consent and backend account verification remain required. Recheck the
upstream browser implementation before updating the pinned SDK or removing this
patch:
https://github.com/PipedreamHQ/pipedream-sdk-typescript/blob/main/src/browser/index.ts
