"""HandoffRail API Server — Routers package init."""

from app.routers.dashboard import router as dashboard_router
from app.routers.health import router as health_router
from app.routers.hooks import router as hooks_router
from app.routers.keys import router as keys_router
from app.routers.metrics import router as metrics_router
from app.routers.packets import router as packets_router
from app.routers.websocket import router as websocket_router

__all__ = [
    "packets_router",
    "keys_router",
    "hooks_router",
    "health_router",
    "metrics_router",
    "dashboard_router",
    "websocket_router",
]
