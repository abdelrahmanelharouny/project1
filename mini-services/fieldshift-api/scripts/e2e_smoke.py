#!/usr/bin/env python3
"""CropTwist end-to-end HTTP smoke test (P0 Phase 6 + P3 section).

Covers the primary user journey against a RUNNING stack
(default http://127.0.0.1:3030):

    login -> open farm + field -> AI insights -> load recommendations
    -> trigger recommendation refresh -> verify multi-domain output
    -> advisor query (evidence + disclaimer) -> authz/404 error handling
    -> P1 trust contracts -> P2 intelligence surface
    -> P3 commercial journey (fresh user): register -> onboarding ->
       plan catalog -> free subscription -> server-side entitlement 402 ->
       notifications -> team invite -> public API key + tenant isolation ->
       ops health

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

    # --- 8g. P2 satellite ingestion + vegetation summary ---------------------
    r = httpx.post(f"{BASE}/fields/{field['id']}/data-jobs", headers=headers, timeout=120,
                   json={"provider_code": "satellite_sim", "variables": ["ndvi"],
                         "start_date": "2019-01-01", "end_date": "2021-12-31",
                         "options": {"profile": "stress_declining", "seed": 7}})
    check("P2 satellite job 202", r.status_code == 202, f"got {r.status_code}")
    if r.status_code == 202:
        job = r.json()
        for _ in range(120):
            jr = httpx.get(f"{BASE}/jobs/{job['job_id']}", headers=headers, timeout=30).json()
            if jr.get("status") in ("succeeded", "failed"):
                break
            time.sleep(0.5)
        check("P2 satellite job succeeded", jr.get("status") == "succeeded", str(jr.get("error_summary")))

    r = httpx.get(f"{BASE}/fields/{field['id']}/vegetation/summary?index=ndvi", headers=headers, timeout=60)
    check("P2 vegetation summary 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        vs = r.json()
        check("P2 vegetation has observations", vs.get("observation_counts", {}).get("valid", 0) > 0,
              str(vs.get("observation_counts")))
        check("P2 vegetation NDVI formula label", str(vs.get("formula", "")).startswith("NDVI"),
              str(vs.get("formula")))

    # --- 8h. P2 evidence gaps + staleness + forecast capabilities -------------
    r = httpx.get(f"{BASE}/fields/{field['id']}/evidence-gaps", headers=headers, timeout=60)
    check("P2 evidence gaps 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        gaps = r.json()
        codes = {g["gap_code"] for g in gaps.get("gaps", [])}
        check("P2 gap has soil decision linkage", all(g.get("affected_decisions") for g in gaps.get("gaps", [])) if gaps.get("gaps") else True,
              str(len(codes)))
        check("P2 VoI never monetary", all("monetary" in g["voi"]["honesty_note"] for g in gaps.get("gaps", [])) if gaps.get("gaps") else True, "")

    r = httpx.get(f"{BASE}/fields/{field['id']}/evidence/staleness", headers=headers, timeout=60)
    check("P2 staleness report 200", r.status_code == 200, f"got {r.status_code}")

    r = httpx.get(f"{BASE}/climate/forecast/capabilities", headers=headers, timeout=30)
    check("P2 forecast capabilities 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        providers = {p["provider_code"] for p in r.json().get("capability_matrix", [])}
        check("P2 capability matrix declares blocked CMIP6", "cmip6_projection" in providers, str(providers))

    # --- 8i. P2 soil memory + failure lab + portfolio -------------------------
    r = httpx.post(f"{BASE}/fields/{field['id']}/soil-memory/snapshots", headers=headers, timeout=60,
                   json={"as_of": "2026-01-01"})
    check("P2 soil snapshot 200", r.status_code == 200, f"got {r.status_code}")

    r = httpx.get(f"{BASE}/fields/{field['id']}/rotation-runs", headers=headers, timeout=30)
    has_rotation = r.status_code == 200 and r.json().get("items")
    if has_rotation:
        r = httpx.post(f"{BASE}/fields/{field['id']}/rotation-stress-runs", headers=headers, timeout=300,
                       json={"packs": ["water_restriction"]})
        check("P2 rotation stress run 200", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            check("P2 stress run succeeded", r.json().get("status") == "succeeded", str(r.json().get("status")))

    r = httpx.post(f"{BASE}/farms/{farm['id']}/portfolio-runs", headers=headers, timeout=300,
                   json={"season_count": 1, "constraints": {"water_allocation_m3": 5000.0}})
    check("P2 portfolio run 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        check("P2 portfolio succeeded", r.json().get("status") == "succeeded",
              str(r.json().get("not_evaluated"))[:200])
        if r.json().get("id"):
            rv = httpx.post(f"{BASE}/portfolio-runs/{r.json()['id']}/verify", headers=headers, timeout=60)
            check("P2 portfolio verify ok", rv.status_code == 200 and rv.json().get("valid") is True,
                  str(rv.json().get("valid")))

    # --- 9. error handling: unknown field must 404, not 500 ------------------
    r = httpx.get(f"{BASE}/fields/00000000-0000-0000-0000-000000000000/recommendations",
                  headers=headers, timeout=30)
    check("unknown field -> 404 (not 500)", r.status_code == 404,
          f"got {r.status_code}")

    # ======================================================================
    # 10. P3 commercial SaaS journey (FRESH user — never mutates demo state)
    #     register -> onboarding step -> billing plans -> free subscription
    #     -> entitlement 402 -> notifications -> team invite -> public API
    #     -> ops health. All structural; sandbox provider only, no money.
    # ======================================================================
    stamp = str(int(time.time()))
    r = httpx.post(f"{BASE}/auth/register",
                   json={"email": f"p3-e2e-{stamp}@test.local",
                         "password": "p3-e2e-password-1",
                         "display_name": "P3 E2E"},
                   timeout=30)
    check("P3 register 201", r.status_code == 201, f"got {r.status_code}")
    if r.status_code != 201:
        return _finish(t0)
    reg = r.json()
    p3_headers = {"Authorization": f"Bearer {reg['token']}"}
    org_id = reg.get("organization", {}).get("id")
    check("P3 register returns personal organization", bool(org_id))

    # onboarding: 9-step state machine is resumable and skippable
    r = httpx.get(f"{BASE}/onboarding/progress", headers=p3_headers, timeout=30)
    check("P3 onboarding progress 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        steps = r.json().get("steps", [])
        check("P3 onboarding declares 9 steps", len(steps) == 9,
              f"got {len(steps)}")
    r = httpx.post(f"{BASE}/onboarding/account-type", headers=p3_headers, timeout=30,
                   json={"account_type": "individual"})
    check("P3 onboarding account-type 200", r.status_code == 200, f"got {r.status_code}")

    # billing: public catalog (anonymous), free floor, subscription lifecycle
    r = httpx.get(f"{BASE}/billing/plans", timeout=30)
    check("P3 plans catalog anonymous 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        codes = [p["code"] for p in r.json().get("items", [])]
        check("P3 catalog has 5 plans in order",
              codes == ["free", "starter", "professional", "business", "enterprise"],
              str(codes))
    r = httpx.get(f"{BASE}/billing/entitlements", headers=p3_headers,
                  params={"organization_id": org_id}, timeout=30)
    check("P3 entitlements free floor 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        ents = r.json().get("entitlements", {})
        check("P3 free floor max_farms=1 (plan named)",
              ents.get("max_farms", {}).get("value") == 1
              and ents.get("max_farms", {}).get("plan_code") == "free",
              str(ents.get("max_farms")))
    r = httpx.post(f"{BASE}/billing/subscription", headers=p3_headers, timeout=30,
                   json={"organization_id": org_id, "plan_code": "free",
                         "billing_period": "monthly"})
    check("P3 start free subscription 200", r.status_code == 200, f"got {r.status_code}")
    r2 = httpx.post(f"{BASE}/billing/subscription", headers=p3_headers, timeout=30,
                    json={"organization_id": org_id, "plan_code": "starter",
                          "billing_period": "monthly"})
    check("P3 double-start rejected 409", r2.status_code == 409, f"got {r2.status_code}")

    # entitlement enforcement is SERVER-side: second farm exceeds free plan
    r = httpx.post(f"{BASE}/farms", headers=p3_headers, timeout=30,
                   json={"name": f"P3 E2E Farm {stamp}", "country_code": "EG",
                         "timezone": "Africa/Cairo", "currency_code": "EGP"})
    check("P3 first farm 201", r.status_code == 201, f"got {r.status_code}")
    farm_id = r.json().get("id") if r.status_code == 201 else ""
    r = httpx.post(f"{BASE}/farms", headers=p3_headers, timeout=30,
                   json={"name": f"P3 E2E Farm Two {stamp}", "country_code": "EG",
                         "timezone": "Africa/Cairo", "currency_code": "EGP"})
    check("P3 second farm blocked 402 (plan limit)", r.status_code == 402,
          f"got {r.status_code}")
    if r.status_code == 402:
        check("P3 402 names the entitlement", "max_farms" in r.text)

    # notifications center: list + unread count are tenant-scoped and empty
    r = httpx.get(f"{BASE}/notifications", headers=p3_headers, timeout=30)
    check("P3 notifications list 200", r.status_code == 200, f"got {r.status_code}")
    r = httpx.get(f"{BASE}/notifications/unread-count", headers=p3_headers, timeout=30)
    check("P3 unread count 200", r.status_code == 200, f"got {r.status_code}")

    # Retain the Free export-denial assertion before changing the plan.
    r = httpx.post(f"{BASE}/reports", headers=p3_headers, timeout=30,
                   json={"report_type": "org_executive", "format": "csv", "sync": True})
    check("P3 free-plan report export denied 403", r.status_code == 403,
          f"got {r.status_code}")
    r = httpx.post(f"{BASE}/orgs/{org_id}/invitations", headers=p3_headers, timeout=30,
                   json={"email": f"free-denied-{stamp}@test.local", "role_code": "viewer"})
    check("P3 Free pending invitation created", r.status_code == 201,
          f"got {r.status_code}")
    if r.status_code == 201:
        invitation_token = r.json().get("token")
        invitee = httpx.post(
            f"{BASE}/auth/register",
            json={"email": f"free-denied-{stamp}@test.local",
                  "password": "free-invitee-password-1",
                  "display_name": "Free seat-limit invitee"},
            timeout=30,
        )
        check("P3 Free invitee registration 201", invitee.status_code == 201,
              f"got {invitee.status_code}")
        if invitee.status_code == 201 and invitation_token:
            accepted = httpx.post(
                f"{BASE}/invitations/accept",
                headers={"Authorization": f"Bearer {invitee.json()['token']}"},
                json={"token": invitation_token},
                timeout=30,
            )
            check("P3 Free seat cap blocks invite acceptance 402",
                  accepted.status_code == 402, f"got {accepted.status_code}")
            if accepted.status_code == 402:
                check("P3 invite denial names max_org_members",
                      "max_org_members" in accepted.json()["error"]["message"])
    r = httpx.post(f"{BASE}/developer/keys", headers=p3_headers, timeout=30,
                   json={"name": "Free denied key", "scopes": ["org:read"], "organization_id": org_id})
    check("P3 Free API issuance denied 403", r.status_code == 403,
          f"got {r.status_code}")
    if r.status_code == 403:
        check("P3 API denial names disabled plan feature",
              "not part of your current plan" in r.json()["error"]["message"])
    # Synthetic sandbox subscription transition only: no real charge/send.
    r = httpx.post(f"{BASE}/billing/subscription/change", headers=p3_headers, timeout=30,
                   json={"organization_id": org_id, "new_plan_code": "professional",
                         "billing_period": "monthly"})
    check("P3 synthetic paid-tier upgrade 200", r.status_code == 200,
          f"got {r.status_code}")

    # team: invite a viewer, member directory reflects it
    r = httpx.post(f"{BASE}/orgs/{org_id}/invitations", headers=p3_headers, timeout=30,
                   json={"email": f"p3-invitee-{stamp}@test.local", "role_code": "viewer"})
    check("P3 invitation created 201", r.status_code == 201, f"got {r.status_code}")
    r = httpx.get(f"{BASE}/orgs/{org_id}/invitations", headers=p3_headers, timeout=30)
    check("P3 pending invitations listed", r.status_code == 200
          and len(r.json().get("items", [])) >= 1, f"got {r.status_code}")

    # developer: key created (show-once), public API requires it, tenant-scoped
    r = httpx.post(f"{BASE}/developer/keys", headers=p3_headers, timeout=30,
                   json={"name": "e2e smoke key",
                         "scopes": ["org:read", "farms:read"],
                         "organization_id": org_id})
    check("P3 api key created 201", r.status_code == 201, f"got {r.status_code}")
    key_secret = r.json().get("secret", "") if r.status_code == 201 else ""
    check("P3 api key plaintext shown once", bool(key_secret))
    r = httpx.get(f"{BASE}/public/v1/org", timeout=30)
    check("P3 public API without key rejected 401", r.status_code == 401,
          f"got {r.status_code}")
    if key_secret:
        pub_headers = {"X-API-Key": key_secret}
        r = httpx.get(f"{BASE}/public/v1/org", headers=pub_headers, timeout=30)
        check("P3 public API with key 200", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            check("P3 public API scoped to key's org", r.json().get("id") == org_id)
        # tenant isolation: the demo org's farm is invisible to this key
        if farm_id:
            r = httpx.get(f"{BASE}/public/v1/farms/{farm_id}", headers=pub_headers, timeout=30)
            check("P3 public API own farm visible", r.status_code == 200,
                  f"got {r.status_code}")
        demo_farm_id = ""
        r = httpx.get(f"{BASE}/farms", headers=headers, timeout=30)
        demo_items = r.json().get("items", []) if r.status_code == 200 else []
        if demo_items:
            demo_farm_id = demo_items[0]["id"]
            r = httpx.get(f"{BASE}/public/v1/farms/{demo_farm_id}",
                          headers=pub_headers, timeout=30)
            check("P3 cross-tenant farm invisible 404", r.status_code == 404,
                  f"got {r.status_code}")

    # Paid-tier report creation is checked only on synthetic sandbox data.
    r = httpx.post(f"{BASE}/reports", headers=p3_headers, timeout=30,
                   json={"report_type": "org_executive", "format": "csv", "sync": True})
    check("P3 synthetic CSV report created 201", r.status_code == 201,
          f"got {r.status_code}")
    if r.status_code == 201:
        report = r.json()
        check("P3 synthetic CSV report succeeded", report.get("status") == "succeeded",
              str(report.get("error")))
        report_id = report.get("id")
        if report_id and report.get("status") == "succeeded":
            downloaded = httpx.get(f"{BASE}/reports/{report_id}/download", headers=p3_headers, timeout=30)
            check("P3 synthetic CSV download 200", downloaded.status_code == 200,
                  f"got {downloaded.status_code}")

    # ops health: aggregate surface, authenticated, no secrets
    r = httpx.get(f"{BASE}/ops/health", headers=p3_headers, timeout=30)
    check("P3 ops health 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check("P3 ops health status enum", body.get("status") in ("ok", "degraded"),
              str(body.get("status")))
        check("P3 ops health billing provider sandbox",
              body.get("billing", {}).get("provider") == "sandbox"
              and body.get("billing", {}).get("mode") == "test",
              str(body.get("billing")))

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
