# CropTwist Integration Queue

**Snapshot:** 2026-11-14 02:42 UTC+02:00. No feature branch has been merged into the global `integration/cropshift-control` branch. Queue order reflects dependencies and verified risks, not feature priority alone.

## Queue

| Order | Change / ref | State | Dependencies and blockers | Required decision / evidence | Integration outcome |
| --- | --- | --- | --- | --- | --- |
| 0 | Repository CI baseline (`main` `998f7a5`) / [issue #2](https://github.com/abdelrahmanelharouny/project1/issues/2) | **Release/integration blocker** | Backend `alembic check` detects model/migration drift; frontend bridge typecheck fails `TS2688` because Bun type definitions are missing in the frontend job. Both failures occur on main and on GIS PR runs. | Fix CI configuration/model-migration consistency in small reviewed changes; run full main workflow successfully, including disposable PostGIS migration checks, pytest and E2E. Do not waive failing mandatory checks. | No integration branch can be called green until resolved. |
| 1 | GIS: `feature/gis-spatial-analytics` `0ed6039` / PR #1 | **Awaiting review; CI blocked** | Based directly on main; no migration changes. PR #1 is open and `UNSTABLE`; two jobs fail in each of push and PR workflows. PostGIS suites were not run in the GIS task. | Review complete diff; fix shared CI baseline; verify raster sample/zone/partial-index paths against API contracts and PostGIS; rerun full CI. | Merge to global integration only after all gates pass. Do not merge PR #1 or alter main from this control task. |
| 2 | AI Core baseline `feature/ai-core-orchestration` / active `feature/ai-complete-integration` | **Active; committed integration plus dirty AI workspace, not published** | Task reports head/merge commit `d590be057c1993fd75e796b7c8365ab07db2eb87`, common base main `998f7a5885e4ee0c9defe28671736560fb1b8762`, GIS parent `0ed6039ce8072bc95e02ae614c2a2daba7900ef9`. Working tree: 14 modified tracked, 5 untracked, none staged. Local migration `0025_ai_feedback_knowledge` follows `0024_ai_core_orchestration`; one Alembic head reported; no DB apply. | Preserve the active tree; request a safe commit/export when ready. Inspect migration status/graph and exact diff; run full main+AI+GIS checks on the combined candidate. Task reports 59 AI/provider unit passes and 7 GIS render passes/13 deselected; no CI/PostGIS integration. | GIS is merged only on this task-local branch; it is not the GitHub global integration. Do not cherry-pick its dirty tree. Review privacy, authorization, provider, migration and API boundaries. |
| 3 | Legacy remediation `remediation/legacy-hardening` `6dc6048` | **Held for review; not approved** | Local branch/bundle exists. AI task's read-only review raised possible recovery/replay fencing issues; unmetered Free-plan scenarios; omitted seasonal rotation water/climate scores; verification delivery, Free provisioning and seat-concurrency gaps; API-key unlimited usage/rotation entitlement and invoice callback binding risks; missing regression coverage. These are reported concerns, not confirmed root causes. No PostGIS suite ran. | Inspect each concern against exact source and tests; add focused regressions; run broader unit suite plus disposable-DB auth, billing, jobs and agronomy integrations and migrations. Classify each as confirmed/fixed/disproved. | No cherry-pick/merge until all high-impact findings are resolved or explicitly reviewed. Its 941-unit count alone is insufficient. |
| 4 | Figma website/design task `AjYPACwwJ64QKCsudAOBG8` | **Stopped; waiting for repo inspection** | Task confirmed Figma is accessible and its empty scaffold branch `main` `0d0edff` is separate, with no CropTwist edits. Supervisor supplied `https://github.com/abdelrahmanelharouny/project1`; no response to that handoff yet. | Read-only inspect the exact repo, branch and worktree first; compare its proposed UI changes with the GIS map/satellite UI files and wait for explicit feature-branch plan. | Keep the unrelated scaffold and notes separate; do not integrate it. |
| 5 | `integration/cropshift-control` | **Control-only local snapshot** | Created from main base; feature refs intentionally not merged. | Finish review, commit and publish only the control documentation; keep issue/PR status and task reports current. | Intended canonical coordination branch, not a release-ready integrated product. |

## Shared review findings

### PR #1 — verified GitHub state

- Title: `feat(gis): add raster inspection and partial index processing`.
- URL: https://github.com/abdelrahmanelharouny/project1/pull/1
- Base: main `998f7a5885e4ee0c9defe28671736560fb1b8762`.
- Head: `feature/gis-spatial-analytics` `0ed6039ce8072bc95e02ae614c2a2daba7900ef9`.
- Status: OPEN; merge state `UNSTABLE`; no review decision; 18 changed files; no migration file.
- Failed check rows: backend and frontend for both push and PR events. Distinct causes are baseline `alembic check` drift and missing Bun type definitions in the bridge typecheck. Main's latest run has the same failures. A branch report saying local build/lint passed does not satisfy failed GitHub required checks.

### Remediation review handoff

The active AI task has explicitly stated it will not integrate the remediation commit as-is. Its review lists six risk groups: (1) stale-job ownership/lease and replay of completed work; (2) Free-plan scenario quota usage not incremented; (3) missing season-specific water/climate rotation scores; (4) non-dev verification delivery, Free provisioning and member-seat races; (5) API-key unlimited-rate growth/rotation entitlement and exact invoice binding; (6) missing recovery/quota/concurrency regressions and stale billing-test docs. These are valid hold signals, not established root causes. A reviewer must inspect the diff/tests and mark every finding confirmed, fixed, or disproven before integration.

### Integration order and safety

1. Fix main CI baseline and prove it passes.
2. Obtain a safe copy of the AI task's reported `d590be057c1993fd75e796b7c8365ab07db2eb87` integration branch plus its 14 modified / 5 untracked files; inspect migration `0025_ai_feedback_knowledge`, API/security ownership and full tests.
3. Review GIS against the shared integration base, then run its database-backed tests and green CI.
4. Review remediation only after the three flagged issues are investigated; verify every database-backed/auth/billing/jobs/science path.
5. Verify the Figma task can open the exact public `project1` URL it was given; review overlap with GIS/UI before authorizing design code.
6. Integrate feature code with separate, reviewable commits; verify migration graph and cross-feature workflows after each merge.
7. Do not merge `main` or promote release state without explicit user approval.
