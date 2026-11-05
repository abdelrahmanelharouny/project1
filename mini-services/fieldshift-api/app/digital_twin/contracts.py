"""Contracts and bounds for the digital twin (Milestone 7.7)."""

VALIDATION_VERSION = "digital-twin-validation-1.0"
TWIN_VIEW_VERSION = "digital-twin-view-1.0"

# Bounded assembly (read-only view).
MAX_STATES = 10
MAX_FEATURE_RUNS = 8
MAX_SCENARIOS = 12
MAX_EXECUTIONS_PER_SCENARIO = 5
MAX_SCENARIO_SETS = 5
MAX_ROBUST_RUNS_PER_SET = 3
MAX_DECISION_DOCS = 5
MAX_SOIL_MGMT_RUNS = 8

# Bounded validation walk (re-verification is CPU-bound; documented caps).
MAX_STATES_VALIDATED = 6
MAX_SCENARIOS_VALIDATED = 8
MAX_EXECUTIONS_VALIDATED = 6
MAX_ANALYSES_VALIDATED = 6
MAX_ROBUST_RUNS_VALIDATED = 6
MAX_DECISION_DOCS_VALIDATED = 6
MAX_SOIL_MGMT_RUNS_VALIDATED = 6

OVERALL_STATUSES = ("consistent", "inconsistent", "no_artifacts")
