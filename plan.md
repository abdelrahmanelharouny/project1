# CropTwist integration execution plan

## Scope and preserved baseline

Work in the existing repository on `feature/ai-complete-integration`, starting at `d590be057c1993fd75e796b7c8365ab07db2eb87`. The existing 14 tracked modifications and five untracked AI files are intentional in-progress work. Their recoverable patch/archive snapshot is outside the repository at `/home/ubuntu/checkpoints/croptwist-ai-d590be0-20261114`. Preserve `main`, source branches, valid AI/GIS implementations and history. Only ordinary non-force pushes to the integration branch are authorized.

## Implementation approach

Retain the authenticated AI Core, typed contracts, deterministic planner, bounded tool registry and existing agronomic evidence collector. Complete the environment-configured Gemini → Groq → OpenRouter routing with transient-only failover, safe telemetry and privacy gates. Finish tenant/model-isolated knowledge ingestion, embeddings and retrieval with approved-source metadata; no corpus or live connectivity is fabricated. Complete consented feedback lifecycle and deletion/retention. Wire the existing Copilot screen to AI Core and owner-scoped conversation APIs, keeping every existing destination and selected-field context.

The six remediation concerns are reviewed independently from their actual branch source before fixes. Corrected remediation receives focused regression coverage before integration; merge overlap and migration heads are inspected deliberately. Background-job recovery, scenario quota accounting, crop-season scoring, signup/seat limits, API-key lifecycle and invoice-bound callbacks remain release gates until their cases are tested.

Restore the existing pinned frontend toolchain. Run focused and full database-independent suites, then isolated disposable PostgreSQL/PostGIS migrations and integration checks where infrastructure permits. Do not touch shared or production data. Browser journeys use only a disposable local test environment. Live LLM, Earthdata acquisition, delivery adapters and external artifacts require real configured services and remain explicit blockers unless exercised.

## Existing design

Reuse CropTwist's current component library, visual hierarchy, localization and responsive layouts. Copilot remains part of AI Insights and the nine-destination navigation, not a separate chatbot. Sources, uncertainty, missing-data states and errors must be visible. Preserve English/Arabic and RTL. No decorative asset changes are needed.

## Project structure

- `src/components/croptwist/`: existing product screens and Copilot UI.
- `src/hooks/`, `src/lib/`: context-aware query hooks, client API and contracts.
- `messages/en/`, `messages/ar/`: matched localization.
- `mini-services/fieldshift-api/app/intelligence/orchestration/`: lifecycle, planning, tools, providers, knowledge and retention.
- `mini-services/fieldshift-api/app/api/v1/`: authenticated API integration.
- `mini-services/fieldshift-api/app/db/` and `migrations/`: ORM metadata and ordered additive schema changes.
- Existing domain services: agronomic calculations, jobs, billing, identity and entitlements; corrections stay in their owning services.
- `tests/`, backend `tests/`: focused regression and integration suites.
- `docs/implementation/`: exact execution evidence, commit provenance, blockers and release status.
