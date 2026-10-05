"""The card, and the one request that fills it."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from walkcue import __version__
from walkcue.config import Settings
from walkcue.phrasing import AreaNotFound, InvalidArea, UpstreamError
from walkcue.service import WalkService

WEB_DIR = Path(__file__).resolve().parent / "web"


class CueIn(BaseModel):
    area: str = Field(min_length=1, max_length=80)
    local_time: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    client_kwargs: dict[str, object] = {
        "headers": {
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
            "Accept-Language": "en",
        },
        "timeout": httpx.Timeout(20.0, connect=5.0),
        "follow_redirects": False,
    }
    transport = getattr(app.state, "transport", None)
    if transport is not None:
        client_kwargs["transport"] = transport
    async with httpx.AsyncClient(**client_kwargs) as client:
        app.state.service = WalkService(client, settings)
        yield


def create_app(
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    app = FastAPI(title="Walk Cue", version=__version__, lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()
    app.state.transport = transport

    @app.get("/api/health")
    def health(request: Request) -> dict[str, object]:
        current: Settings = request.app.state.settings
        return {"ok": True, "llm_mode": current.llm_mode}

    @app.post("/api/cue")
    async def create_cue(body: CueIn, request: Request) -> dict[str, object]:
        return await _compose(request, body.area, body.local_time)

    @app.get("/api/cue")
    async def read_cue(area: str, request: Request, local_time: str | None = None) -> dict[str, object]:
        return await _compose(request, area, local_time)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


async def _compose(request: Request, area: str, local_time: str | None = None) -> dict[str, object]:
    try:
        return await request.app.state.service.compose(area, local_time)
    except InvalidArea as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AreaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UpstreamError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


app = create_app()
