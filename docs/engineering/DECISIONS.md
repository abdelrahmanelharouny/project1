# Engineering Governance Decisions

This file records cross-workstream coordination and release decisions only. Detailed product, data, scientific and architecture ADRs remain in [`docs/implementation/DECISIONS_AND_ASSUMPTIONS.md`](../implementation/DECISIONS_AND_ASSUMPTIONS.md); do not duplicate them here.

| ID | Date | Decision | Rationale / consequence | Status |
| --- | --- | --- | --- | --- |
| GOV-001 | 2026-11-14 | `main` is not modified or merged by the supervisor without explicit promotion approval. Feature integration occurs on a dedicated branch. | Preserve independent work and make review reversible; a PR or feature-branch push is not permission to merge main. | Active |
| GOV-002 | 2026-11-14 | Create `integration/cropshift-control` from verified `origin/main` `998f7a5885e4ee0c9defe28671736560fb1b8762`; add control docs only before integration readiness. | Central coordination needs a stable ref, but control-system setup is not justification to merge unverified code. | Active |
| GOV-003 | 2026-11-14 | Distinguish verified Git refs from task-reported local refs and task messages; mark inaccessible state explicitly. | Separate Manus sandboxes are not shared worktrees. Task completion text is not evidence of a remote ref or live test. | Active |
| GOV-004 | 2026-11-14 | Main CI failures block release and integration: `alembic check` detects model/migration drift; bridge typecheck cannot find Bun type definitions. | The same failures are observed on main and GIS PR; [issue #2](https://github.com/abdelrahmanelharouny/project1/issues/2) tracks the safe fix and acceptance checks. Do not waive either job. | Open |
| GOV-005 | 2026-11-14 | Keep remediation commit `6dc6048` preserved but out of the integration branch until the reported stale-job, Free-plan scenario-metering and seasonal-rotation concerns are independently checked. | Protect security/data/science changes without accepting unresolved high-impact review findings. | Open |
| GOV-006 | 2026-11-14 | GitHub activity monitoring is read-only and alert-only; it must never autonomously edit, push, merge, close issues/PRs, or change secrets. | Prevent an event payload or trigger from becoming an unreviewed code/repository action. Trigger is enabled but source sync is pending; do not claim it is operational yet. | Active / pending source sync |
| GOV-007 | 2026-11-14 | Use [`PROJECT_STATUS.md`](PROJECT_STATUS.md), [`BRANCH_REGISTRY.md`](BRANCH_REGISTRY.md), and [`INTEGRATION_QUEUE.md`](INTEGRATION_QUEUE.md) as the single coordination sources; the existing audit, gap analysis, ADRs and dated milestone reports remain the technical sources. | Avoid redundant status/architecture documents and update the correct canonical record after changes. | Active |
| GOV-008 | 2026-11-14 | Do not build the Figma task's separate blank scaffold as CropTwist. | The task reported its workspace is not the actual project1 repository; first prove repository identity and design scope. | Open |

## Decision log maintenance

Append a row for each durable cross-workstream integration, migration, safety or release decision. Link affected PRs, commits and test evidence. Temporary status belongs in `PROJECT_STATUS.md` or `INTEGRATION_QUEUE.md`, not as a new ADR.
