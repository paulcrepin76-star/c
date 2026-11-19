from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.domain import ensure_profiles

STATIC_CANDIDATES = [
    Path("/app/static"),
    Path(__file__).resolve().parents[1] / "frontend" / "dist",
]


def static_dir() -> Path | None:
    for path in STATIC_CANDIDATES:
        if (path / "index.html").is_file():
            return path
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_profiles(db)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Survey Café Command", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.command_secret_key or "command-dev-session",
        session_cookie="survey_command",
        same_site="lax",
        https_only=settings.command_https_only,
        max_age=60 * 60 * 12,
    )
    app.include_router(api_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        detail = exc.detail
        if not isinstance(detail, str):
            detail = str(detail)
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        folder = static_dir()
        if folder is None:
            return JSONResponse(
                {"status": "ok", "ui": "not-built", "detail": "The API is up. Build the frontend to serve the dashboard."},
                status_code=200 if full_path == "" else 404,
            )
        candidate = (folder / full_path).resolve()
        if full_path and str(candidate).startswith(str(folder.resolve())) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(folder / "index.html")

    return app


app = create_app()
