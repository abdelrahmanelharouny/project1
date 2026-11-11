"""Evaluation report generator (A11.4): machine-readable JSON.

Writes a full report (deterministic + optional LLM layers) to
`evaluation_reports/eval_<UTC timestamp>.json` and returns the summary.
Tracked metrics (never invented — computed from actual runs):

- pass_rate / failed_checks            (deterministic correctness)
- stability_rate                       (fingerprint run-to-run equality)
- coverage_by_domain                   (evaluation coverage per domain)
- groundedness_rate, unsupported_numeric_claims, clarity_rate,
  locale_consistency_rate, fabrication_free_rate  (LLM narrative criteria)
- latency                              (per-case generator wall time)
- citation validity / schema validity / fallback / cache rates live in the
  runtime metrics store (`/api/v1/metrics`, `/fields/{id}/ai/metrics`) — the
  report embeds their current snapshot for context.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evaluation import runner as eval_runner
from app.intelligence.metrics import snapshot_ai

logger = logging.getLogger("croptwist.evaluation.report")

REPORT_DIR = Path(__file__).resolve().parents[2] / "evaluation_reports"


def build_report(*, with_llm: bool = False) -> dict[str, Any]:
    deterministic = eval_runner.run_deterministic_eval()
    llm = eval_runner.run_llm_eval(with_judge=with_llm) if with_llm else None
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "framework_version": "p1-1",
        "deterministic": deterministic,
        "llm": llm,
        "runtime_metrics_snapshot": snapshot_ai(),
        "limitations": [
            "Golden cases verify generator RULES against fixed synthetic "
            "evidence; they do not validate the upstream agronomic engines "
            "(those have their own suites).",
            "LLM narrative criteria are heuristic (numeric subset, locale "
            "script, length); a bridge-based judge is supplementary and never "
            "the source of truth. No calibrated quality scores exist.",
            "Latency numbers are single-process wall times on the dev sandbox.",
            "Feedback analytics (acceptance rate etc.) require production "
            "usage data and are intentionally absent here.",
        ],
    }
    return report


def write_report(*, with_llm: bool = False) -> tuple[Path, dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report(with_llm=with_llm)
    path = REPORT_DIR / f"eval_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("evaluation report written: %s", path)
    return path, report


def summary(report: dict[str, Any]) -> str:
    det = report["deterministic"]
    lines = [
        "AI evaluation report",
        f"  deterministic: {det['passed_checks']}/{det['total_checks']} checks passed "
        f"(pass_rate={det['pass_rate']}, stability_rate={det['stability_rate']})",
    ]
    for domain, stats in det["coverage_by_domain"].items():
        lines.append(
            f"    {domain}: {stats['passed']}/{stats['cases']} cases, "
            f"{stats['checks_passed']}/{stats['checks']} checks"
        )
    if report.get("llm"):
        metrics = report["llm"]["metrics"]
        lines.append(f"  llm: {metrics['cases_with_narratives']} cases with narratives")
    return "\n".join(lines)
