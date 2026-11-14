# CropTwist Integration Queue

**Snapshot:** 2026-11-14 03:07 UTC+02:00. The supervisor's docs-only `integration/cropshift-control` branch is published; no feature branch has been merged into it. Queue order reflects dependencies and reported risks, not feature priority alone.

## Queue

| Order | Change / ref | State | Dependencies and blockers | Required decision / evidence | Integration outcome |
| --- | --- | --- | --- | --- | --- |
| 0 | Repository CI baseline (`main` `998f7a5`) / [issue #2](https://github.com/abdelrahmanelharouny/project1/issues/2) | **Release/integration blocker** | Backend `alembic check` detects model/migration drift; frontend bridge typecheck fails `TS2688` because Bun type definitions are missing in the frontend job. Both failures occur on main and on GIS PR runs. | Fix CI configuration/model-migration consistency in small reviewed changes; run full main workflow successfully, including disposable PostGIS migration checks, pytest and E2E. Do not waive failing mandatory checks. | No integration branch can be called green until resolved. |
| 1 | GIS: `feature/gis-spatial-analytics` `0ed6039` / PR #1 | **Awaiting review; CI blocked** | Based directly on main; no migration changes. PR #1 is open and `UNSTABLE`; two jobs fail in each of push and PR workflows. PostGIS suites were not run in the GIS task. | Review complete diff; fix shared CI baseline; verify raster sample/zone/partial-index paths against API contracts and PostGIS; rerun full CI. | Merge to global integration only after all gates pass. Do not merge PR #1 or alter main from this control task. |
| 2 | AI Core baseline `feature/ai-core-orchestration` / active `feature/ai-complete-integration` | **Active; task-local checkpoint committed, ordinary WIP remains unstaged** | AI task reports HEAD `2d03c9fe097fd2c46b42c5495b65123bea455ef6`, parent GIS merge `d590be057c1993fd75e796b7c8365ab07db2eb87`; common base `998f7a5885e4ee0c9defe28671736560fb1b8762`; GIS parent `0ed6039ce8072bc95e02ae614c2a2daba7900ef9`. Main reportedly remains at base. Separate `fix/remediation-release-gates` worktree owns six reported corrections. | Task reports disposable PostgreSQL 16.15/PostGIS 3.4.2 upgrade through migration `0025_ai_feedback_knowledge` passed; final migrations `0026/0027/0028` still need composition. Interim pure tests: 1,084 passed, 15 DB-bound deselected; Arabic/DSN/fallback slice: 21 passed. Two older AI integration tests still expose a stale provider-mock seam. No final full suite/CI, live provider validation or production claim. | Preserve task WIP. Its user mission authorizes that AI task to complete and integrate corrected remediation onto `feature/ai-complete-integration`, then push only that branch after verification. No remote feature push reported; never push/merge main. |
| 3 | Legacy remediation `remediation/legacy-hardening` `6dc6048` / correction `fix/remediation-release-gates` | **Original preserved; correction in progress elsewhere** | Original branch remains local and unmerged. AI task reports six confirmed fixes are being implemented/tested on a dedicated correction branch in another local worktree; its HEAD, exact diff, test agent IDs and final results are not available in this checkout. | Await task-owned final test report and review the correction diff. Verify tenant/auth, billing, quotas, durable jobs, data integrity and seasonal optimizer behavior against the disposable PostGIS schema and full migration chain. | Only the AI task is authorized by its new mission to integrate the corrected changes into its feature branch and push that branch after verification. Original `6dc6048` remains preserved; this supervisor will not apply or merge the correction. |
| 4 | Figma website/design task `AjYPACwwJ64QKCsudAOBG8` | **Stopped; waiting for repo inspection** | Task confirmed Figma is accessible and its empty scaffold branch `main` `0d0edff` is separate, with no CropTwist edits. Supervisor supplied `https://github.com/abdelrahmanelharouny/project1`; no response to that handoff yet. | Read-only inspect the exact repo, branch and worktree first; compare its proposed UI changes with the GIS map/satellite UI files and wait for explicit feature-branch plan. | Keep the unrelated scaffold and notes separate; do not integrate it. |
| 5 | `integration/cropshift-control` | **Published docs-only control branch** | Created from main base; initial checkpoint `ad9bb2c2e7b18d33b9b536bcdad590dc87253e7a` is on `origin`, followed by this status-only refresh. Feature refs intentionally not merged. | Keep issue/PR status and task reports current; refresh the control snapshot without importing task-local source. | Canonical coordination branch, not a release-ready integrated product. |

## Shared review findings

### PR #1 — verified GitHub state

- Title: `feat(gis): add raster inspection and partial index processing`.
- URL: https://github.com/abdelrahmanelharouny/project1/pull/1
- Base: main `998f7a5885e4ee0c9defe28671736560fb1b8762`.
- Head: `feature/gis-spatial-analytics` `0ed6039ce8072bc95e02ae614c2a2daba7900ef9`.
- Status: OPEN; merge state `UNSTABLE`; no review decision; 18 changed files; no migration file.
- Failed check rows: backend and frontend for both push and PR events. Distinct causes are baseline `alembic check` drift and missing Bun type definitions in the bridge typecheck. Main's latest run has the same failures. A branch report saying local build/lint passed does not satisfy failed GitHub required checks.

### Remediation review handoff

The prior AI review identified six remediation risk groups: (1) job-recovery lease/fencing and completed-work replay; (2) Free-plan scenario usage; (3) season-specific water/climate rotation scores; (4) non-dev verification, Free provisioning and seat concurrency; (5) API-key limits/rotation entitlement and invoice binding; (6) regression coverage and billing-test documentation. The latest AI task update now reports six confirmed fixes are being implemented with tests on `fix/remediation-release-gates`. The branch and tests are not visible here, so confirmation of the fixes' correctness is still pending independent review of its final diff and results.

### Integration order and safety

1. Fix main CI baseline and prove it passes.
2. Await the AI task's final provider-mock regressions and `0025`–`0028` migration composition. Its task-local PostGIS upgrade through 0025 and 1,084 pure tests are interim evidence only; obtain final commit/diff and full results before review.
3. Review GIS against the shared integration base, then run its database-backed tests and green CI.
4. Review the AI task's six remediation fixes after its correction branch tests finish; the AI task may integrate/push only `feature/ai-complete-integration` after verification. Do not apply its task-local patch in this supervisor worktree.
5. Verify the Figma task can open the exact public `project1` URL it was given; review overlap with GIS/UI before authorizing design code.
6. Integrate feature code with separate, reviewable commits; verify migration graph and cross-feature workflows after each merge.
7. Do not merge `main` or promote release state without explicit user approval.
