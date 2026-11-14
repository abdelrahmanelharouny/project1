"""Deployment readiness tests that do not contact a hosted database.

The repository's shared integration conftest still provisions its local test
cluster for the broader suite. These tests themselves use subprocess settings
checks and a tiny TestClient app with the database probe replaced explicitly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def _settings_subprocess(*assignments: tuple[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CROPTWIST_"):
            env.pop(key)
    env.update(dict(assignments))
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.core.config import Settings; Settings(); print('ok')",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cors_wildcard_is_rejected_in_a_clean_settings_process() -> None:
    result = _settings_subprocess(("CROPTWIST_CORS_ALLOW_ORIGINS", "*"))
    assert result.returncode != 0
    assert "cors_allow_origins" in result.stderr


def test_search_path_rejects_sql_injection_in_a_clean_settings_process() -> None:
    result = _settings_subprocess(
        ("CROPTWIST_DATABASE_SEARCH_PATH", "public;DROP TABLE users")
    )
    assert result.returncode != 0
    assert "database_search_path" in result.stderr


def test_staging_rejects_dev_mode_and_wildcard_hosts() -> None:
    result = _settings_subprocess(
        ("CROPTWIST_ENVIRONMENT", "staging"),
        ("CROPTWIST_DEV_MODE", "true"),
        ("CROPTWIST_TRUSTED_HOSTS", "*"),
    )
    assert result.returncode != 0
    assert "dev_mode" in result.stderr or "trusted_hosts" in result.stderr


def test_postgres_connect_args_are_explicit_and_safe() -> None:
    from app.core.config import Settings
    from app.core.database import get_database_connect_args

    configured = Settings(
        database_url="postgresql+psycopg2://user:password@example.invalid:5432/db",
        database_sslmode="verify-full",
        database_sslrootcert="/run/secrets/supabase-ca.pem",
        database_connect_timeout_seconds=4,
        database_search_path="public,extensions",
    )
    assert get_database_connect_args(configured) == {
        "connect_timeout": 4,
        "sslmode": "verify-full",
        "sslrootcert": "/run/secrets/supabase-ca.pem",
        "options": "-csearch_path=public,extensions",
    }


def test_configured_trusted_hosts_are_enforced_without_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    monkeypatch.setattr(main.settings, "trusted_hosts", "api.example.test")
    monkeypatch.setattr(main.settings, "cors_allow_origins", "")
    app = main.create_app()
    client = TestClient(app)
    try:
        assert client.get("/api/v1/health", headers={"host": "evil.example.test"}).status_code == 400
        assert client.get("/api/v1/health", headers={"host": "api.example.test"}).status_code == 200
    finally:
        client.close()


def _probe_app() -> FastAPI:
    from app.api.v1 import health

    app = FastAPI()
    app.include_router(health.router, prefix="/api/v1")
    return app


def test_readiness_uses_db_probe_without_startup_or_remote_db(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import health

    monkeypatch.setattr(
        health,
        "check_database",
        lambda: {
            "database": "ok",
            "server_version": "16",
            "postgis_version": "3.5.0",
            "alembic_ok": True,
            "alembic": {"ok": True, "expected_heads": ["head"], "applied_heads": ["head"]},
        },
    )
    with TestClient(_probe_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["postgis_version"] == "3.5.0"


def test_readiness_does_not_leak_database_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import health

    monkeypatch.setattr(
        health,
        "check_database",
        lambda: (_ for _ in ()).throw(
            RuntimeError("postgresql://secret-user:secret-password@example.invalid")
        ),
    )
    with TestClient(_probe_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "database unavailable"}
    assert "secret-password" not in response.text


def test_readiness_rejects_migration_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import health

    monkeypatch.setattr(
        health,
        "check_database",
        lambda: {
            "database": "ok",
            "postgis_version": "3.5.0",
            "alembic_ok": False,
            "alembic": {"ok": False, "expected_heads": ["0023"], "applied_heads": ["0022"]},
        },
    )
    with TestClient(_probe_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "database schema is not ready"}


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_hosted_environment_requires_verified_tls(environment: str) -> None:
    result = _settings_subprocess(
        ("CROPTWIST_ENVIRONMENT", environment),
        ("CROPTWIST_TRUSTED_HOSTS", "api.example.test"),
        ("CROPTWIST_DATABASE_SSLMODE", "require"),
    )
    assert result.returncode != 0
    assert "verify-full" in result.stderr


def test_valid_hosted_config_accepts_explicit_hosts_https_cors_and_ca() -> None:
    result = _settings_subprocess(
        ("CROPTWIST_ENVIRONMENT", "production"),
        ("CROPTWIST_TRUSTED_HOSTS", "api.example.test"),
        ("CROPTWIST_DATABASE_SSLMODE", "verify-full"),
        ("CROPTWIST_DATABASE_SSLROOTCERT", "/run/secrets/ca.crt"),
        ("CROPTWIST_CORS_ALLOW_ORIGINS", "https://ui.example.test"),
    )
    assert result.returncode == 0, result.stderr


def test_cors_allows_only_exact_approved_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main
    monkeypatch.setattr(main.settings, "trusted_hosts", "testserver")
    monkeypatch.setattr(main.settings, "cors_allow_origins", "https://ui.example.test")
    client = TestClient(main.create_app())
    try:
        approved = client.options("/api/v1/health", headers={
            "Origin": "https://ui.example.test", "Access-Control-Request-Method": "GET",
        })
        denied = client.options("/api/v1/health", headers={
            "Origin": "https://evil.example.test", "Access-Control-Request-Method": "GET",
        })
    finally:
        client.close()
    assert approved.headers.get("access-control-allow-origin") == "https://ui.example.test"
    assert approved.headers.get("access-control-allow-credentials") == "true"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
