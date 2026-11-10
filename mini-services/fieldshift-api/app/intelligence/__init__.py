"""Intelligence layer: LLM advisor bridge, evidence assembly, anomaly
detection, advisor answers and recommendation narratives.

Layer contract (docs/architecture/AI_LAYERS.md):
- Every function here is GROUNDED in deterministic engine outputs — the LLM
  narrates evidence, it never invents numbers.
- The LLM bridge is OPTIONAL: every function degrades gracefully to a
  rules-only answer when the bridge is unreachable, disabled or malformed.
  Recommendation and insight endpoints must never fail because of the LLM.
- Reads engine outputs read-only (latest runs per domain); nothing here
  mutates engine tables.
"""

from app.intelligence import anomaly, bridge, config, evidence  # noqa: F401
