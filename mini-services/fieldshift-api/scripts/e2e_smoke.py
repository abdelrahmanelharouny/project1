#!/usr/bin/env python3
"""CropTwist P0 end-to-end HTTP smoke test (Phase 6).

Covers the primary user journey against a RUNNING stack
(default http://127.0.0.1:3030):

    login -> open farm + field -> AI insights -> load recommendations
    -> trigger recommendation refresh -> verify multi-domain output
    -> advisor query (evidence + disclaimer) -> authz/404 error handling

Determinism contract: assertions are STRUCTURAL only. When the LLM bridge
is healthy the advisor/insights run with engine mode "llm" and the
recommendation narratives with "rules+llm"; when it is down both degrade
to "rules". Default mode accepts both via the engine-mode contract;
`--expect-rules-only` (run with the bridge STOPPED) asserts the fallback
contract exactly (mode == "rules", no invented insight summary). No
external LLM API is ever required.

Usage:
    python3 scripts/e2e_smoke.py                       # happy path
    python3 scripts/e2e_smoke.py --expect-rules-only   # bridge-down fallback
    BASE=http://127.0.0.1:3030 python3 scripts/e2e_smoke.py

Exit code 0 = all checks passed; 1 = one or more failures (each printed).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:3030") + "/api/v1"
DEMO_EMAIL = "demo@croptwist.local"
DEMO_PASSWORD = "croptwist-demo-2026"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-rules-only", action="store_true",
                    help="assert advisor/recommendations run in rules-only "
                         "fallback mode (run with the LLM bridge stopped)")
    args = ap.parse_args()

    t0 = time.monotonic()

    # --- 1. authenticate with the local demo account ------------------------
    r = httpx.post(f"{BASE}/auth/login",
                   json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
                   timeout=30)
    check("login 200", r.status_code == 200, f"got {r.status_code}")
    token = r.json().get("token") if r.status_code == 200 else ""
    check("login returns bearer token", bool(token))
    if not token:
        return _finish(t0)
    headers = {"Authorization": f"Bearer {token}"}

    # --- authz: unauthenticated access must be rejected ---------------------
    r = httpx.get(f"{BASE}/farms", timeout=30)
    check("farms without token rejected (401)", r.status_code == 401,
          f"got {r.status_code}")

    # --- 2. open farm and field ---------------------------------------------
    r = httpx.get(f"{BASE}/farms", headers=headers, timeout=30)
    check("farms 200", r.status_code == 200, f"got {r.status_code}")
    farms = r.json().get("items", [])
    check("at least one farm", len(farms) >= 1)
    if not farms:
        return _finish(t0)
    farm = farms[0]
    r = httpx.get(f"{BASE}/farms/{farm['id']}/fields", headers=headers, timeout=30)
    check("fields 200", r.status_code == 200, f"got {r.status_code}")
    fields = r.json().get("items", [])
    check("at least one field", len(fields) >= 1)
    if not fields:
        return _finish(t0)
    field = fields[0]
    print(f"    farm={farm.get('name')!r} field={field.get('name')!r}")

    # --- ensure a feature run exists and COMPLETES (synthetic, deterministic)
    r = httpx.get(f"{BASE}/fields/{field['id']}/feature-runs",
                  headers=headers, timeout=30)
    runs = r.json().get("items", []) if r.status_code == 200 else []
    if not runs:
        r = httpx.post(
            f"{BASE}/fields/{field['id']}/feature-runs",
            headers=headers,
            json={
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
                "aggregation_levels": ["monthly", "seasonal"],
                "idempotency_key": "p0-e2e-feature-run",
            },
            timeout=180,
        )
        check("feature run created", r.status_code < 300, f"got {r.status_code}")
    # Feature runs are async (202 -> queued -> running -> succeeded): poll.
    deadline = time.monotonic() + 150
    run_status = None
    while time.monotonic() < deadline:
        r = httpx.get(f"{BASE}/fields/{field['id']}/feature-runs",
                      headers=headers, timeout=30)
        items = r.json().get("items", []) if r.status_code == 200 else []
        run_status = items[0].get("status") if items else None
        if run_status in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(2)
    check("feature run completed", run_status == "succeeded", str(run_status))

    # --- 3. AI insights ------------------------------------------------------
    r = httpx.get(f"{BASE}/fields/{field['id']}/insights",
                  headers=headers, timeout=120)
    check("insights 200", r.status_code == 200, f"got {r.status_code}")
    insights = r.json() if r.status_code == 200 else {}
    if not args.expect_rules_only:
        check("insights has summary", bool(insights.get("summary")))
    check("insights engine-mode contract",
          insights.get("engine", {}).get("mode") in ("rules", "llm"),
          str(insights.get("engine", {}).get("mode")))

    # --- 4. load recommendations ---------------------------------------------
    r = httpx.get(f"{BASE}/fields/{field['id']}/recommendations",
                  headers=headers, timeout=120)
    check("recommendations 200", r.status_code == 200, f"got {r.status_code}")

    # --- 5. trigger refresh --------------------------------------------------
    r = httpx.post(f"{BASE}/fields/{field['id']}/recommendations/refresh",
                   headers=headers, timeout=300)
    check("recommendation refresh 200", r.status_code == 200,
          f"got {r.status_code} {r.text[:200] if r.status_code >= 300 else ''}")
    payload = r.json() if r.status_code == 200 else {}
    items = payload.get("recommendations", payload.get("items", []))
    check("refresh produced recommendations", len(items) >= 1,
          f"count={len(items)}")

    # --- 6. multi-domain verification ----------------------------------------
    domains = sorted({i.get("domain") for i in items if i.get("domain")})
    check("recommendations span multiple domains (>=3)", len(domains) >= 3,
          f"domains={domains}")
    check("refresh engine-mode contract",
          payload.get("engine", {}).get("mode") in ("rules", "rules+llm"),
          str(payload.get("engine", {}).get("mode")))
    if args.expect_rules_only:
        check("fallback: refresh engine mode is rules-only",
              payload.get("engine", {}).get("mode") == "rules",
              str(payload.get("engine", {}).get("mode")))

    # --- 7. advisor question (evidence + disclaimer contract) ----------------
    r = httpx.post(
        f"{BASE}/fields/{field['id']}/advisor/query",
        headers=headers,
        json={"question": "What should I prioritize for this field this week?"},
        timeout=300,
    )
    check("advisor query 200", r.status_code == 200,
          f"got {r.status_code} {r.text[:200] if r.status_code >= 300 else ''}")
    advisor = r.json() if r.status_code == 200 else {}
    check("advisor answer non-empty", bool((advisor.get("answer") or "").strip()))
    check("advisor evidence citations present", len(advisor.get("evidence_used") or []) >= 1,
          f"evidence={len(advisor.get('evidence_used') or [])}")
    check("advisor disclaimer present", bool(advisor.get("disclaimer")))
    mode = advisor.get("engine", {}).get("mode")
    check("advisor engine-mode contract", mode in ("rules", "llm"), str(mode))
    if args.expect_rules_only:
        check("fallback: advisor engine mode is rules-only", mode == "rules", str(mode))
        check("fallback: insight summary suppressed (no invented brief)",
              insights.get("summary") is None,
              str(insights.get("summary"))[:80])

    # --- advisor history persisted ------------------------------------------
    r = httpx.get(f"{BASE}/fields/{field['id']}/advisor/history",
                  headers=headers, timeout=30)
    check("advisor history 200", r.status_code == 200, f"got {r.status_code}")

    # --- 8. P1 additions ------------------------------------------------------
    # 8a. A4 fingerprint no-churn: a second refresh must keep the same active
    # recommendation ids (unchanged evidence -> unchanged fingerprints).
    r2 = httpx.post(f"{BASE}/fields/{field['id']}/recommendations/refresh",
                    headers=headers, timeout=300)
    check("second refresh 200", r2.status_code == 200, f"got {r2.status_code}")
    payload2 = r2.json() if r2.status_code == 200 else {}
    items2 = payload2.get("recommendations", [])
    ids1 = {i.get("id") for i in items}
    ids2 = {i.get("id") for i in items2}
    check("A4 no-churn: unchanged refresh keeps active ids",
          ids1 == ids2, f"removed={len(ids1 - ids2)} added={len(ids2 - ids1)}")

    # 8b. A5 confidence semantics: every rec states its confidence kind.
    kinds = {i.get("confidence_kind") for i in items2}
    check("A5 confidence kinds honest",
          kinds <= {None, "deterministic_rule", "evidence_quality"},
          str(kinds))

    # 8c. A3 narrative cache outcome present on refresh payloads.
    check("A3 narrative_cache contract",
          payload2.get("narrative_cache") in (None, "hit", "miss"),
          str(payload2.get("narrative_cache")))

    # 8d. A8 advisor session id + reuse.
    session_id = advisor.get("session_id")
    check("A8 advisor returns session_id", bool(session_id), str(session_id))
    if session_id:
        r = httpx.post(
            f"{BASE}/fields/{field['id']}/advisor/query",
            headers=headers,
            json={"question": "Follow-up question.", "session_id": session_id},
            timeout=300,
        )
        check("A8 session reuse 200", r.status_code == 200, f"got {r.status_code}")
        check("A8 session id stable", r.json().get("session_id") == session_id,
              str(r.json().get("session_id")))

    # 8e. A12 feedback lifecycle on the first recommendation.
    if items2:
        rec_id = items2[0]["id"]
        r = httpx.post(f"{BASE}/recommendations/{rec_id}/feedback",
                       headers=headers, json={"state": "accepted"}, timeout=30)
        check("A12 feedback accepted 201", r.status_code == 201, f"got {r.status_code}")
        r = httpx.get(f"{BASE}/recommendations/{rec_id}/feedback",
                      headers=headers, timeout=30)
        check("A12 feedback history 200", r.status_code == 200, f"got {r.status_code}")
        check("A12 feedback current state", r.json().get("state") == "accepted",
              str(r.json().get("state")))

    # 8f. A10 Arabic refresh: locale=ar accepted, ids unchanged.
    r = httpx.post(f"{BASE}/fields/{field['id']}/recommendations/refresh?locale=ar",
                   headers=headers, timeout=300)
    check("A10 Arabic refresh 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        ar_ids = {i.get("id") for i in r.json().get("recommendations", [])}
        check("A10 locale does not change recommendation ids", ar_ids == ids2,
              f"diff={len(ar_ids ^ ids2)}")

    # --- 9. error handling: unknown field must 404, not 500 ------------------
    r = httpx.get(f"{BASE}/fields/00000000-0000-0000-0000-000000000000/recommendations",
                  headers=headers, timeout=30)
    check("unknown field -> 404 (not 500)", r.status_code == 404,
          f"got {r.status_code}")

    return _finish(t0)


def _finish(t0: float) -> int:
    dt = time.monotonic() - t0
    print(f"\n{'=' * 60}")
    if failures:
        print(f"E2E SMOKE: {len(failures)} FAILURE(S) in {dt:.1f}s: {failures}")
        return 1
    print(f"E2E SMOKE: ALL CHECKS PASSED in {dt:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
