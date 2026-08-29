# AURA Python control plane

The GitHub Pages site is only the React client. Real execution is provided by `backend/`, a separately deployed Python service.

## Runtime architecture

- FastAPI exposes workspaces, tools, OAuth callbacks, runs, approvals, and run-state APIs.
- PostgreSQL stores workflows, steps, approvals, encrypted tool connections, and audit events.
- Redis and Celery provide recoverable background planning and execution.
- OpenAI Agents SDK runs structured, role-specific agents behind the control-plane API.
- The backend uses seven explicit runtime roles from the AURA orchestration design:
  Intent & Scope, Tool Router, Plan Builder, Static Plan Evaluator, deterministic Workflow
  State Manager, Tool Output Critic, and Unified Response Synthesizer.
- Planning is separated into Propose and Authorize phases. Execution cannot begin until the
  deterministic capability check, model-based preflight evaluation, and human plan approval pass.
- Each real provider result is evaluated against its step contract. Safe reads may be retried once;
  consequential actions are never automatically replayed after an uncertain result.
- Final synthesis uses only critic-accepted artifacts and includes step-level traceability.
- Provider credentials are encrypted with Fernet and are never passed into model context.
- Provider writes pause for approval. Approved payloads may be edited before execution.
- Idempotency keys prevent an already-completed provider action from being treated as a new step.

## Supported real operations

| Connection | Operations |
|---|---|
| Google OAuth | Gmail read/send, Calendar read/create, Sheets read (write requires a separate explicit scope grant) |
| Airtable OAuth | Records read/create |
| Slack OAuth | Post approved messages |
| API key/OpenAPI tool | Allow-listed HTTP operations under one configured base URL |
| MCP | Discover and call allow-listed tools on trusted Streamable HTTP MCP servers |

## Run locally

1. Copy `backend/.env.example` to `backend/.env`.
2. Generate keys:

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

3. Add `OPENAI_API_KEY` and the OAuth client credentials you want to offer.
4. Configure each provider callback as `https://YOUR_API/v1/oauth/PROVIDER/callback`.
5. Start everything with `docker compose up --build`.

The public GitHub demo must set `VITE_AURA_API_URL` to the deployed API URL. A Python backend cannot run on GitHub Pages.
