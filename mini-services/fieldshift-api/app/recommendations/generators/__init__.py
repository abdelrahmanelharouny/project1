"""Domain generators — one module per recommendation domain.

Each module registers its generators on the central registry at import time
(app/recommendations/generators/__init__.py imports them all so registration
happens whenever the package is imported). Generators read the SHARED
RecommendationContext only — they never rebuild the evidence pack and never
re-run engines.
"""

from app.recommendations.generators import (  # noqa: F401
    climate,
    management,
    rotation,
    soil,
    water,
)
