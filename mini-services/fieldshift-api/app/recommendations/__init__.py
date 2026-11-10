"""Central recommendation system (Recommendation layer).

ALL product suggestions flow from here: domain generators register on the
registry, a refresh runs them against one prebuilt evidence context, persists
a new generation (superseding the old) and optionally adds LLM narratives.

Importing this package imports every generator module so registration is
complete: `from app.recommendations import registry`  (then registry.run_all).
"""

from app.recommendations import contracts, registry  # noqa: F401
from app.recommendations.generators import (  # noqa: F401,E402,F401
    climate,
    management,
    rotation,
    soil,
    water,
)
from app.recommendations.registry import registry as default_registry  # noqa: F401
