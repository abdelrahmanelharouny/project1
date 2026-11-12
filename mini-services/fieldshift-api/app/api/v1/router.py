"""v1 API router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    activity,
    analytics,
    auth,
    billing,
    climate,
    data_platform,
    decision,
    developer,
    digital_twin,
    evidence_gaps,
    failure_lab,
    farms,
    features,
    field_states,
    fields,
    health,
    jobs,
    knowledge,
    management,
    members,
    metrics,
    notifications,
    onboarding,
    ops,
    orgs,
    portfolio,
    preferences,
    public_v1,
    recommendations,
    reports,
    robust_rotation,
    rotation,
    scenario_executions,
    scenarios,
    sensitivity,
    soil,
    soil_memory,
    vegetation,
    water,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(members.router)
api_router.include_router(farms.router)
api_router.include_router(fields.router)
# jobs BEFORE data_platform: its literal /jobs/background routes must win
# over data_platform's parameterized /jobs/{job_id} (FastAPI matches in
# registration order).
api_router.include_router(jobs.router)
api_router.include_router(data_platform.router)
api_router.include_router(features.router)
api_router.include_router(knowledge.router)
api_router.include_router(rotation.router)
api_router.include_router(water.router)
api_router.include_router(field_states.router)
api_router.include_router(scenarios.router)
api_router.include_router(soil.router)
api_router.include_router(management.router)
api_router.include_router(scenario_executions.router)
api_router.include_router(sensitivity.router)
api_router.include_router(robust_rotation.router)
api_router.include_router(decision.router)
api_router.include_router(digital_twin.router)
api_router.include_router(recommendations.router)
# P2 intelligence routers — all field/farm-scoped paths are literal and
# non-conflicting with the routers above.
api_router.include_router(vegetation.router)
api_router.include_router(climate.router)
api_router.include_router(soil_memory.router)
api_router.include_router(failure_lab.router)
api_router.include_router(evidence_gaps.router)
api_router.include_router(portfolio.router)
# Prometheus exposition (unauthenticated by design — loopback bind +
# route-template labels only; see app/api/v1/metrics.py).
api_router.include_router(metrics.router)

# P3 SaaS platform routers — all prefixes are literal and non-conflicting
# with the routers above (orgs/billing/onboarding/notifications/analytics/
# preferences/reports/developer/public). Registered last; /public/v1 carries
# its own API-key authentication rather than the bearer Principal flow.
api_router.include_router(orgs.router)
api_router.include_router(billing.router)
api_router.include_router(onboarding.router)
api_router.include_router(notifications.router)
api_router.include_router(analytics.router)
api_router.include_router(preferences.router)
api_router.include_router(activity.router)
api_router.include_router(reports.router)
api_router.include_router(developer.router)
api_router.include_router(ops.router)
api_router.include_router(public_v1.router)
