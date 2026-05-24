"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from paper2beamer.api.routes import upload, jobs, templates, settings
from paper2beamer.web.router import router as web_router
from paper2beamer.db.database import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    Path("data/uploads").mkdir(parents=True, exist_ok=True)
    yield
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="paper2beamer",
        description="Convert math/statistics papers into Beamer presentations",
        version="0.1.0",
        lifespan=lifespan,
    )

    static_dir = Path(__file__).parent.parent / "web" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(upload.router, prefix="/api", tags=["upload"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    app.include_router(templates.router, prefix="/api", tags=["templates"])
    app.include_router(settings.router, prefix="/api", tags=["settings"])

    app.include_router(web_router, tags=["web"])

    return app
