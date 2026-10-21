import pytest

from app.render_runtime import launch_command, prepare_environment


@pytest.mark.parametrize("scheme", ["postgres://", "postgresql://"])
def test_render_database_url_uses_psycopg_without_losing_tls_parameters(scheme):
    original = {"DATABASE_URL": scheme + "user:password@private/db?sslmode=require"}
    result = prepare_environment(original)
    assert result["DATABASE_URL"] == (
        "postgresql+psycopg://user:password@private/db?sslmode=require"
    )
    assert original["DATABASE_URL"].startswith(scheme)


def test_explicit_public_url_and_driver_are_preserved():
    original = {"DATABASE_URL": "postgresql+psycopg://private/db",
                "PUBLIC_URL": "https://api.example.test",
                "RENDER_EXTERNAL_URL": "https://other.example.test"}
    assert prepare_environment(original) == original


def test_render_origin_and_port_are_used_and_worker_does_not_start_an_http_server():
    env = prepare_environment({"RENDER_EXTERNAL_URL": "https://aura.example.test",
                               "PORT": "10000"})
    assert env["PUBLIC_URL"] == "https://aura.example.test"
    assert launch_command("api", env)[-1] == "10000"
    assert launch_command("worker", env)[-1] == "--concurrency=1"
    with pytest.raises(ValueError):
        launch_command("unknown", env)
