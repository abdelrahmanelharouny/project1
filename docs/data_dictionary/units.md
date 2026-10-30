# Data Dictionary — Units and Conversions

Internal storage units follow the master data dictionary (`variables.md`). No unit conversion engine exists yet in this slice: values are stored exactly as the provider normalized them, and the canonical catalog defines the expected unit per variable.

Planned conventions (Master §15, enforced from Milestone 4 onward):

- Every conversion preserves: source unit, factor, conversion version, and who performed it (processing_version).
- 1 mm over 1 ha = 10 m³ (water volume conversions must respect area basis).
- Yield stores value + commodity unit + moisture/content basis.
- Prices/costs store amount + ISO currency + date + source.
- Never convert without verifying depth/basis (e.g., soil organic carbon per depth interval and mass basis).

Current status: synthetic provider emits catalog units directly (`degC`, `mm`, `m3/m3`, `m/s`); the ingestion service rejects nothing on unit grounds yet because there is only one source, but the canonical unit contract is already enforced by the provider contract tests.
