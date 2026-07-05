from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from office.api.events import event_stream
from office.api.routes import goals, meetings, office, workstations
from office.api.routes import directives as directives_routes
from office.api.routes import events as events_routes
from office.config import get_office_settings
from office.storage import init_db

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="AI Office", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(office.router)
app.include_router(goals.router)
app.include_router(workstations.router)
app.include_router(meetings.router)
app.include_router(events_routes.router)
app.include_router(directives_routes.router)


@app.get("/api/events")
async def sse_events():
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "office"}


@app.get("/")
async def root_redirect():
    return RedirectResponse("/office", status_code=302)


if UI_DIST.is_dir():
    assets_dir = UI_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/office/assets", StaticFiles(directory=str(assets_dir)), name="office-assets")

    @app.get("/office")
    @app.get("/office/{path:path}")
    async def office_spa(path: str = ""):
        index = UI_DIST / "index.html"
        if path and (UI_DIST / path).is_file():
            return FileResponse(UI_DIST / path)
        return FileResponse(index)
