"""ATLAS API - FastAPI application.

Run:  uvicorn apps.api.main:app --port 8000
Docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from apps.api.routes import content, intelligence, operations
from apps.api.schemas import Health
from apps.api.services import Conflict
from packages.config import get_settings
from packages.persistence.db import ping, session_scope
from packages.persistence.repositories import get_default_project
from packages.telemetry.logging import configure_logging, get_logger
from workers.publishing.activities import PREVIEW_DIR
from workflows import engine

VERSION = "0.1.0"
log = get_logger("atlas.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        with session_scope() as s:
            get_default_project(s)  # seeds the demo tenant/project on first boot
    except Exception:  # noqa: BLE001 - surface via /health instead of crashing
        log.exception("startup seed failed")
    yield


app = FastAPI(
    title="ATLAS API",
    description="Autonomous Search Intelligence & Content Operations. Demo signals are SIMULATED and labelled as such.",
    version=VERSION,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_list, allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"],
)


@app.exception_handler(LookupError)
async def not_found(_: Request, exc: LookupError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(exc).strip("'")})


@app.exception_handler(Conflict)
async def conflict(_: Request, exc: Conflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "conflict", "detail": str(exc)})


@app.exception_handler(ValueError)
async def bad_value(_: Request, exc: ValueError) -> JSONResponse:
    if isinstance(exc, ValidationError):
        return JSONResponse(status_code=422, content={"error": "validation_error", "detail": exc.errors()})
    return JSONResponse(status_code=422, content={"error": "invalid_request", "detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": type(exc).__name__})


@app.get("/health", response_model=Health, tags=["system"])
async def health() -> Health:
    s = get_settings()
    try:
        db_ok = ping()
    except Exception:  # noqa: BLE001
        db_ok = False
    ok, why = await engine.temporal_worker_available()
    orchestrator = "temporal" if (ok and s.orchestrator != "inline") else "inline"
    return Health(status="ok" if db_ok else "degraded", database=db_ok, temporal=("ready: " if ok else "") + why,
                  orchestrator=orchestrator, provider_mode=s.provider_mode, llm_provider=s.llm_provider, version=VERSION)


app.include_router(intelligence.router)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/site", StaticFiles(directory=PREVIEW_DIR, html=True), name="site-preview")  # static build preview
app.include_router(content.router)
app.include_router(operations.router)
