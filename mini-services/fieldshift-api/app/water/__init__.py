"""Water Intelligence Engine (Milestone 6A).

Pure decision core: `contracts`, `curve`, `effective_rainfall`, `soil`,
`requirements`, `knowledge`, `planner` — no ORM/HTTP imports (ADR-0015).
The DB bridge lives in `app.water.service`; the HTTP layer in
`app.api.v1.water`.
"""

from app.water.contracts import (  # noqa: F401
    EFFECTIVE_RAINFALL_METHODS,
    IRRIGATION_EFFICIENCY_CLASSES,
    SOIL_SOURCES,
    PTF_VERSION,
    WATER_ENGINE_VERSION,
    WATER_METHODS_VERSION,
)
