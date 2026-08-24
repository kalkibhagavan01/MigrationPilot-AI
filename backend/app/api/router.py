from fastapi import APIRouter

from app.api import audit, auth, escalations, migrations, mock_target, ops

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(migrations.router)
api_router.include_router(audit.router)
api_router.include_router(escalations.router)
api_router.include_router(mock_target.router)
api_router.include_router(ops.router)
