# AURA workflow demo

A dependency-free, interactive prototype showing AURA's outcome-contract and safe-recovery flow.

## Run locally

```bash
python3 -m http.server 8080 --directory aura-demo
```

Then open `http://localhost:8080`.

## Publish with GitHub Pages

Push the contents of `aura-demo/` to a GitHub repository, then enable **Settings → Pages → Deploy from a branch** and select the branch root.

## Demo flow

1. Approve the outcome contract.
2. Watch Salesforce and Stripe complete.
3. A simulated Drive permission failure safely blocks Slack.
4. Approve the recommended recovery.
5. Inspect the verified outcome and audit evidence.
