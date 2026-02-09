import os
import sys

# Ensure project root is on sys.path so 'config' and 'db' are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from webapp.routers import signals, traders, dashboard


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Prevent Telegram WebView from caching stale JS/CSS."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.endswith((".html", ".js", ".css")) or path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


app = FastAPI(title="Poly Smart Radar API", version="1.0.0")

app.add_middleware(NoCacheStaticMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
def health():
    return {"status": "ok"}


app.include_router(health_router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(traders.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")

# Serve frontend static files if directory exists (must be last — catch-all)
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
