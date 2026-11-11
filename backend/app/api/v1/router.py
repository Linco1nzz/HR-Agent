"""v1 路由汇总。新增业务路由时在此 include。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import ai, auth, health, jds, resume_evaluations, scoring_criteria

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(ai.router)
api_router.include_router(jds.router)
api_router.include_router(scoring_criteria.router)
api_router.include_router(resume_evaluations.router)
