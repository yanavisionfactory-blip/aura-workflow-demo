# AURA

AURA is a multi-tenant workflow automation application. The React frontend authenticates with Clerk and sends the current session token to the Python control plane. Workflows, runs, schedules, access requests, connection state, and orchestration records are stored by workspace.

`main` is the single controlled release source for both the GitHub Pages frontend and the Railway Python control plane. Production changes must be reconciled and tested on a branch from `main`, then merged through one reviewed pull request.

## Frontend

```bash
npm install
cp .env.example .env.local
npm run dev
```

Required browser configuration:

```env
VITE_AURA_API_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

## Backend

See [`docs/PYTHON_BACKEND.md`](docs/PYTHON_BACKEND.md), [`backend/RELIABILITY.md`](backend/RELIABILITY.md), and [`docs/production-deployment.md`](docs/production-deployment.md) for PostgreSQL, Redis, Clerk, encryption, worker, and connector-network configuration. Start the API and Celery worker before using the frontend.

## Release validation

Pull requests run the frontend tests and build, the complete Python test suite, and the isolated execution load evaluation. GitHub Pages publishes the frontend after the pull request is merged to `main`; Railway should also deploy the `backend/` directory from `main`.

## Tenant boundary

Every persisted customer record carries a `workspace_id`. API authorization verifies Clerk organization membership, and PostgreSQL row-level security enforces the same workspace boundary in the database.
