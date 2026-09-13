# Python control plane

The FastAPI API, Celery worker, and scheduler live in `backend/` and are released from `main` together with the React client.

## Local validation

```bash
cd backend
python -m pip install -e ".[dev]"
python -m compileall -q app
pytest -q
python -m app.load_evaluation --report engine-load.json
```

The connector-broker integration tests exercise OAuth, managed API-key setup, MCP execution, and automatic continuation of a paused workflow. External Pipedream calls are replaced at the network boundary; AURA's HTTP routes, database writes, capability certification, orchestration, and run transitions remain real.

## Release source

Railway services must deploy `backend/` from `main`. GitHub Pages also publishes from `main`. The retired `python-control-plane` branch is historical input only and must not be used as an independent release source.

See [production-deployment.md](production-deployment.md) for environment configuration and post-deployment checks.
