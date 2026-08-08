"""FastAPI application entry point for Nimble Lab Manager.

Launch with:  uvicorn app.server:app
Serves the buildless SPA in web/ at / and the JSON API under /api.
"""

import contextlib
import os
import sqlite3

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, scheduler
from .api import auth_router, router
from .db import ROOT_DIR, init_db


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()  # opt-in daily alert digest (NLM_SCHEDULER); no-op otherwise
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(title="Nimble Lab Manager", lifespan=lifespan)

# List endpoints return JSON that is highly repetitive and compresses ~10x. At a
# real lab's scale /api/items alone was measured at 5.8MB uncompressed, which
# dominated both response time and server memory; gzip removes that without any
# change to the API or the client.
app.add_middleware(GZipMiddleware, minimum_size=1024)

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


# A transient SQLite lock (writer contention that outlived busy_timeout) is not a
# server bug -- answer 503 so the client can retry, instead of a scary 500. Other
# OperationalErrors (a genuine schema/programming fault) still surface as 500.
@app.exception_handler(sqlite3.OperationalError)
async def _operational_handler(request: Request, exc: sqlite3.OperationalError):
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        return JSONResponse(
            status_code=503,
            content={"detail": "database is busy, please retry"},
            headers={"Retry-After": "1"},
        )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


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


# Cap JSON bodies. The multipart upload routes police their own (larger) limits;
# everything else on /api is small structured data, so a body in the megabytes is
# either a mistake or an attempt to grow the database without bound.
_MAX_JSON_BODY = 1 * 1024 * 1024


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path

    if request.method in _CSRF_METHODS and path.startswith("/api/"):
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" not in content_type:
            try:
                length = int(request.headers.get("content-length") or 0)
            except ValueError:
                length = 0
            if length > _MAX_JSON_BODY:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "request body is too large"},
                )
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
    # camera=(self) enables in-app barcode/QR scanning (stocktake and the global
    # scan action); geolocation and microphone stay off. The browser still asks
    # the user for camera permission -- this header only stops it being blocked
    # outright.
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(self)"
    )
    if path not in _CSP_EXEMPT:
        response.headers["Content-Security-Policy"] = _CSP
    return response


# Serve the SPA. web/ is owned by the frontend agents; ensure it exists so the
# mount does not fail on a fresh checkout, then serve index.html at /.
WEB_DIR = os.path.join(ROOT_DIR, "web")
UPLOADS_DIR = os.path.join(WEB_DIR, "uploads")
os.makedirs(WEB_DIR, exist_ok=True)


# Uploaded files (SDS documents, floor images, product photos) live under web/,
# so the static mount below would hand them to anyone who knows the URL --
# access control by secrecy. This explicit route is declared BEFORE the mount, so
# it wins, and it requires a session. Traversal is blocked by resolving the path
# and requiring it to stay inside the uploads directory.
@app.get("/uploads/{path:path}")
def serve_upload(path: str, user: dict = Depends(auth.current_user)):
    root = os.path.realpath(UPLOADS_DIR)
    target = os.path.realpath(os.path.join(root, path))
    if target != root and not target.startswith(root + os.sep):
        raise HTTPException(status_code=404, detail="not found")
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(target)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
