# AURA workflow demo

AURA is a React workflow client backed by a separately deployed Python control plane.

- The production frontend is built from `main` and published with GitHub Pages.
- The production FastAPI service and Celery worker are built from
  [`python-control-plane`](https://github.com/yanavisionfactory-blip/aura-workflow-demo/tree/python-control-plane/backend).
- Railway deploys the `backend/` directory from that branch. Backend fixes must target
  `python-control-plane`; frontend fixes must target `main`.

This branch split is intentional. It is documented here so reviews and deployments use the same
source revision instead of treating the older `backend/` snapshot on `main` as production code.

## Frontend development

```bash
npm install
npm run dev
```

Set `VITE_AURA_API_URL` to the deployed control-plane URL. Authentication settings are described in
the environment examples committed with each deployment branch.

## Backend development

Check out `python-control-plane`, then follow its `README.md` and `backend/RELIABILITY.md`.
