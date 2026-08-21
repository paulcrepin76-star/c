from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.config import settings
from app.connect_routes import router as connect_router
from app.db import Base, SessionLocal, engine
from app.matching import match_sellables
from app.paperless_hook import ensure_paperless_sync_workflow
from app.purchasing import backfill_purchase_prices, ensure_purchasing
from app.catalog import ensure_catalog_suppliers
from app.schema import ensure_schema
from app.seed import ensure_connections, seed_if_empty
from app.web import router as web_router

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["money"] = lambda value: f"${value:,.2f}"
templates.env.filters["pct"] = lambda value: f"{value:.1f}%"
templates.env.filters["bottles"] = lambda value: f"{value:.2f}".rstrip("0").rstrip(".")


def _unit_cost(value) -> str:
    from decimal import Decimal

    amount = Decimal(str(value or 0))
    if amount == 0:
        return "$0.00"
    if abs(amount) < 1:
        return f"${amount:.3f}"
    return f"${amount:,.2f}"


templates.env.filters["unitcost"] = _unit_cost


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        ensure_connections(db)
        ensure_purchasing(db)
        ensure_catalog_suppliers(db)
        backfill_purchase_prices(db)
        match_sellables(db)
        ensure_paperless_sync_workflow(db)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Restaurant back office", version="0.1.0", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(connect_router)
    app.include_router(web_router)
    app.include_router(api_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.exception_handler(404)
    async def not_found(request: Request, exc):  # noqa: ARG001
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return RedirectResponse("/")

    return app


app = create_app()
