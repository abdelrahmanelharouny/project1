# CropTwist Project Control

**Snapshot date:** 2026-11-14 (UTC+02:00)<br>
**Repository:** [`abdelrahmanelharouny/project1`](https://github.com/abdelrahmanelharouny/project1)<br>
**Control branch:** `integration/cropshift-control`, created from `origin/main` at `998f7a5885e4ee0c9defe28671736560fb1b8762`. No feature branch was merged to establish this control system.

This is the navigation/index file only. Do not duplicate capability audits, technical ADRs, test details, or feature status here; their canonical records are linked below.

- [Project status and workstream inventory](docs/engineering/PROJECT_STATUS.md)
- [Branch registry](docs/engineering/BRANCH_REGISTRY.md)
- [Integration queue and decisions](docs/engineering/INTEGRATION_QUEUE.md)
- [Quality gates](docs/engineering/QUALITY_GATES.md)
- [Engineering governance decisions](docs/engineering/DECISIONS.md)
- [Tracked main-CI blocker, GitHub issue #2](https://github.com/abdelrahmanelharouny/project1/issues/2)
- [Repository-wide capability audit](docs/MASTER_REPOSITORY_AUDIT.md)
- [Gap analysis and roadmap](docs/MASTER_GAP_ANALYSIS.md)
- [Current remediation branch report](docs/implementation/REMEDIATION_STATUS_2026-11-14.md)
- [Existing technical decisions and assumptions (ADR source)](docs/implementation/DECISIONS_AND_ASSUMPTIONS.md)

## Operating boundary

The local checkout can inspect the authenticated GitHub repository and remote refs, list CropTwist Manus Project tasks and their accessible messages, and manage a GitHub activity Trigger. Other tasks' private workspaces and unreported in-progress files are not visible here. A task message is evidence of what that task reported, not proof of a branch existing remotely or of a test passing in this checkout. The branch registry labels repository refs versus task-reported refs explicitly.

`main` is not to be merged into or modified by this control task. Feature merges require a reviewed diff and the gates in `docs/engineering/QUALITY_GATES.md`; no implementation branch has been integrated into the global control branch in this initial setup.

## Update protocol

For each accessible workstream update, record: task ID and status; feature owner; branch, base and full commit; changed scope; exact verification results; blockers/dependencies; and whether it is ready for review or integration. Mark anything not observable as **unverified / not accessible**, not as complete. Refresh status after meaningful commits, PR changes, CI runs, failed gates, or integration decisions.

The GitHub activity monitor is configured as a read-only event alert for repository `abdelrahmanelharouny/project1`. At snapshot time it is enabled but its entry is still initializing with source synchronization pending. It does not watch local/unpushed files or other Manus task state and must not edit, push, merge, or close anything.
