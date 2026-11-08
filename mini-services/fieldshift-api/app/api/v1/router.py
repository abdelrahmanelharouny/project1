"""v1 API router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    data_platform,
    decision,
    digital_twin,
    farms,
    features,
    field_states,
    fields,
    health,
    jobs,
    knowledge,
    management,
    members,
    robust_rotation,
    rotation,
    scenario_executions,
    scenarios,
    sensitivity,
    soil,
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
