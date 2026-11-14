#!/usr/bin/env python3
"""Run pure unit/contract cases without provisioning or truncating a database.

Database cases are explicitly deselected, never treated as passed. Use the
normal pytest command and an isolated DSN for their separate integration run.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

DB_FIXTURES = frozenset({"db", "client", "auth_headers", "farm_with_field"})


class IndependentOnly:
    def pytest_collection_modifyitems(self, config, items):
        retained, deselected = [], []
        for item in items:
            dependencies = DB_FIXTURES.intersection(item.fixturenames)
            if dependencies:
                deselected.append(item)
            else:
                retained.append(item)
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            print("\nDatabase-bound cases explicitly excluded from this independent slice:")
            for item in deselected:
                print(f"  {item.nodeid}")
        items[:] = retained


if __name__ == "__main__":
    arguments = ["-c", "/dev/null", "--noconftest", "-q", "tests/unit", "tests/contract"]
    arguments.extend(sys.argv[1:])
    raise SystemExit(pytest.main(arguments, plugins=[IndependentOnly()]))
