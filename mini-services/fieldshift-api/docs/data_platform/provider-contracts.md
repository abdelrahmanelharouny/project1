# Data Platform — Provider Contracts

How external environmental data enters CropTwist, and the guarantees every
provider implementation must uphold. Implementation:
`app/data_platform/` (registry, ingestion, imports, providers, contracts,
observability).

## Provider protocol

Every provider implements the `EnvironmentalDataProvider` protocol:

- `provider_code` / product identity plus a `SourceProvenance` record
  (license, attribution text, documentation URL, retrieval method, known
  limitations) persisted with every ingested record.
- Capability discovery (variables, coverage windows, spatial support) used
  by the registry and the passport readiness logic.
- Fetch by variable + geometry + period, returning canonical observation
  payloads — never raw provider payloads.

## Shipped providers

| Provider | Data | Notes |
| --- | --- | --- |
| `open_meteo` | ERA5 / ERA5-Land daily reanalysis (historical archive) | Gridded reanalysis estimate, labelled as such in provenance; not a field sensor. Base URL/timeout configurable. |
| `soilgrids` | ISRIC SoilGrids WCS soil properties | Remote-sensing model predictions; keeps the prediction label end-to-end. |
| `chirps` | CHIRPS rainfall from local GeoTIFF | Extraction only; no live API client. |
| `synthetic` | Deterministic SHA-256-seeded fixture generator | Climate profiles with injected data gaps; identical requests yield identical series; every record labelled `is_synthetic=true`. **No agronomic validity** — software fixtures with invented shape parameters. |

Intentionally absent (adapter seam reserved, nothing simulated): weather
forecast, climate projection, NASA/satellite products — see
`../KNOWN_LIMITATIONS.md`.

## Contract tests

`tests/contract/` pins each provider's behavior:

- **Determinism:** the synthetic provider returns byte-identical series for
  identical requests (seeded hashing; no clock, no randomness).
- **Honesty:** provenance travels with the data; synthetic records are
  flagged everywhere they surface (passport, features, UI badges).
- **Gaps stay gaps:** injected missing values remain missing (NULL, never
  zero) through ingestion and feature computation.
- **Farmer CSV import:** `tests/contract/test_farmer_csv_import.py` covers
  the CSV ingestion path (`app/data_platform/imports/csv_service.py`),
  including unit validation and rejection reporting.

## Ingestion guarantees

- Jobs persist state: records received / rejected, warnings, structured
  failures (HTTP 202 + job resource).
- **Idempotent reruns** via natural-key uniqueness — re-posting the same
  payload does not duplicate observations.
- Upload guards: `CROPTWIST_MAX_IMPORT_FILE_BYTES` caps CSV/GeoTIFF sizes
  (default 32 MB).
- Provider availability probes (`provider_probe_*` settings) feed the
  data-platform status view with a small in-process TTL cache.

## Variables

The canonical variable catalog (`app/data_platform/contracts/variables.py`)
is versioned; observations reference catalog codes. Missing fields are
stored as NULL — the platform never zero-fills (contract shared with the
feature engine and every downstream analytics module).
