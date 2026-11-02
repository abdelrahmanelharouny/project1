"""v1 API router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    data_platform,
    farms,
    features,
    field_states,
    fields,
    health,
    knowledge,
    rotation,
    scenarios,
    water,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(farms.router)
api_router.include_router(fields.router)
api_router.include_router(data_platform.router)
api_router.include_router(features.router)
api_router.include_router(knowledge.router)
api_router.include_router(rotation.router)
api_router.include_router(water.router)
api_router.include_router(field_states.router)
api_router.include_router(scenarios.router)
