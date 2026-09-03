# AURA

AURA is a multi-tenant workflow automation application. The React frontend authenticates with Clerk and sends the current session token to the Python control plane. Workflows, runs, schedules, access requests, connection state, and orchestration records are stored by workspace.

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

See [`backend/README.md`](backend/README.md) for PostgreSQL, Redis, Clerk, encryption, and worker configuration. Start the API and Celery worker before using the frontend.

## Tenant boundary

Every persisted customer record carries a `workspace_id`. API authorization verifies Clerk organization membership, and PostgreSQL row-level security enforces the same workspace boundary in the database.
