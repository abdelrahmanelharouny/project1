"""Run the A11 evaluation framework and write a machine-readable report.

Usage:
    .venv/bin/python scripts/run_evaluation.py            # deterministic only
    .venv/bin/python scripts/run_evaluation.py --with-llm # + narrative eval
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("CROPTWIST_DATABASE_URL", "postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist")
os.environ.setdefault("CROPTWIST_LLM_ENABLED", "true")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-llm", action="store_true", help="also evaluate LLM narratives via the bridge")
    args = parser.parse_args()

    from app.evaluation.report import summary, write_report

    path, report = write_report(with_llm=args.with_llm)
    print(summary(report))
    print(f"report: {path}")
    det = report["deterministic"]
    return 0 if det["failed_checks"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
