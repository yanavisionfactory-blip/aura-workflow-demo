"""Launch AURA on Render using its managed Postgres connection URL."""
import os
import sys


def prepare_environment(source: dict[str, str]) -> dict[str, str]:
    env = dict(source)
    url = env.get("DATABASE_URL", "")
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            env["DATABASE_URL"] = "postgresql+psycopg://" + url[len(scheme):]
            break
    if not env.get("PUBLIC_URL") and env.get("RENDER_EXTERNAL_URL"):
        env["PUBLIC_URL"] = env["RENDER_EXTERNAL_URL"]
    return env


def launch_command(role: str, env: dict[str, str]) -> list[str]:
    if role == "api":
        return [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
                "--port", env.get("PORT", "8000")]
    if role == "worker":
        return ["celery", "-A", "app.worker.celery", "worker", "--loglevel=INFO",
                "--concurrency=1"]
    raise ValueError("Expected the api or worker runtime role")


if __name__ == "__main__":
    environment = prepare_environment(os.environ)
    command = launch_command(sys.argv[1] if len(sys.argv) == 2 else "", environment)
    os.execvpe(command[0], command, environment)
