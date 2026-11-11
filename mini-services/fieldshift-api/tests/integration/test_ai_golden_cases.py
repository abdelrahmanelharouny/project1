"""A11 golden-case evaluation as CI tests (deterministic layers, no network)."""

from __future__ import annotations

from app.evaluation.golden_cases import GOLDEN_CASES
from app.evaluation.runner import run_deterministic_eval


def test_all_golden_cases_pass():
    report = run_deterministic_eval()
    assert report["failed_checks"] == 0, (
        "failing checks: "
        + str(
            [
                (r["case_id"], c["name"], c["detail"])
                for r in report["results"]
                for c in r["checks"]
                if not c["passed"]
            ]
        )
    )
    assert report["pass_rate"] == 1.0


def test_fingerprint_stability_across_runs():
    report = run_deterministic_eval()
    assert report["stability_rate"] == 1.0


def test_every_domain_has_golden_cases():
    covered = {case["domain"] for case in GOLDEN_CASES}
    assert covered == {"climate", "water", "soil", "rotation", "management"}


def test_missing_evidence_fallback_covered():
    report = run_deterministic_eval()
    checks = report["missing_evidence_checks"]
    assert len(checks) >= 4
    assert all(c["passed"] for c in checks)
