"""The destructive integration harness must reject non-disposable targets."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dsn", [
    "postgresql+psycopg2://postgres@db.example.com:5432/croptwist_test",
    "postgresql+psycopg2://postgres@127.0.0.1:5433/production",
    "postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist_test;DROP",
    "sqlite:///croptwist_test",
])
def test_harness_refuses_unsafe_database_before_import(dsn: str) -> None:
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, CROPTWIST_TEST_DB_URL=dsn)
    result = subprocess.run(
        [sys.executable, str(root / "tests/conftest.py")],
        cwd=root, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "Refusing destructive fixtures" in result.stderr
    assert "psycopg2.OperationalError" not in result.stderr


def test_slice_runner_never_drops_a_database() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts/run_test_slice.sh").read_text()
    assert "DROP DATABASE" not in runner
    assert "git reset" not in runner
    assert "Refusing destructive test fixtures" in runner
