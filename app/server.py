"""FastAPI application entry point for Nimble Lab Manager.

Launch with:  uvicorn app.server:app
Serves the buildless SPA in web/ at / and the JSON API under /api.
"""

import contextlib
import os
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
from .api import auth_router, router
from .db import ROOT_DIR, init_db


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Nimble Lab Manager", lifespan=lifespan)

# API routes first so /api/* is never shadowed by the static mount at /.
# auth_router carries login/logout/me (no session required); everything on
# router requires an authenticated user.
app.include_router(auth_router)
app.include_router(router)


# A number larger than SQLite's signed-64-bit range reaches the driver and raises
# OverflowError ("Python int too large to convert to SQLite INTEGER"). That is
# out-of-range input, not a server fault, so answer 400 instead of a 500. (Found
# by the Schemathesis property/fuzz suite.)
@app.exception_handler(OverflowError)
async def _overflow_handler(request: Request, exc: OverflowError):
    return JSONResponse(
        status_code=400, content={"detail": "numeric value out of range"}
    )


# A SQLite IntegrityError (e.g. a body that references a nonexistent foreign key
# like staff_id=0) is bad client input, not a server fault -- answer 400, not a
# 500. (Surfaced by the Schemathesis property/fuzz suite.)
@app.exception_handler(sqlite3.IntegrityError)
async def _integrity_handler(request: Request, exc: sqlite3.IntegrityError):
    return JSONResponse(
        status_code=400, content={"detail": "request violates a data constraint"}
    )


# --------------------------------------------------------------------------- #
# security middleware: CSRF double-submit + response security headers
# --------------------------------------------------------------------------- #
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'self'; frame-ancestors 'none'"
)
# Swagger UI/ReDoc need inline scripts + a CDN; exempt them from the strict CSP.
_CSP_EXEMPT = {"/docs", "/redoc", "/openapi.json"}
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    # CSRF double-submit enforcement: only when auth is on AND a session cookie
    # is present (anonymous requests fall through to the route's own 401).
    if (
        request.method in _CSRF_METHODS
        and path.startswith("/api/")
        and path != "/api/login"
        and auth.auth_enabled()
        and request.cookies.get(auth.COOKIE_NAME)
    ):
        header = request.headers.get("X-CSRF-Token")
        cookie = request.cookies.get(auth.CSRF_COOKIE_NAME)
        if not header or not cookie or header != cookie:
            return JSONResponse(
                status_code=403, content={"detail": "CSRF token missing or invalid"}
            )

    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=()"
    )
    if path not in _CSP_EXEMPT:
        response.headers["Content-Security-Policy"] = _CSP
    return response


# Serve the SPA. web/ is owned by the frontend agents; ensure it exists so the
# mount does not fail on a fresh checkout, then serve index.html at /.
WEB_DIR = os.path.join(ROOT_DIR, "web")
os.makedirs(WEB_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
