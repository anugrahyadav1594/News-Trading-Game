from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.games import router as games_router
from app.api.v1.orders import router as orders_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(games_router)
api_v1_router.include_router(orders_router)
api_v1_router.include_router(admin_router)


@api_v1_router.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "NEWS TRADING — MTT Exchange Engine",
        "simulation_mode": "ACTIVE",
    }
