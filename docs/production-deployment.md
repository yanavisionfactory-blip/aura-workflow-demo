# Production deployment

## Railway API and worker

Configure the same environment on the API and Celery worker services:

```env
ENVIRONMENT=production
PUBLIC_URL=https://<api-domain>
FRONTEND_URL=https://yanavisionfactory-blip.github.io
DATABASE_URL=<Railway PostgreSQL URL using postgresql+psycopg://>
REDIS_URL=<Railway Redis URL>
OPENAI_API_KEY=<secret>
OPENAI_MODEL=gpt-5.4-mini
CREDENTIAL_ENCRYPTION_KEY=<current Fernet key>
CREDENTIAL_ENCRYPTION_PREVIOUS_KEYS=<retired Fernet keys, comma-separated>
SESSION_SIGNING_KEY=<at least 32 random characters>
CLERK_JWT_KEY=<Clerk PEM public key>
CLERK_ISSUER=<Clerk issuer URL>
CLERK_AUTHORIZED_PARTIES=https://yanavisionfactory-blip.github.io
ALLOW_LEGACY_WORKSPACE_TOKENS=false
```

Add each provider's client ID and secret to both services. Never add provider secrets to GitHub Pages, source control, build arguments, or variables prefixed with `VITE_`.

Set the API start command to the Dockerfile default. Set the worker command to:

```bash
celery -A app.worker.celery worker --loglevel=INFO
```

Use a modest worker concurrency for the Railway service size, for example `--concurrency=4`, rather than Celery's CPU-derived default.

## GitHub Pages

Create the repository Actions secret `CLERK_PUBLISHABLE_KEY`. The public Clerk publishable key is the only authentication value compiled into the browser. The API address is configured by `VITE_AURA_API_URL`.

## Encryption-key rotation

1. Generate a new Fernet key and move the old `CREDENTIAL_ENCRYPTION_KEY` into `CREDENTIAL_ENCRYPTION_PREVIOUS_KEYS`.
2. Deploy the API and worker with the new keyring.
3. As a workspace administrator, call `POST /v1/security/rotate-credentials` once for every workspace.
4. Confirm the audit event `credentials.encryption_rotated` and successful connector tests.
5. Remove retired keys only after every workspace reports zero rotated connections on a second pass.

## Release checks

`GET /health` confirms the process is alive. `GET /ready` additionally checks PostgreSQL, Redis, Clerk, OpenAI, credential encryption, authorized browser origins, and that legacy workspace tokens are disabled.

Run the smoke test after each deployment:

```bash
bash scripts/smoke-production.sh https://<api-domain>
```

Before launch, create two Clerk organizations and verify that workflows, history, schedules, access requests, and connections created in one organization return `404` or `403` from the other.
