from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import files as fileman
from app import fleet, library, system
from app.settings import settings

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def create_app() -> FastAPI:
    app = FastAPI(title="Orbit", version="1.0.0")
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.get("/health")
    def health():
        return {"status": "ok", "name": "orbit"}

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "host": settings.host_name,
                "system": system.snapshot(),
                "fleet": fleet.snapshot(),
                "library": library.snapshot(),
                "roots": fileman.roots(),
            },
        )

    @app.get("/api/system")
    def api_system():
        return system.snapshot()

    @app.get("/api/fleet")
    def api_fleet():
        return fleet.snapshot()

    @app.get("/api/library")
    def api_library():
        return library.snapshot()

    @app.get("/api/files/roots")
    def api_roots():
        return {"roots": fileman.roots()}

    @app.get("/api/files")
    def api_files(root: str = Query(...), path: str = ""):
        return fileman.listing(root, path)

    @app.get("/api/files/download")
    def api_download(root: str = Query(...), path: str = Query(...)):
        return fileman.download(root, path)

    @app.post("/api/files/mkdir")
    def api_mkdir(root: str = Form(...), path: str = Form(""), name: str = Form(...)):
        return fileman.mkdir(root, path, name)

    @app.post("/api/files/upload")
    async def api_upload(
        root: str = Form(...),
        path: str = Form(""),
        file: UploadFile = File(...),
    ):
        return await fileman.upload(root, path, file)

    @app.post("/api/files/delete")
    def api_delete(root: str = Form(...), path: str = Form(...)):
        return fileman.remove(root, path)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):  # noqa: ARG001
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return RedirectResponse("/", status_code=303)

    return app


app = create_app()
