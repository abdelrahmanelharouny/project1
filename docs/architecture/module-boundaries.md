# Module Boundaries

Dependency direction (arrows point "may import"):

```
api/v1 ──► domains ──► db (models)
  │            │  ▲
  │            ▼  │
  ├─────► data_platform (contracts, registry, providers, ingestion)
  ├─────► passport
  └─────► geospatial

data_platform ──► contracts, db, core
providers ──► contracts ONLY (never db, never routers)
passport ──► db, contracts
core ──► (nothing above it)
```

Rules enforced in this slice:

1. **Routers** (`app/api/v1/*`) parse requests, resolve the `Principal`, call domain/application services, serialize responses. No SQL beyond session plumbing.
2. **Domain services** (`app/domains/*`) own business rules and persistence for their aggregate (farms/fields: versioning + audit; identity: registration/tokens/authorization).
3. **Provider adapters** (`app/data_platform/providers/*`) map their payloads into canonical DTOs. They MUST NOT import ORM models or FastAPI types. The synthetic provider is a pure function of its request (no I/O).
4. **Canonical contracts** (`app/data_platform/contracts/*`) are the only interchange vocabulary between providers, ingestion, storage, and the passport. Pydantic v2 models; no ORM leakage.
5. **Ingestion** (`app/data_platform/ingestion`) orchestrates job lifecycle and persistence; it is the only place that writes `observations`/`observation_quality_flags` from provider results.
6. **Passport** (`app/passport`) is read-only aggregation; it never mutates data and never merges quality concepts into a single score.
7. **Geospatial** (`app/geospatial`) is a pure library (Shapely/PyProj) — reusable by ingestion or future importers.
8. **core** (`app/core`) provides config/database/errors/security/logging to everyone; imports nothing from layers above.

Frontend mirrors this: `src/lib/api.ts` (typed transport, the only place that knows about `XTransformPort`), `src/lib/types.ts` (contract types), `src/hooks/use-fieldshift.ts` (server state), `src/components/fieldshift/*` (presentation), `src/lib/store.ts` (ephemeral UI state).
