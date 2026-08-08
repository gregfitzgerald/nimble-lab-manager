"""All /api/* routes for Nimble Lab Manager.

Every query is parameterized. The location hierarchy is walked with recursive
CTEs. Endpoints are written to survive an empty / edge-case dataset.

Auth: every route on `router` requires a live session (see app.auth); the
login/logout/me endpoints live on the dependency-free `auth_router`.
Mutations additionally require member+, and reset requires manager+.
"""

import csv
import io
import json
import logging
import os
import re
import secrets as _secrets
import sqlite3
from typing import List, Optional

import segno
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

from . import auth, notify, sqlconsole
from . import db as _db
from .db import ROOT_DIR, get_conn, rebuild_db

log = logging.getLogger("nlm.api")

router = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])
auth_router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _today(conn):
    """Return SQLite's notion of today as an ISO date string."""
    return conn.execute("SELECT date('now') AS d").fetchone()["d"]


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def _expiry_flag(nearest_expiry, today):
    """Map a nearest-expiry date to ok | expiring | expired | none."""
    if not nearest_expiry:
        return "none"
    if nearest_expiry < today:
        return "expired"
    # expiring if within 30 days
    days = _days_between(today, nearest_expiry)
    if days is not None and days <= 30:
        return "expiring"
    return "ok"


def _days_between(today, target):
    """Whole days from today to target (positive = future). None on bad input."""
    try:
        from datetime import date

        y1, m1, d1 = (int(x) for x in today.split("-"))
        y2, m2, d2 = (int(x) for x in target.split("-"))
        return (date(y2, m2, d2) - date(y1, m1, d1)).days
    except Exception:
        return None


def _location_path(conn, node_id):
    """Return a ' / '-joined path from root down to node_id (names)."""
    if node_id is None:
        return None
    rows = conn.execute(
        """
        WITH RECURSIVE up(id, parent_id, name, depth) AS (
            SELECT id, parent_id, name, 0
            FROM location_node WHERE id = ?
            UNION ALL
            SELECT p.id, p.parent_id, p.name, up.depth + 1
            FROM location_node p
            JOIN up ON p.id = up.parent_id
        )
        SELECT name FROM up ORDER BY depth DESC
        """,
        (node_id,),
    ).fetchall()
    if not rows:
        return None
    return " / ".join(r["name"] for r in rows)


def _box_name(conn, box_id):
    if box_id is None:
        return None
    row = conn.execute(
        "SELECT name FROM location_node WHERE id = ?", (box_id,)
    ).fetchone()
    return row["name"] if row else None


def _audit(conn, user, action, entity_type=None, entity_id=None, detail=None):
    """Append one row to the append-only audit trail (powers the History view).

    `user` is the current_user dict (id/username/...), or None. The username is
    denormalized into the row so it stays readable after the user changes. This
    never raises: an audit-write failure must not break the operation it records.
    The caller owns the transaction -- this only stages the INSERT.
    """
    try:
        uid = user.get("id") if user else None
        uname = user.get("username") if user else None
        conn.execute(
            """INSERT INTO audit_log
                   (occurred_at, user_id, username, action,
                    entity_type, entity_id, detail)
               VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)""",
            (uid, uname, action, entity_type, entity_id, detail),
        )
    except Exception:
        # Never break the operation being recorded -- but never fail silently
        # either: a schema drift that quietly stopped writing history is exactly
        # the failure an audit trail must not hide.
        log.exception(
            "AUDIT WRITE FAILED for action=%r entity=%s/%s; the audit trail is "
            "now incomplete", action, entity_type, entity_id,
        )


def _open_lot(conn, item_id, quantity, expiry=None, label="opening balance"):
    """Create the lot that accounts for an item's opening stock.

    Stock used to be able to exist with no lot behind it (item creation and CSV
    import both set quantity_on_hand directly), which left two numbers that
    could not be reconciled -- and, because expiry alerts read item_lot, meant
    imported stock was invisible to expiry tracking. Every opening balance now
    gets a lot, so SUM(item_lot.quantity) always accounts for what is on hand.

    The expiry is unknown at import time unless the sheet supplies one; the lot
    is created without it and can be filled in later (PATCH /api/lots/{id}),
    which is what makes imported stock trackable at all.
    """
    if not quantity or quantity <= 0:
        return None
    cur = conn.execute(
        """INSERT INTO item_lot
               (item_id, lot_number, expiry_date, quantity, received_date)
           VALUES (?, ?, ?, ?, date('now'))""",
        (item_id, label, expiry, quantity),
    )
    return cur.lastrowid


def _current_uid(conn, user):
    """Resolve current_user -> a real app_user.id, or None.

    With auth off current_user is a synthetic admin (id 0) that isn't a row in
    app_user; fall back to matching the manager demo user so soft-referenced
    writes (tickets, POs, controlled log) still attribute to someone real.
    """
    if not user:
        return None
    uid = user.get("id")
    row = conn.execute("SELECT id FROM app_user WHERE id = ?", (uid,)).fetchone()
    if row is not None:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM app_user WHERE username = ? ORDER BY id LIMIT 1",
        (user.get("username"),),
    ).fetchone()
    return row["id"] if row else None


# --------------------------------------------------------------------------- #
# document attachments (shared helpers)
# --------------------------------------------------------------------------- #
_DOC_KINDS = {"sds", "coa", "invoice", "po", "packing_slip", "other"}
_DOC_UPLOAD_DIR = os.path.join(ROOT_DIR, "web", "uploads", "docs")
_DOC_EXTS = {"pdf", "png", "jpg", "jpeg", "txt", "csv", "docx", "xlsx"}
_DOC_MAX_BYTES = 20 * 1024 * 1024  # ~20MB cap
_DOC_COLS = (
    "id", "item_id", "lot_id", "po_id", "kind", "label", "url",
    "filename", "uploaded_at", "uploaded_by",
)


def _doc_href(row):
    """Public link for a document row: an external url, else the uploaded file."""
    if row.get("url"):
        return row["url"]
    if row.get("filename"):
        return f"/uploads/docs/{row['filename']}"
    return None


def _documents_for(conn, target_col, target_id):
    """Return item_document rows for one target (item_id|lot_id|po_id), + href."""
    rows = _rows(conn.execute(
        f"SELECT {', '.join(_DOC_COLS)} FROM item_document "
        f"WHERE {target_col} = ? ORDER BY uploaded_at DESC, id DESC",
        (target_id,),
    ))
    for r in rows:
        r["href"] = _doc_href(r)
    return rows


def _unlink_doc_file(filename):
    """Best-effort removal of an uploaded document (basename-guarded)."""
    if not filename or os.path.basename(filename) != filename:
        return
    try:
        os.unlink(os.path.join(_DOC_UPLOAD_DIR, filename))
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# auth (on auth_router: reachable without a session)
# --------------------------------------------------------------------------- #
class LoginBody(BaseModel):
    # Bounded so an unauthenticated caller cannot post a huge string that is then
    # hashed (PBKDF2 at 210k iterations is deliberately expensive).
    username: str = Field(max_length=150)
    password: str = Field(max_length=256)


# In-process login throttle. Keyed by BOTH the username and the client IP:
# username alone let an attacker lock a known account out at will, and let them
# spray many usernames with no limit at all -- while each miss still burned a
# full PBKDF2 hash, making the endpoint a CPU amplifier. Sliding window;
# >= _LOGIN_MAX_FAILURES within _LOGIN_WINDOW_SEC -> 429.
_login_failures = {}
_LOGIN_MAX_FAILURES = 8
_LOGIN_WINDOW_SEC = 600
_LOGIN_IP_MAX_FAILURES = 30      # across all usernames from one address
_LOGIN_TRACK_LIMIT = 8192        # bound the dict so it cannot grow without limit


def _login_prune(now):
    """Drop entries whose whole window has expired (keeps the map bounded)."""
    stale = [
        k for k, times in _login_failures.items()
        if not times or now - times[-1] >= _LOGIN_WINDOW_SEC
    ]
    for k in stale:
        _login_failures.pop(k, None)
    if len(_login_failures) > _LOGIN_TRACK_LIMIT:
        # Pathological case: keep the most recent offenders, discard the rest.
        for k in sorted(_login_failures, key=lambda k: _login_failures[k][-1])[
            : len(_login_failures) - _LOGIN_TRACK_LIMIT
        ]:
            _login_failures.pop(k, None)


def _login_recent(key, now):
    return [t for t in _login_failures.get(key, []) if now - t < _LOGIN_WINDOW_SEC]


_MIN_PASSWORD_LEN = 8


def _require_password(password):
    """Reject empty or too-short passwords; return the accepted value."""
    password = password or ""
    if len(password) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"password must be at least {_MIN_PASSWORD_LEN} characters",
        )
    return password


def _cookie_secure(request: Request = None):
    """Set the Secure flag when configured OR when the request arrived over
    HTTPS, so the deployed (force_https) instance never emits a non-Secure
    session cookie even if NLM_SECURE_COOKIES was left unset."""
    if auth.secure_cookies():
        return True
    return request is not None and request.url.scheme == "https"


def _issue_csrf_cookie(response: Response, request: Request = None):
    """Set a fresh JS-readable double-submit CSRF cookie; return its value."""
    token = _secrets.token_urlsafe(32)
    response.set_cookie(
        auth.CSRF_COOKIE_NAME,
        token,
        max_age=auth.SESSION_DAYS * 24 * 3600,
        path="/",
        httponly=False,
        samesite="lax",
        secure=_cookie_secure(request),
    )
    return token


@auth_router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    import time

    key = body.username.strip().lower()
    ip = (request.client.host if request.client else None) or "unknown"
    ip_key = ("ip", ip)
    now = time.time()
    _login_prune(now)

    recent = _login_recent(key, now)
    ip_recent = _login_recent(ip_key, now)
    # Refuse BEFORE hashing: the point is to stop the request burning a PBKDF2
    # round, not merely to reject it afterwards.
    if len(recent) >= _LOGIN_MAX_FAILURES or len(ip_recent) >= _LOGIN_IP_MAX_FAILURES:
        _login_failures[key] = recent
        _login_failures[ip_key] = ip_recent
        raise HTTPException(
            status_code=429, detail="too many failed attempts; try again later"
        )

    conn = get_conn()
    try:
        result = auth.login_user(conn, body.username, body.password)
    finally:
        conn.close()
    if result is None:
        recent.append(now)
        _login_failures[key] = recent
        # Count the miss against the source address too, so spraying many
        # usernames from one host is limited even though each name is fresh.
        ip_recent.append(now)
        _login_failures[ip_key] = ip_recent
        raise HTTPException(status_code=401, detail="invalid credentials")
    _login_failures.pop(key, None)
    _login_failures.pop(ip_key, None)
    token, user = result
    conn = get_conn()
    try:
        _audit(conn, user, "login", "app_user", user.get("id"), user.get("username"))
        conn.commit()
    finally:
        conn.close()
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=auth.SESSION_DAYS * 24 * 3600,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
    )
    _issue_csrf_cookie(response, request)
    return {"user": user}


@auth_router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        conn = get_conn()
        try:
            auth.delete_session(conn, token)
        finally:
            conn.close()
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@auth_router.get("/me")
def me(request: Request, response: Response, user: dict = Depends(auth.current_user)):
    # Ensure the SPA has a CSRF token even if it only ever calls /api/me.
    if not request.cookies.get(auth.CSRF_COOKIE_NAME):
        _issue_csrf_cookie(response, request)
    return {"user": user}


@auth_router.get("/public-config")
def public_config():
    """Unauthenticated bootstrap the login screen can read before sign-in.

    demo_mode is true only when the well-known demo logins are seeded, so the
    login page advertises them exactly when they exist -- a deployed (empty)
    instance shows a plain sign-in form with no admin/admin hint.
    """
    return {"demo_mode": auth.demo_enabled()}


# --------------------------------------------------------------------------- #
# dashboard
# --------------------------------------------------------------------------- #
@router.get("/dashboard")
def dashboard():
    conn = get_conn()
    try:
        today = _today(conn)
        counts = {}
        counts["items"] = conn.execute(
            "SELECT COUNT(*) c FROM inventory WHERE status = 'active'"
        ).fetchone()["c"]
        counts["locations"] = conn.execute(
            "SELECT COUNT(*) c FROM location_node"
        ).fetchone()["c"]
        counts["containers"] = conn.execute(
            "SELECT COUNT(*) c FROM container WHERE status = 'in_use'"
        ).fetchone()["c"]
        counts["expiring_soon"] = conn.execute(
            """SELECT COUNT(*) c FROM item_lot
               WHERE expiry_date IS NOT NULL
                 AND expiry_date >= ?
                 AND expiry_date <= date(?, '+30 day')""",
            (today, today),
        ).fetchone()["c"]
        counts["expired"] = conn.execute(
            """SELECT COUNT(*) c FROM item_lot
               WHERE expiry_date IS NOT NULL AND expiry_date < ?""",
            (today,),
        ).fetchone()["c"]
        counts["low_stock"] = conn.execute(
            "SELECT COUNT(*) c FROM inventory WHERE quantity_on_hand <= reorder_threshold"
        ).fetchone()["c"]
        counts["misplaced"] = conn.execute(
            """SELECT COUNT(*) c FROM container
               WHERE status = 'in_use' AND expected_box_id IS NOT NULL
                 AND (box_id <> expected_box_id
                      OR row <> expected_row
                      OR col <> expected_col)"""
        ).fetchone()["c"]
        counts["compat_conflicts"] = len(_compat_conflicts(conn))
        counts["pos_pending"] = conn.execute(
            "SELECT COUNT(*) c FROM purchase_order WHERE status = 'pending_approval'"
        ).fetchone()["c"]
        counts["equipment_due"] = conn.execute(
            """SELECT COUNT(*) c FROM equipment
               WHERE next_service_date IS NOT NULL
                 AND next_service_date <= date(?, '+14 day')""",
            (today,),
        ).fetchone()["c"]
        counts["open_counts"] = conn.execute(
            "SELECT COUNT(*) c FROM count_session WHERE status = 'open'"
        ).fetchone()["c"]
        counts["funds_attention"] = conn.execute(
            """SELECT COUNT(*) c FROM fund f
               WHERE f.budget > 0
                 AND (SELECT COALESCE(SUM(amount), 0) FROM fund_charge
                      WHERE fund_id = f.id) * 1.0 / f.budget > 0.9"""
        ).fetchone()["c"]
        counts["controlled"] = conn.execute(
            "SELECT COUNT(*) c FROM inventory WHERE is_controlled = 1"
        ).fetchone()["c"]
        counts["kits"] = conn.execute(
            "SELECT COUNT(*) c FROM kit"
        ).fetchone()["c"]

        recent = _rows(
            conn.execute(
                """SELECT e.event_type, i.item_name, e.quantity, e.occurred_at
                   FROM usage_event e
                   LEFT JOIN inventory i ON i.item_id = e.item_id
                   ORDER BY e.occurred_at DESC, e.id DESC
                   LIMIT 10"""
            )
        )
        return {"counts": counts, "recent_events": recent}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# locations
# --------------------------------------------------------------------------- #
_NODE_COLS = (
    "id, parent_id, kind, name, capacity_rows, capacity_cols, "
    "floor_id, map_x, map_y, map_w, map_h, allowed_hazards, temp_rating"
)


@router.get("/locations")
def locations():
    conn = get_conn()
    try:
        rows = _rows(
            conn.execute(f"SELECT {_NODE_COLS} FROM location_node ORDER BY id")
        )
        by_id = {r["id"]: {**r, "children": []} for r in rows}
        roots = []
        for r in rows:
            node = by_id[r["id"]]
            parent = by_id.get(r["parent_id"])
            if parent is not None:
                parent["children"].append(node)
            else:
                roots.append(node)
        return roots
    finally:
        conn.close()


@router.get("/locations/{node_id}")
def location_detail(node_id: int):
    conn = get_conn()
    try:
        node = conn.execute(
            f"SELECT {_NODE_COLS} FROM location_node WHERE id = ?", (node_id,)
        ).fetchone()
        if node is None:
            raise HTTPException(status_code=404, detail="location not found")
        node = dict(node)
        children = _rows(
            conn.execute(
                f"SELECT {_NODE_COLS} FROM location_node WHERE parent_id = ? ORDER BY id",
                (node_id,),
            )
        )
        containers = []
        if node["kind"] == "box":
            today = _today(conn)
            raw = _rows(
                conn.execute(
                    """SELECT c.id, c.row, c.col, c.status,
                              c.box_id, c.expected_box_id, c.expected_row, c.expected_col,
                              i.item_id, i.item_name,
                              l.lot_number, l.expiry_date
                       FROM container c
                       JOIN item_lot l ON l.id = c.item_lot_id
                       JOIN inventory i ON i.item_id = l.item_id
                       WHERE c.box_id = ?
                       ORDER BY c.row, c.col""",
                    (node_id,),
                )
            )
            for c in raw:
                c["misplaced"] = bool(
                    c["expected_box_id"] is not None
                    and (
                        c["box_id"] != c["expected_box_id"]
                        or c["row"] != c["expected_row"]
                        or c["col"] != c["expected_col"]
                    )
                )
                c["expiry_flag"] = _expiry_flag(c["expiry_date"], today)
                containers.append(c)
        return {"node": node, "children": children, "containers": containers}
    finally:
        conn.close()


# Columns of the floor table (schema.sql); also the layout-import whitelist.
_FLOOR_COLS = ("id", "name", "image_filename", "image_width", "image_height")

# Real floor-plan images live here, inside the StaticFiles-mounted web/ dir,
# so a stored image_filename serves at /uploads/floors/<image_filename>.
_FLOOR_UPLOAD_DIR = os.path.join(ROOT_DIR, "web", "uploads", "floors")
_FLOOR_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "svg"}
_FLOOR_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # ~10MB cap


def _floor_image_url(image_filename):
    return f"/uploads/floors/{image_filename}" if image_filename else None


def _get_floor(conn, floor_id):
    row = conn.execute(
        f"SELECT {', '.join(_FLOOR_COLS)} FROM floor WHERE id = ?", (floor_id,)
    ).fetchone()
    return dict(row) if row else None


def _floor_public(row):
    """Public shape of one floor row (no units)."""
    return {
        "floor_id": row["id"],
        "name": row["name"],
        "image_url": _floor_image_url(row["image_filename"]),
        "image_width": row["image_width"],
        "image_height": row["image_height"],
    }


def _unlink_floor_image(image_filename):
    """Best-effort removal of a stored floor image. Basename-guarded so a
    hostile stored filename can never step outside the uploads dir."""
    if not image_filename or os.path.basename(image_filename) != image_filename:
        return
    try:
        os.unlink(os.path.join(_FLOOR_UPLOAD_DIR, image_filename))
    except OSError:
        pass


@router.get("/floors")
def floors():
    conn = get_conn()
    try:
        units = _rows(
            conn.execute(
                f"""SELECT {_NODE_COLS} FROM location_node
                    WHERE map_x IS NOT NULL
                    ORDER BY floor_id, id"""
            )
        )
        floor_rows = _rows(
            conn.execute(f"SELECT {', '.join(_FLOOR_COLS)} FROM floor ORDER BY id")
        )
        known = {f["id"] for f in floor_rows}
        result = []
        for f in floor_rows:
            d = _floor_public(f)
            # width/height stay for existing map consumers: the image's natural
            # pixel size when a real plan is uploaded, else the 0..1000 canvas.
            d["width"] = f["image_width"] or 1000
            d["height"] = f["image_height"] or 1000
            d["units"] = [u for u in units if u["floor_id"] == f["id"]]
            result.append(d)
        # Floors referenced only by location_node.floor_id (soft reference, no
        # floor row) still render as abstract schematics.
        orphan_ids = sorted(
            {u["floor_id"] for u in units
             if u["floor_id"] is not None and u["floor_id"] not in known}
        )
        for fid in orphan_ids:
            result.append(
                {
                    "floor_id": fid,
                    "name": f"Floor {fid}",
                    "image_url": None,
                    "image_width": None,
                    "image_height": None,
                    "width": 1000,
                    "height": 1000,
                    "units": [u for u in units if u["floor_id"] == fid],
                }
            )
        return result
    finally:
        conn.close()


class FloorCreateBody(BaseModel):
    name: str


@router.post("/floors", dependencies=[Depends(auth.require_role("manager"))])
def create_floor(body: FloorCreateBody):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO floor (name) VALUES (?)", (name,))
        conn.commit()
        return _floor_public(_get_floor(conn, cur.lastrowid))
    finally:
        conn.close()


@router.post(
    "/floors/{floor_id}/image",
    dependencies=[Depends(auth.require_role("manager"))],
)
async def upload_floor_image(
    floor_id: int,
    file: UploadFile = File(...),
    width: int = Form(...),
    height: int = Form(...),
):
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="width/height must be positive")
    if not (file.content_type or "").lower().startswith("image/"):
        raise HTTPException(status_code=400, detail="file must be an image")

    # Derive a safe name: basename only (kills traversal), extension whitelist,
    # stem reduced to [A-Za-z0-9._-], unique floor_<id>_<token>_<stem>.<ext>.
    original = os.path.basename(file.filename or "")
    stem, dot, ext = original.rpartition(".")
    ext = ext.lower()
    if not dot or ext not in _FLOOR_IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"extension must be one of: {', '.join(sorted(_FLOOR_IMAGE_EXTS))}",
        )
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:60] or "plan"
    filename = f"floor_{floor_id}_{_secrets.token_hex(4)}_{safe_stem}.{ext}"

    data = await file.read(_FLOOR_IMAGE_MAX_BYTES + 1)
    if len(data) > _FLOOR_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="image exceeds 10MB limit")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    conn = get_conn()
    try:
        floor = _get_floor(conn, floor_id)
        if floor is None:
            raise HTTPException(status_code=404, detail="floor not found")

        os.makedirs(_FLOOR_UPLOAD_DIR, exist_ok=True)
        dest = os.path.join(_FLOOR_UPLOAD_DIR, filename)
        # Belt and braces: the joined path must resolve inside the uploads dir.
        if os.path.dirname(os.path.abspath(dest)) != os.path.abspath(_FLOOR_UPLOAD_DIR):
            raise HTTPException(status_code=400, detail="invalid filename")
        with open(dest, "wb") as fh:
            fh.write(data)

        conn.execute(
            """UPDATE floor SET image_filename = ?, image_width = ?, image_height = ?
               WHERE id = ?""",
            (filename, width, height, floor_id),
        )
        conn.commit()
        _unlink_floor_image(floor["image_filename"])  # replaced image, if any
        return _floor_public(_get_floor(conn, floor_id))
    finally:
        conn.close()


@router.delete(
    "/floors/{floor_id}/image",
    dependencies=[Depends(auth.require_role("manager"))],
)
def delete_floor_image(floor_id: int):
    conn = get_conn()
    try:
        floor = _get_floor(conn, floor_id)
        if floor is None:
            raise HTTPException(status_code=404, detail="floor not found")
        conn.execute(
            """UPDATE floor SET image_filename = NULL, image_width = NULL,
                   image_height = NULL WHERE id = ?""",
            (floor_id,),
        )
        conn.commit()
        _unlink_floor_image(floor["image_filename"])
        return {"ok": True}
    finally:
        conn.close()


# Known location kinds (mirrors the comment in schema.sql).
_LOCATION_KINDS = {
    "room", "bench", "cabinet", "fridge", "freezer",
    "shelf", "rack", "box", "cage",
    "building", "zone", "drawer", "tower", "incubator", "tank",
}

# Columns the layout editor may write. PATCH bodies are filtered against this
# whitelist so client-supplied field names are never interpolated into SQL.
_EDITABLE_COLS = (
    "name", "parent_id", "kind", "capacity_rows", "capacity_cols",
    "floor_id", "map_x", "map_y", "map_w", "map_h",
    "allowed_hazards", "temp_rating",
)


def _get_node(conn, node_id):
    """Fetch one location_node as a dict (same shape as _NODE_COLS), or None."""
    row = conn.execute(
        f"SELECT {_NODE_COLS} FROM location_node WHERE id = ?", (node_id,)
    ).fetchone()
    return dict(row) if row else None


class LocationCreateBody(BaseModel):
    parent_id: Optional[int] = None
    kind: str
    name: str
    capacity_rows: Optional[int] = None
    capacity_cols: Optional[int] = None
    floor_id: Optional[int] = None
    map_x: Optional[float] = None
    map_y: Optional[float] = None
    map_w: Optional[float] = None
    map_h: Optional[float] = None
    allowed_hazards: Optional[str] = None
    temp_rating: Optional[str] = None


@router.post("/locations", dependencies=[Depends(auth.require_role("manager"))])
def create_location(body: LocationCreateBody):
    if body.kind not in _LOCATION_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown kind: {body.kind}")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    # Grid capacity only applies to boxes.
    cap_rows = body.capacity_rows if body.kind == "box" else None
    cap_cols = body.capacity_cols if body.kind == "box" else None
    conn = get_conn()
    try:
        if body.parent_id is not None and _get_node(conn, body.parent_id) is None:
            raise HTTPException(status_code=400, detail="parent location not found")
        cur = conn.execute(
            """INSERT INTO location_node
                   (parent_id, kind, name, capacity_rows, capacity_cols,
                    floor_id, map_x, map_y, map_w, map_h,
                    allowed_hazards, temp_rating)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.parent_id, body.kind, name, cap_rows, cap_cols,
             body.floor_id, body.map_x, body.map_y, body.map_w, body.map_h,
             body.allowed_hazards, body.temp_rating),
        )
        conn.commit()
        return _get_node(conn, cur.lastrowid)
    finally:
        conn.close()


@router.patch(
    "/locations/{node_id}",
    dependencies=[Depends(auth.require_role("manager"))],
)
def update_location(node_id: int, payload: dict = Body(...)):
    # Whitelist filter: only known columns survive, in _EDITABLE_COLS order.
    fields = {k: payload[k] for k in _EDITABLE_COLS if k in payload}
    if not fields:
        raise HTTPException(status_code=400, detail="no updatable fields provided")
    if "kind" in fields and fields["kind"] not in _LOCATION_KINDS:
        raise HTTPException(
            status_code=400, detail=f"unknown kind: {fields['kind']}"
        )
    if "name" in fields:
        fields["name"] = str(fields["name"] or "").strip()
        if not fields["name"]:
            raise HTTPException(status_code=400, detail="name cannot be empty")
    conn = get_conn()
    try:
        if _get_node(conn, node_id) is None:
            raise HTTPException(status_code=404, detail="location not found")
        if fields.get("parent_id") is not None:
            if fields["parent_id"] == node_id:
                raise HTTPException(
                    status_code=400, detail="location cannot be its own parent"
                )
            if _get_node(conn, fields["parent_id"]) is None:
                raise HTTPException(
                    status_code=400, detail="parent location not found"
                )
        set_sql = ", ".join(f"{col} = ?" for col in fields)  # whitelisted names
        conn.execute(
            f"UPDATE location_node SET {set_sql} WHERE id = ?",
            (*fields.values(), node_id),
        )
        conn.commit()
        return _get_node(conn, node_id)
    finally:
        conn.close()


@router.delete(
    "/locations/{node_id}",
    dependencies=[Depends(auth.require_role("manager"))],
)
def delete_location(node_id: int):
    conn = get_conn()
    try:
        if _get_node(conn, node_id) is None:
            raise HTTPException(status_code=404, detail="location not found")
        children = conn.execute(
            "SELECT COUNT(*) AS c FROM location_node WHERE parent_id = ?",
            (node_id,),
        ).fetchone()["c"]
        if children:
            raise HTTPException(
                status_code=400,
                detail="location has child locations; move or delete them first",
            )
        # box_id per spec; expected_box_id too, since that FK would also break.
        containers = conn.execute(
            "SELECT COUNT(*) AS c FROM container WHERE box_id = ? OR expected_box_id = ?",
            (node_id, node_id),
        ).fetchone()["c"]
        if containers:
            raise HTTPException(
                status_code=400,
                detail="location holds containers; move or discard them first",
            )
        conn.execute("DELETE FROM location_node WHERE id = ?", (node_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# layout import/export (portable floor + location_node snapshot)
# --------------------------------------------------------------------------- #
# Import whitelist for location_node: primary key + every editable column.
_NODE_IMPORT_COLS = ("id",) + _EDITABLE_COLS


@router.get("/layout")
def layout_export():
    conn = get_conn()
    try:
        return {
            "floors": _rows(
                conn.execute(
                    f"SELECT {', '.join(_FLOOR_COLS)} FROM floor ORDER BY id"
                )
            ),
            "locations": _rows(
                conn.execute(f"SELECT {_NODE_COLS} FROM location_node ORDER BY id")
            ),
        }
    finally:
        conn.close()


class LayoutBody(BaseModel):
    floors: Optional[list] = None
    locations: list


def _require_dicts(rows, label):
    for row in rows:
        if not isinstance(row, dict):
            raise HTTPException(status_code=400, detail=f"{label} entries must be objects")


def _opt_int(row, key, label):
    """Validate an optional integer field on an import row."""
    v = row.get(key)
    if v is not None and (not isinstance(v, int) or isinstance(v, bool)):
        raise HTTPException(status_code=400, detail=f"{label}.{key} must be an integer")
    return v


@router.post("/layout", dependencies=[Depends(auth.require_role("manager"))])
def layout_import(body: LayoutBody):
    floors = body.floors or []
    locations = body.locations or []
    _require_dicts(floors, "floors")
    _require_dicts(locations, "locations")

    # ---- validate floors --------------------------------------------------
    for f in floors:
        _opt_int(f, "id", "floor")
        name = str(f.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="floor name is required")
        f["name"] = name
        fname = f.get("image_filename")
        if fname is not None and (
            not isinstance(fname, str)
            or os.path.basename(fname) != fname
            or ".." in fname
        ):
            raise HTTPException(
                status_code=400, detail="floor image_filename must be a bare filename"
            )

    # ---- validate locations -----------------------------------------------
    payload_ids = {
        loc["id"] for loc in locations if isinstance(loc.get("id"), int)
    }
    for loc in locations:
        _opt_int(loc, "id", "location")
        _opt_int(loc, "parent_id", "location")
        if loc.get("kind") not in _LOCATION_KINDS:
            raise HTTPException(
                status_code=400, detail=f"unknown kind: {loc.get('kind')}"
            )
        name = str(loc.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="location name is required")
        loc["name"] = name

    conn = get_conn()
    try:
        # Parents may reference ids elsewhere in the payload or already in the DB.
        for loc in locations:
            pid = loc.get("parent_id")
            if pid is not None and pid not in payload_ids:
                if conn.execute(
                    "SELECT 1 FROM location_node WHERE id = ?", (pid,)
                ).fetchone() is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"parent_id {pid} not in payload or database",
                    )

        # One transaction; FK checks deferred to COMMIT so payload order and
        # REPLACE-induced delete/insert pairs cannot trip the parent FK. The
        # explicit BEGIN matters: defer_foreign_keys resets at every commit,
        # so it must be set INSIDE the transaction, not in autocommit mode.
        conn.execute("BEGIN")
        conn.execute("PRAGMA defer_foreign_keys = ON")
        try:
            for f in floors:
                conn.execute(
                    f"""INSERT OR REPLACE INTO floor ({', '.join(_FLOOR_COLS)})
                        VALUES (?, ?, ?, ?, ?)""",
                    tuple(f.get(c) for c in _FLOOR_COLS),
                )
            for loc in locations:
                placeholders = ", ".join("?" for _ in _NODE_IMPORT_COLS)
                conn.execute(
                    f"""INSERT OR REPLACE INTO location_node
                            ({', '.join(_NODE_IMPORT_COLS)})
                        VALUES ({placeholders})""",
                    tuple(loc.get(c) for c in _NODE_IMPORT_COLS),
                )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=f"import failed: {exc}")
        return {
            "ok": True,
            "counts": {"floors": len(floors), "locations": len(locations)},
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# items
# --------------------------------------------------------------------------- #
# Allowed product categories (mirrors the comment on inventory.category in
# schema.sql; enforced here at the app layer, not by a CHECK constraint).
_ITEM_CATEGORIES = (
    "reagent", "supply", "chemical", "antibody", "enzyme",
    "media", "animal", "equipment", "office", "other",
)

# Columns PATCH /items/{id} may write; body keys are filtered against this
# whitelist so client-supplied field names are never interpolated into SQL.
_ITEM_EDITABLE_COLS = (
    "item_name", "vendor", "unit", "category", "sds_url",
    "reorder_threshold", "unit_cost", "status", "disposal_instructions",
    "is_controlled", "controlled_schedule",
    "reorder_max", "hazard_class", "cas_number", "catalog_id", "pack_size",
    "storage_temp", "light_sensitive",
)

_ITEM_STATUSES = ("active", "deprecated")

_PRODUCT_UPLOAD_DIR = os.path.join(ROOT_DIR, "web", "uploads", "products")
_PRODUCT_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
_PRODUCT_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # ~10MB cap


def _product_photo_url(photo_filename):
    return f"/uploads/products/{photo_filename}" if photo_filename else None


def _unlink_product_photo(photo_filename):
    """Best-effort removal of a stored product photo. Basename-guarded so a
    hostile stored filename can never step outside the uploads dir."""
    if not photo_filename or os.path.basename(photo_filename) != photo_filename:
        return
    try:
        os.unlink(os.path.join(_PRODUCT_UPLOAD_DIR, photo_filename))
    except OSError:
        pass


@router.get("/items")
def items(category: Optional[str] = None, include_deprecated: bool = False):
    conn = get_conn()
    try:
        today = _today(conn)
        clauses = []
        params = []
        if not include_deprecated:
            clauses.append("i.status = 'active'")
        if category:
            clauses.append("i.category = ?")
            params.append(category)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = _rows(
            conn.execute(
                f"""SELECT i.item_id, i.item_name, i.vendor, i.unit,
                          i.category, i.sds_url, i.status,
                          i.disposal_instructions, i.is_controlled,
                          i.controlled_schedule,
                          i.reorder_max, i.hazard_class, i.cas_number,
                          i.catalog_id, i.pack_size, i.photo_filename,
                          i.storage_temp, i.light_sensitive,
                          i.quantity_on_hand, i.reorder_threshold, i.unit_cost,
                          vc.catalog_number,
                          COALESCE(i.pack_size, vc.pack_size) AS size,
                          (SELECT coa_url FROM item_lot cl
                             WHERE cl.item_id = i.item_id AND cl.coa_url IS NOT NULL
                             ORDER BY (cl.expiry_date IS NULL), cl.expiry_date
                             LIMIT 1) AS coa_url,
                          COALESCE(SUM(l.quantity), 0) AS on_hand_lots,
                          MIN(CASE WHEN l.expiry_date IS NOT NULL AND l.quantity > 0
                                   THEN l.expiry_date END) AS nearest_expiry
                   FROM inventory i
                   LEFT JOIN item_lot l ON l.item_id = i.item_id
                   LEFT JOIN vendor_catalog vc ON vc.id = i.catalog_id
                   {where}
                   GROUP BY i.item_id
                   ORDER BY i.item_name""",
                tuple(params),
            )
        )
        # Primary storage location for every item in ONE pass. This used to be a
        # query per row (fine on the demo seed, quadratic for a real lab), plus a
        # recursive-CTE path lookup per row on top. Now: one grouped query, and
        # each distinct box's path resolved once.
        # In a min()/max() aggregate SQLite takes the bare columns from the
        # matching row, so box_id is the one belonging to MIN(c.id) -- i.e. the
        # same container the old "ORDER BY c.id LIMIT 1" picked.
        box_by_item = {
            row["item_id"]: row["box_id"]
            for row in conn.execute(
                """SELECT l2.item_id AS item_id, c.box_id AS box_id, MIN(c.id)
                     FROM container c
                     JOIN item_lot l2 ON l2.id = c.item_lot_id
                    WHERE c.status = 'in_use'
                    GROUP BY l2.item_id"""
            )
        }
        path_cache = {}

        def _cached_path(box_id):
            if box_id not in path_cache:
                path_cache[box_id] = _location_path(conn, box_id)
            return path_cache[box_id]

        for r in rows:
            r["is_low_stock"] = r["quantity_on_hand"] <= r["reorder_threshold"]
            r["expiry_flag"] = _expiry_flag(r["nearest_expiry"], today)
            r["photo_url"] = _product_photo_url(r.get("photo_filename"))
            box_id = box_by_item.get(r["item_id"])
            r["location"] = _cached_path(box_id) if box_id is not None else None
            # Unit-aware amount string, e.g. "6 x 500 mL" or "6 vial".
            qty = r["quantity_on_hand"]
            if r["size"]:
                r["amount"] = f"{qty} x {r['size']}"
            else:
                r["amount"] = f"{qty} {r['unit']}".strip() if r["unit"] else str(qty)
        return rows
    finally:
        conn.close()


@router.get("/items/{item_id}")
def item_detail(item_id: int):
    conn = get_conn()
    try:
        item = conn.execute(
            """SELECT i.*, vc.catalog_number, vc.product_url,
                      vc.sds_url AS catalog_sds_url, vc.list_price
               FROM inventory i
               LEFT JOIN vendor_catalog vc ON vc.id = i.catalog_id
               WHERE i.item_id = ?""",
            (item_id,),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        item = dict(item)
        item["photo_url"] = _product_photo_url(item.get("photo_filename"))
        lots = _rows(
            conn.execute(
                """SELECT id, item_id, lot_number, expiry_date, quantity,
                          received_date, coa_url
                   FROM item_lot WHERE item_id = ?
                   ORDER BY (expiry_date IS NULL), expiry_date""",
                (item_id,),
            )
        )
        raw = _rows(
            conn.execute(
                """SELECT c.id, c.box_id, c.row, c.col, c.status,
                          c.expected_box_id, c.expected_row, c.expected_col,
                          l.lot_number, l.expiry_date
                   FROM container c
                   JOIN item_lot l ON l.id = c.item_lot_id
                   WHERE l.item_id = ?
                   ORDER BY c.id""",
                (item_id,),
            )
        )
        for c in raw:
            c["location_path"] = _location_path(conn, c["box_id"])
        documents = _documents_for(conn, "item_id", item_id)
        return {"item": item, "lots": lots, "containers": raw,
                "documents": documents}
    finally:
        conn.close()


@router.post(
    "/items/{item_id}/photo",
    dependencies=[Depends(auth.require_role("member"))],
)
async def upload_item_photo(
    item_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(auth.require_role("member")),
):
    if not (file.content_type or "").lower().startswith("image/"):
        raise HTTPException(status_code=400, detail="file must be an image")

    # Derive a safe name: basename only (kills traversal), extension whitelist,
    # stem reduced to [A-Za-z0-9._-], unique item_<id>_<token>_<stem>.<ext>.
    original = os.path.basename(file.filename or "")
    stem, dot, ext = original.rpartition(".")
    ext = ext.lower()
    if not dot or ext not in _PRODUCT_IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"extension must be one of: {', '.join(sorted(_PRODUCT_IMAGE_EXTS))}",
        )
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:60] or "photo"
    filename = f"item_{item_id}_{_secrets.token_hex(4)}_{safe_stem}.{ext}"

    data = await file.read(_PRODUCT_IMAGE_MAX_BYTES + 1)
    if len(data) > _PRODUCT_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="image exceeds 10MB limit")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT photo_filename FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="item not found")

        os.makedirs(_PRODUCT_UPLOAD_DIR, exist_ok=True)
        dest = os.path.join(_PRODUCT_UPLOAD_DIR, filename)
        # Belt and braces: the joined path must resolve inside the uploads dir.
        if os.path.dirname(os.path.abspath(dest)) != os.path.abspath(_PRODUCT_UPLOAD_DIR):
            raise HTTPException(status_code=400, detail="invalid filename")
        with open(dest, "wb") as fh:
            fh.write(data)

        conn.execute(
            "UPDATE inventory SET photo_filename = ? WHERE item_id = ?",
            (filename, item_id),
        )
        _audit(conn, user, "item.photo", "inventory", item_id, filename)
        conn.commit()
        _unlink_product_photo(row["photo_filename"])  # replaced photo, if any
        return {"item_id": item_id, "photo_url": _product_photo_url(filename)}
    finally:
        conn.close()


@router.delete(
    "/items/{item_id}/photo",
    dependencies=[Depends(auth.require_role("member"))],
)
def delete_item_photo(
    item_id: int, user: dict = Depends(auth.require_role("member"))
):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT photo_filename FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="item not found")
        conn.execute(
            "UPDATE inventory SET photo_filename = NULL WHERE item_id = ?", (item_id,)
        )
        _audit(conn, user, "item.photo", "inventory", item_id, "cleared")
        conn.commit()
        _unlink_product_photo(row["photo_filename"])
        return {"ok": True}
    finally:
        conn.close()


@router.patch(
    "/items/{item_id}",
    dependencies=[Depends(auth.require_role("manager"))],
)
def update_item(
    item_id: int,
    payload: dict = Body(...),
    user: dict = Depends(auth.require_role("manager")),
):
    # Whitelist filter: only known columns survive, in _ITEM_EDITABLE_COLS order.
    fields = {k: payload[k] for k in _ITEM_EDITABLE_COLS if k in payload}
    if not fields:
        raise HTTPException(status_code=400, detail="no updatable fields provided")
    if "item_name" in fields:
        fields["item_name"] = str(fields["item_name"] or "").strip()
        if not fields["item_name"]:
            raise HTTPException(status_code=400, detail="item_name cannot be empty")
    if "category" in fields and fields["category"] not in _ITEM_CATEGORIES:
        raise HTTPException(
            status_code=400, detail=f"unknown category: {fields['category']}"
        )
    if "status" in fields and fields["status"] not in _ITEM_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"unknown status: {fields['status']}"
        )
    if "is_controlled" in fields:
        fields["is_controlled"] = 1 if fields["is_controlled"] else 0
    conn = get_conn()
    try:
        exists = conn.execute(
            "SELECT item_name FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="item not found")
        set_sql = ", ".join(f"{col} = ?" for col in fields)  # whitelisted names
        conn.execute(
            f"UPDATE inventory SET {set_sql} WHERE item_id = ?",
            (*fields.values(), item_id),
        )
        action = (
            "item.deprecate" if fields.get("status") == "deprecated"
            else "item.restore" if fields.get("status") == "active"
            else "item.update"
        )
        _audit(conn, user, action, "inventory", item_id,
               f"{exists['item_name']}: {', '.join(sorted(fields))}")
        conn.commit()
        return dict(
            conn.execute(
                "SELECT * FROM inventory WHERE item_id = ?", (item_id,)
            ).fetchone()
        )
    finally:
        conn.close()


@router.get("/categories")
def categories():
    conn = get_conn()
    try:
        # Count only active items so the dropdown totals match the default
        # (deprecated-excluded) /api/items list.
        counts = {
            r["category"]: r["c"]
            for r in conn.execute(
                "SELECT category, COUNT(*) AS c FROM inventory "
                "WHERE status = 'active' GROUP BY category"
            ).fetchall()
        }
        return {
            "categories": [
                {"name": name, "count": counts.get(name, 0)}
                for name in _ITEM_CATEGORIES
            ]
        }
    finally:
        conn.close()


class ConsumeBody(BaseModel):
    quantity: int
    staff_id: Optional[int] = None
    note: Optional[str] = None


@router.post("/items/{item_id}/consume")
def consume_item(
    item_id: int,
    body: ConsumeBody,
    user: dict = Depends(auth.require_role("member")),
):
    if body.quantity is None or body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    conn = get_conn()
    try:
        item = conn.execute(
            "SELECT item_id FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")

        # Atomic guarded deduction. This conditional UPDATE is the single point
        # that decides success: SQLite serializes writers and each re-evaluates
        # the WHERE against committed state, so concurrent consumes cannot both
        # pass a stale check and drive quantity_on_hand negative.
        cur = conn.execute(
            """UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?
               WHERE item_id = ? AND quantity_on_hand >= ?""",
            (body.quantity, item_id, body.quantity),
        )
        if cur.rowcount == 0:
            conn.rollback()
            raise HTTPException(
                status_code=400, detail="insufficient quantity on hand"
            )

        # Deduct from lots first-expiry-first (nulls last), in the same write
        # transaction so lot totals stay in sync with on-hand.
        remaining = body.quantity
        lots = conn.execute(
            """SELECT id, quantity FROM item_lot
               WHERE item_id = ? AND quantity > 0
               ORDER BY (expiry_date IS NULL), expiry_date, id""",
            (item_id,),
        ).fetchall()
        for lot in lots:
            if remaining <= 0:
                break
            take = min(lot["quantity"], remaining)
            conn.execute(
                "UPDATE item_lot SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                (take, lot["id"], take),
            )
            remaining -= take
        if remaining > 0:
            # On-hand covered the consume (the guarded UPDATE above succeeded)
            # but the lots did not, so this item carries stock no lot accounts
            # for. Legitimate for legacy rows created before opening lots
            # existed; never silent, because it is also how real drift shows up.
            log.warning(
                "item %s: consumed %s but lots only covered %s -- %s unit(s) had "
                "no lot behind them (see GET /api/integrity/stock)",
                item_id, body.quantity, body.quantity - remaining, remaining,
            )
        conn.execute(
            """INSERT INTO usage_event
                   (item_id, container_id, staff_id, event_type, quantity, occurred_at, note)
               VALUES (?, NULL, ?, 'consume', ?, datetime('now'), ?)""",
            (item_id, body.staff_id, body.quantity, body.note),
        )
        _audit(conn, user, "consume", "inventory", item_id,
               f"-{body.quantity}" + (f" ({body.note})" if body.note else ""))
        conn.commit()
        new_on_hand = conn.execute(
            "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()["quantity_on_hand"]
        return {"ok": True, "item_id": item_id, "quantity_on_hand": new_on_hand}
    finally:
        conn.close()


class RestockBody(BaseModel):
    quantity: int
    lot_number: Optional[str] = None
    expiry_date: Optional[str] = None
    staff_id: Optional[int] = None
    coa_url: Optional[str] = None


@router.post("/items/{item_id}/restock")
def restock_item(
    item_id: int,
    body: RestockBody,
    user: dict = Depends(auth.require_role("member")),
):
    if body.quantity is None or body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    conn = get_conn()
    try:
        item = conn.execute(
            "SELECT * FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")

        existing = None
        if body.lot_number:
            existing = conn.execute(
                "SELECT id FROM item_lot WHERE item_id = ? AND lot_number = ?",
                (item_id, body.lot_number),
            ).fetchone()

        if existing is not None:
            # Top up the lot; a provided coa_url replaces the stored one,
            # while an absent coa_url leaves it untouched.
            conn.execute(
                """UPDATE item_lot
                   SET quantity = quantity + ?, coa_url = COALESCE(?, coa_url)
                   WHERE id = ?""",
                (body.quantity, body.coa_url, existing["id"]),
            )
            lot_id = existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO item_lot
                       (item_id, lot_number, expiry_date, quantity,
                        received_date, coa_url)
                   VALUES (?, ?, ?, ?, date('now'), ?)""",
                (item_id, body.lot_number, body.expiry_date, body.quantity,
                 body.coa_url),
            )
            lot_id = cur.lastrowid

        conn.execute(
            "UPDATE inventory SET quantity_on_hand = quantity_on_hand + ? WHERE item_id = ?",
            (body.quantity, item_id),
        )
        conn.execute(
            """INSERT INTO usage_event
                   (item_id, container_id, staff_id, event_type, quantity, occurred_at, note)
               VALUES (?, NULL, ?, 'restock', ?, datetime('now'), ?)""",
            (item_id, body.staff_id, body.quantity, body.lot_number),
        )
        _audit(conn, user, "restock", "inventory", item_id,
               f"+{body.quantity}" + (f" lot {body.lot_number}" if body.lot_number else ""))
        conn.commit()
        new_on_hand = conn.execute(
            "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()["quantity_on_hand"]
        return {
            "ok": True,
            "item_id": item_id,
            "lot_id": lot_id,
            "quantity_on_hand": new_on_hand,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# read-only SQL console (opt-in; see app/sqlconsole.py for the safety model)
# --------------------------------------------------------------------------- #
def _sql_console_enabled(conn):
    """True only when an admin has explicitly switched the console on."""
    raw = _get_setting(conn, "ui_config", None)
    if not raw:
        return False
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError):
        return False
    return isinstance(cfg, dict) and cfg.get("sql_console_enabled") is True


def _require_sql_console(conn):
    if not _sql_console_enabled(conn):
        raise HTTPException(
            status_code=403,
            detail="the SQL console is disabled (enable it in Settings)",
        )


class SqlQueryBody(BaseModel):
    sql: str


@router.get("/sql/schema", dependencies=[Depends(auth.require_role("admin"))])
def sql_schema():
    """Queryable tables and columns, so the console can show what exists."""
    conn = get_conn()
    try:
        _require_sql_console(conn)
    finally:
        conn.close()
    return {"tables": sqlconsole.schema_overview(_db.DB_PATH)}


@router.post("/sql/query", dependencies=[Depends(auth.require_role("admin"))])
def sql_query(body: SqlQueryBody, user: dict = Depends(auth.require_role("admin"))):
    """Run one read-only SELECT against the lab database.

    Admin-only AND off unless explicitly enabled. Every query is audited: this is
    the most powerful surface in the app, so it should never be silent.
    """
    conn = get_conn()
    try:
        _require_sql_console(conn)
    finally:
        conn.close()

    sql = (body.sql or "").strip()
    try:
        result = sqlconsole.run_query(_db.DB_PATH, sql)
    except sqlconsole.QueryError as exc:
        # Record refused/failed attempts too -- they are the interesting ones.
        audit_conn = get_conn()
        try:
            _audit(audit_conn, user, "sql.query.failed", "app_setting", None,
                   f"{sql[:200]} -- {exc}")
            audit_conn.commit()
        finally:
            audit_conn.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_conn = get_conn()
    try:
        _audit(audit_conn, user, "sql.query", "app_setting", None,
               f"{sql[:200]} -> {result['row_count']} row(s)")
        audit_conn.commit()
    finally:
        audit_conn.close()
    return result


class ResolveCodeBody(BaseModel):
    code: str


@router.post("/scan/resolve")
def resolve_scan(body: ResolveCodeBody):
    """Resolve a scanned QR/barcode to an item, so the client never has to know
    the code formats (QR deep link, item id, or vendor catalog number)."""
    conn = get_conn()
    try:
        item_id = _resolve_scan_code(conn, body.code)
        if item_id is None:
            return {"matched": False, "item": None}
        row = conn.execute(
            """SELECT item_id, item_name, unit, quantity_on_hand, status
                 FROM inventory WHERE item_id = ?""",
            (item_id,),
        ).fetchone()
        return {"matched": True, "item": dict(row) if row else None}
    finally:
        conn.close()


class LotPatchBody(BaseModel):
    lot_number: Optional[str] = None
    expiry_date: Optional[str] = None
    coa_url: Optional[str] = None


@router.patch("/lots/{lot_id}", dependencies=[Depends(auth.require_role("member"))])
def patch_lot(lot_id: int, body: LotPatchBody,
              user: dict = Depends(auth.require_role("member"))):
    """Edit a lot's identity: lot number, expiry, CoA link.

    Lots could previously only be born from a restock, so stock that arrived any
    other way -- an opening balance, a CSV import -- had no way to ever gain an
    expiry date, and expiry alerts (which read item_lot) could never see it.
    This is the endpoint that makes imported stock trackable.
    """
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    expiry = fields.get("expiry_date")
    if expiry:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(expiry)):
            raise HTTPException(
                status_code=400, detail="expiry_date must be YYYY-MM-DD"
            )
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, item_id FROM item_lot WHERE id = ?", (lot_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="lot not found")
        cols = [c for c in ("lot_number", "expiry_date", "coa_url") if c in fields]
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        conn.execute(
            f"UPDATE item_lot SET {set_clause} WHERE id = ?",
            [fields[c] for c in cols] + [lot_id],
        )
        _audit(conn, user, "lot.update", "item_lot", lot_id,
               ", ".join(f"{c}={fields[c]}" for c in cols))
        conn.commit()
        return dict(
            conn.execute("SELECT * FROM item_lot WHERE id = ?", (lot_id,)).fetchone()
        )
    finally:
        conn.close()


@router.get("/integrity/stock", dependencies=[Depends(auth.require_role("manager"))])
def stock_integrity():
    """Items whose lot quantities do not add up to their recorded stock.

    The app keeps quantity_on_hand and the per-lot quantities as separate
    numbers. They should agree; when they do not, expiry alerts and the stock
    figure are telling different stories, so surface it rather than let it rot:

      untracked > 0  -- stock with no lot behind it, invisible to expiry alerts
      over_lotted    -- lots claim more than the item holds (a real error)
    """
    conn = get_conn()
    try:
        rows = _rows(conn.execute(
            """SELECT i.item_id, i.item_name, i.unit, i.quantity_on_hand,
                      COALESCE(SUM(l.quantity), 0) AS lot_total
                 FROM inventory i
                 LEFT JOIN item_lot l ON l.item_id = i.item_id
                WHERE i.status = 'active'
                GROUP BY i.item_id
               HAVING COALESCE(SUM(l.quantity), 0) <> i.quantity_on_hand
                ORDER BY i.item_name COLLATE NOCASE"""
        ))
        for r in rows:
            diff = r["quantity_on_hand"] - r["lot_total"]
            r["untracked"] = max(diff, 0)
            r["over_lotted"] = max(-diff, 0)
        return {
            "count": len(rows),
            "untracked_items": sum(1 for r in rows if r["untracked"]),
            "over_lotted_items": sum(1 for r in rows if r["over_lotted"]),
            "items": rows,
        }
    finally:
        conn.close()


class SetQuantityBody(BaseModel):
    quantity: int
    reason: Optional[str] = None
    staff_id: Optional[int] = None


@router.post("/items/{item_id}/set-quantity")
def set_item_quantity(
    item_id: int,
    body: SetQuantityBody,
    user: dict = Depends(auth.require_role("member")),
):
    """Reconcile stock to a counted value: "the shelf has 7, make it 7".

    Consume/restock express *movements*; this expresses a correction, which is
    what a physical count produces. Doing it as one action (rather than
    consuming the difference) keeps usage history honest -- the delta is
    recorded as an 'adjust' event, which analytics deliberately ignore, so a
    recount never looks like consumption.

    Lots: when the count is below the recorded lot total, lots are trimmed
    first-expiry-first to match, so expiry alerts stop referring to stock that
    is not there. A count *above* the lot total leaves lots alone -- the extra
    units have no known lot or expiry, and inventing one would be a lie; the
    response reports the shortfall so the caller can prompt for a lot.
    """
    if body.quantity is None or body.quantity < 0:
        raise HTTPException(status_code=400, detail="quantity must be zero or positive")
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="item not found")
        previous = row["quantity_on_hand"]
        delta = body.quantity - previous

        conn.execute(
            "UPDATE inventory SET quantity_on_hand = ? WHERE item_id = ?",
            (body.quantity, item_id),
        )

        # Trim lots FEFO when they now over-state what is physically present.
        lot_total = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS t FROM item_lot WHERE item_id = ?",
            (item_id,),
        ).fetchone()["t"]
        lots_trimmed = 0
        excess = lot_total - body.quantity
        if excess > 0:
            for lot in conn.execute(
                """SELECT id, quantity FROM item_lot
                   WHERE item_id = ? AND quantity > 0
                   ORDER BY (expiry_date IS NULL), expiry_date, id""",
                (item_id,),
            ).fetchall():
                if excess <= 0:
                    break
                take = min(lot["quantity"], excess)
                conn.execute(
                    "UPDATE item_lot SET quantity = quantity - ? WHERE id = ?",
                    (take, lot["id"]),
                )
                excess -= take
                lots_trimmed += take

        conn.execute(
            """INSERT INTO usage_event
                   (item_id, container_id, staff_id, event_type, quantity,
                    occurred_at, note)
               VALUES (?, NULL, ?, 'adjust', ?, datetime('now'), ?)""",
            (item_id, body.staff_id, delta, body.reason),
        )
        _audit(conn, user, "item.set_quantity", "inventory", item_id,
               f"{previous} -> {body.quantity}"
               + (f" ({body.reason})" if body.reason else ""))
        conn.commit()
        # Positive when the count exceeds what the lots account for.
        unlotted = body.quantity - max(lot_total - lots_trimmed, 0)
        return {
            "ok": True,
            "item_id": item_id,
            "previous": previous,
            "quantity_on_hand": body.quantity,
            "delta": delta,
            "lots_trimmed": lots_trimmed,
            "untracked_by_lot": max(unlotted, 0),
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# containers
# --------------------------------------------------------------------------- #
@router.get("/containers/{container_id}")
def container_detail(container_id: int):
    conn = get_conn()
    try:
        c = conn.execute(
            """SELECT c.id, c.item_lot_id, c.box_id, c.row, c.col,
                      c.expected_box_id, c.expected_row, c.expected_col, c.status,
                      i.item_id, i.item_name, l.lot_number, l.expiry_date
               FROM container c
               JOIN item_lot l ON l.id = c.item_lot_id
               JOIN inventory i ON i.item_id = l.item_id
               WHERE c.id = ?""",
            (container_id,),
        ).fetchone()
        if c is None:
            raise HTTPException(status_code=404, detail="container not found")
        c = dict(c)
        c["location_path"] = _location_path(conn, c["box_id"])
        c["expected_location_path"] = _location_path(conn, c["expected_box_id"])
        c["misplaced"] = bool(
            c["expected_box_id"] is not None
            and (
                c["box_id"] != c["expected_box_id"]
                or c["row"] != c["expected_row"]
                or c["col"] != c["expected_col"]
            )
        )
        return c
    finally:
        conn.close()


class MoveBody(BaseModel):
    box_id: Optional[int] = None
    row: Optional[int] = None
    col: Optional[int] = None


@router.patch("/containers/{container_id}")
def move_container(
    container_id: int,
    body: MoveBody,
    user: dict = Depends(auth.require_role("member")),
):
    conn = get_conn()
    try:
        c = conn.execute(
            "SELECT * FROM container WHERE id = ?", (container_id,)
        ).fetchone()
        if c is None:
            raise HTTPException(status_code=404, detail="container not found")

        new_box = body.box_id if body.box_id is not None else c["box_id"]
        new_row = body.row if body.row is not None else c["row"]
        new_col = body.col if body.col is not None else c["col"]

        # Validate the target box exists and is a box within its grid capacity.
        box = conn.execute(
            "SELECT id, kind, capacity_rows, capacity_cols FROM location_node WHERE id = ?",
            (new_box,),
        ).fetchone()
        if box is None:
            raise HTTPException(status_code=400, detail="target box not found")
        if box["kind"] != "box":
            raise HTTPException(status_code=400, detail="target is not a box")
        if box["capacity_rows"] is not None and not (
            1 <= new_row <= box["capacity_rows"]
        ):
            raise HTTPException(status_code=400, detail="row out of range")
        if box["capacity_cols"] is not None and not (
            1 <= new_col <= box["capacity_cols"]
        ):
            raise HTTPException(status_code=400, detail="col out of range")

        # Any other container at the target well is a collision. A live (in_use)
        # occupant blocks the move; an empty/discarded placeholder is cleared so
        # the well never ends up holding two overlapping rows.
        occupant = conn.execute(
            """SELECT id, status FROM container
               WHERE box_id = ? AND row = ? AND col = ? AND id <> ?""",
            (new_box, new_row, new_col, container_id),
        ).fetchone()
        if occupant is not None:
            if occupant["status"] == "in_use":
                raise HTTPException(status_code=400, detail="target well is occupied")
            conn.execute("DELETE FROM container WHERE id = ?", (occupant["id"],))

        conn.execute(
            "UPDATE container SET box_id = ?, row = ?, col = ? WHERE id = ?",
            (new_box, new_row, new_col, container_id),
        )
        conn.execute(
            """INSERT INTO usage_event
                   (item_id, container_id, staff_id, event_type, quantity, occurred_at, note)
               VALUES (
                   (SELECT l.item_id FROM item_lot l
                      JOIN container c ON c.item_lot_id = l.id WHERE c.id = ?),
                   ?, NULL, 'move', NULL, datetime('now'), ?)""",
            (container_id, container_id, f"moved to box {new_box} [{new_row},{new_col}]"),
        )
        _audit(conn, user, "container.move", "container", container_id,
               f"-> box {new_box} [{new_row},{new_col}]")
        conn.commit()
        return container_detail(container_id)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# alerts
# --------------------------------------------------------------------------- #
@router.get("/alerts/expiring")
def alerts_expiring(days: int = Query(30, ge=0)):
    conn = get_conn()
    try:
        today = _today(conn)
        rows = _rows(
            conn.execute(
                """SELECT i.item_name, l.lot_number, l.expiry_date, l.quantity,
                          CAST(julianday(l.expiry_date) - julianday(?) AS INTEGER) AS days_left
                   FROM item_lot l
                   JOIN inventory i ON i.item_id = l.item_id
                   WHERE l.expiry_date IS NOT NULL
                     AND l.expiry_date <= date(?, '+' || ? || ' day')
                   ORDER BY l.expiry_date""",
                (today, today, days),
            )
        )
        return rows
    finally:
        conn.close()


@router.get("/alerts/lowstock")
def alerts_lowstock():
    conn = get_conn()
    try:
        rows = _rows(
            conn.execute(
                """SELECT item_id, item_name, quantity_on_hand, reorder_threshold, unit_cost
                   FROM inventory
                   WHERE quantity_on_hand <= reorder_threshold
                   ORDER BY (quantity_on_hand - reorder_threshold), item_name"""
            )
        )
        out = []
        for r in rows:
            target = max(r["reorder_threshold"] * 2, r["reorder_threshold"] + 1)
            suggested = max(target - r["quantity_on_hand"], 1)
            out.append(
                {
                    "item_id": r["item_id"],
                    "item_name": r["item_name"],
                    "quantity_on_hand": r["quantity_on_hand"],
                    "reorder_threshold": r["reorder_threshold"],
                    "suggested_order_qty": suggested,
                    "estimated_cost": round(suggested * (r["unit_cost"] or 0), 2),
                }
            )
        return out
    finally:
        conn.close()


@router.get("/alerts/misplaced")
def alerts_misplaced():
    conn = get_conn()
    try:
        rows = _rows(
            conn.execute(
                """SELECT c.id AS container_id, i.item_name,
                          c.box_id, c.row, c.col,
                          c.expected_box_id, c.expected_row, c.expected_col
                   FROM container c
                   JOIN item_lot l ON l.id = c.item_lot_id
                   JOIN inventory i ON i.item_id = l.item_id
                   WHERE c.status = 'in_use' AND c.expected_box_id IS NOT NULL
                     AND (c.box_id <> c.expected_box_id
                          OR c.row <> c.expected_row
                          OR c.col <> c.expected_col)
                   ORDER BY c.id"""
            )
        )
        out = []
        for r in rows:
            out.append(
                {
                    "container_id": r["container_id"],
                    "item_name": r["item_name"],
                    "actual": {
                        "box": _box_name(conn, r["box_id"]),
                        "row": r["row"],
                        "col": r["col"],
                    },
                    "expected": {
                        "box": _box_name(conn, r["expected_box_id"]),
                        "row": r["expected_row"],
                        "col": r["expected_col"],
                    },
                }
            )
        return out
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# analytics
# --------------------------------------------------------------------------- #
@router.get("/analytics/usage")
def analytics_usage(
    item_id: Optional[int] = None, days: int = Query(90, ge=1, le=3650)
):
    conn = get_conn()
    try:
        today = _today(conn)
        item_name = None
        if item_id is not None:
            row = conn.execute(
                "SELECT item_name FROM inventory WHERE item_id = ?", (item_id,)
            ).fetchone()
            item_name = row["item_name"] if row else None

        params = [today, days]
        # Compare the raw column, not date(column): wrapping an indexed column in a
        # function prevents SQLite using idx_usage_occurred and full-scans the table.
        where = "e.event_type = 'consume' AND e.occurred_at >= date(?, '-' || ? || ' day')"
        if item_id is not None:
            where += " AND e.item_id = ?"
            params.append(item_id)

        raw = conn.execute(
            f"""SELECT date(e.occurred_at) AS d, COALESCE(SUM(e.quantity), 0) AS q
                FROM usage_event e
                WHERE {where}
                GROUP BY date(e.occurred_at)""",
            params,
        ).fetchall()
        by_date = {r["d"]: r["q"] for r in raw}

        # Zero-fill a continuous daily series so charts have a clean x-axis.
        series = []
        from datetime import date, timedelta

        y, m, d = (int(x) for x in today.split("-"))
        end = date(y, m, d)
        start = end - timedelta(days=days - 1)
        cur = start
        while cur <= end:
            iso = cur.isoformat()
            series.append({"date": iso, "quantity": by_date.get(iso, 0)})
            cur += timedelta(days=1)

        return {"series": series, "item_name": item_name}
    finally:
        conn.close()


@router.get("/analytics/spend")
def analytics_spend():
    conn = get_conn()
    try:
        rows = _rows(
            conn.execute(
                """WITH monthly AS (
                       SELECT strftime('%Y-%m', order_date) AS month,
                              SUM(quantity * unit_cost) AS spend
                       FROM orders
                       GROUP BY strftime('%Y-%m', order_date)
                   )
                   SELECT month,
                          ROUND(spend, 2) AS monthly_spend,
                          ROUND(SUM(spend) OVER (ORDER BY month), 2) AS cumulative_spend
                   FROM monthly
                   ORDER BY month"""
            )
        )
        return rows
    finally:
        conn.close()


@router.get("/analytics/colony")
def analytics_colony():
    conn = get_conn()
    try:
        rows = _rows(
            conn.execute(
                """SELECT strain, sex, COUNT(*) AS n_alive,
                          ROUND(AVG(julianday(date('now')) - julianday(date_of_birth)) / 7.0, 1)
                              AS avg_age_weeks
                   FROM animals
                   WHERE status = 'alive'
                   GROUP BY strain, sex
                   ORDER BY strain, sex"""
            )
        )
        return rows
    finally:
        conn.close()


@router.get("/analytics/forecast")
def analytics_forecast(days: int = Query(90, ge=1, le=3650)):
    conn = get_conn()
    try:
        today = _today(conn)
        rows = _rows(
            conn.execute(
                """SELECT i.item_id, i.item_name, i.quantity_on_hand,
                          COALESCE(u.total_used, 0) AS total_used
                   FROM inventory i
                   LEFT JOIN (
                       SELECT item_id, SUM(quantity) AS total_used
                       FROM usage_event
                       WHERE event_type = 'consume'
                         AND occurred_at >= date(?, '-' || ? || ' day')
                       GROUP BY item_id
                   ) u ON u.item_id = i.item_id
                   ORDER BY i.item_name""",
                (today, days),
            )
        )
        out = []
        for r in rows:
            avg_daily = r["total_used"] / days if r["total_used"] else 0
            dts = (
                round(r["quantity_on_hand"] / avg_daily, 1)
                if avg_daily > 0
                else None
            )
            out.append(
                {
                    "item_id": r["item_id"],
                    "item_name": r["item_name"],
                    "quantity_on_hand": r["quantity_on_hand"],
                    "avg_daily_use": round(avg_daily, 3),
                    "days_to_stockout": dts,
                }
            )
        return out
    finally:
        conn.close()


@router.get("/analytics/operations",
            dependencies=[Depends(auth.require_role("member"))])
def analytics_operations():
    """Operations dashboard: equipment health/booking, fund burn-down, stocktake
    accuracy, top ticket consumers, and kits assembled. Read-only, cheap SQL."""
    conn = get_conn()
    try:
        today = _today(conn)

        # ---- equipment ------------------------------------------------------
        eq = conn.execute(
            """SELECT
                   COUNT(*)                                                   AS total,
                   COALESCE(SUM(status = 'operational'), 0)                   AS operational,
                   COALESCE(SUM(status = 'maintenance'), 0)                   AS in_maintenance,
                   COALESCE(SUM(status = 'out_of_service'), 0)                AS out_of_service,
                   COALESCE(SUM(next_service_date IS NOT NULL
                                AND next_service_date < ?), 0)                AS service_overdue,
                   COALESCE(SUM(next_service_date IS NOT NULL
                                AND next_service_date >= ?
                                AND next_service_date <= date(?, '+14 day')), 0)
                                                                              AS service_due_soon
               FROM equipment""",
            (today, today, today),
        ).fetchone()
        reservations_upcoming = conn.execute(
            "SELECT COUNT(*) c FROM equipment_reservation WHERE ends_at >= datetime('now')"
        ).fetchone()["c"]
        top_booked = _rows(conn.execute(
            """SELECT e.name, COUNT(r.id) AS reservations
               FROM equipment e
               JOIN equipment_reservation r ON r.equipment_id = e.id
               GROUP BY e.id
               HAVING reservations > 0
               ORDER BY reservations DESC, e.name COLLATE NOCASE ASC
               LIMIT 5"""
        ))
        equipment = {
            "total": eq["total"],
            "operational": eq["operational"],
            "in_maintenance": eq["in_maintenance"],
            "out_of_service": eq["out_of_service"],
            "service_overdue": eq["service_overdue"],
            "service_due_soon": eq["service_due_soon"],
            "reservations_upcoming": reservations_upcoming,
            "top_booked": top_booked,
        }

        # ---- funds ----------------------------------------------------------
        fund_rows = _rows(conn.execute(
            """SELECT f.name, f.budget,
                      COALESCE(SUM(c.amount), 0) AS spent
               FROM fund f
               LEFT JOIN fund_charge c ON c.fund_id = f.id
               GROUP BY f.id
               ORDER BY f.name COLLATE NOCASE ASC, f.id ASC"""
        ))
        by_fund = []
        total_budget = total_spent = 0.0
        for f in fund_rows:
            budget = round(f["budget"] or 0, 2)
            spent = round(f["spent"] or 0, 2)
            remaining = round(budget - spent, 2)
            total_budget += budget
            total_spent += spent
            by_fund.append({
                "name": f["name"],
                "budget": budget,
                "spent": spent,
                "remaining": remaining,
                "pct_spent": round(spent / budget * 100, 1) if budget else 0.0,
            })
        funds = {
            "total_budget": round(total_budget, 2),
            "total_spent": round(total_spent, 2),
            "total_remaining": round(total_budget - total_spent, 2),
            "by_fund": by_fund,
        }

        # ---- counts (stocktake accuracy) ------------------------------------
        sess = _rows(conn.execute(
            """SELECT cs.id, cs.name, cs.location_id, cs.status, cs.closed_at,
                      COALESCE(SUM(cl.expected), 0)         AS expected,
                      COALESCE(SUM(cl.status = 'found'), 0) AS found
               FROM count_session cs
               LEFT JOIN count_line cl ON cl.session_id = cs.id
               GROUP BY cs.id
               ORDER BY cs.closed_at DESC, cs.id DESC"""
        ))
        sessions_total = len(sess)
        closed = [s for s in sess if s["status"] == "closed"]
        accuracies = []
        recent = []
        for s in closed:
            expected = s["expected"] or 0
            acc = (s["found"] / expected) if expected else 1.0
            accuracies.append(acc)
        for s in closed[:5]:
            expected = s["expected"] or 0
            acc = (s["found"] / expected) if expected else 1.0
            name_or_location = s["name"] or (
                _location_path(conn, s["location_id"]) if s["location_id"] else None
            )
            recent.append({
                "id": s["id"],
                "name_or_location": name_or_location,
                "accuracy": round(acc, 4),
                "closed_at": s["closed_at"],
            })
        avg_accuracy = round(sum(accuracies) / len(accuracies), 4) if accuracies else 1.0
        counts = {
            "sessions": sessions_total,
            "closed": len(closed),
            "avg_accuracy": avg_accuracy,
            "recent": recent,
        }

        # ---- top consumers (from tickets; mirrors /usage/by-member) ---------
        top_consumers = _rows(conn.execute(
            """SELECT u.username, u.full_name,
                      COUNT(DISTINCT t.id)                          AS tickets,
                      COALESCE(SUM(tl.quantity), 0)                 AS total_qty,
                      COALESCE(SUM(tl.quantity * i.unit_cost), 0)   AS total_cost
               FROM app_user u
               JOIN ticket t ON t.user_id = u.id
               LEFT JOIN ticket_line tl ON tl.ticket_id = t.id
               LEFT JOIN inventory i ON i.item_id = tl.item_id
               WHERE u.role IN ('member','manager','admin')
               GROUP BY u.id
               HAVING tickets > 0
               ORDER BY total_qty DESC, u.username COLLATE NOCASE ASC
               LIMIT 5"""
        ))
        for c in top_consumers:
            c["total_cost"] = round(c["total_cost"] or 0, 2)

        # ---- kits assembled -------------------------------------------------
        kits_assembled = conn.execute(
            "SELECT COUNT(*) c FROM usage_event WHERE note LIKE 'kit:%'"
        ).fetchone()["c"]

        return {
            "equipment": equipment,
            "funds": funds,
            "counts": counts,
            "top_consumers": top_consumers,
            "kits_assembled": kits_assembled,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# staff (used by the Lab Tycoon game to attribute usage events to real people)
# --------------------------------------------------------------------------- #
@router.get("/staff")
def staff():
    conn = get_conn()
    try:
        return _rows(
            conn.execute(
                "SELECT staff_id, full_name, role, email, hire_date FROM staff ORDER BY staff_id"
            )
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# reset
# --------------------------------------------------------------------------- #
@router.post("/reset")
def reset(request: Request, user: dict = Depends(auth.require_role("manager"))):
    # Reset wipes every table and reloads the demo data. That is only ever
    # appropriate on a demo instance -- on a real lab it would destroy live
    # data -- so it is refused unless demo seeding is on (or explicitly allowed
    # via NLM_ALLOW_RESET). This makes the "Reset demo data" button safe.
    allow_reset = os.environ.get("NLM_ALLOW_RESET", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if not (auth.demo_enabled() or allow_reset):
        raise HTTPException(
            status_code=403,
            detail="reset is disabled on this instance (demo mode only)",
        )
    rebuild_db()
    # The rebuild wiped the session table; restore the caller's session so
    # resetting the demo data does not log them out mid-session.
    token = request.cookies.get(auth.COOKIE_NAME)
    if auth.auth_enabled() and token:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT id FROM app_user WHERE username = ?", (user["username"],)
            ).fetchone()
            if row is not None:
                conn.execute(
                    """INSERT OR REPLACE INTO session
                           (token, user_id, created_at, expires_at)
                       VALUES (?, ?, datetime('now'), datetime('now', ?))""",
                    (token, row["id"], f"+{auth.SESSION_DAYS} day"),
                )
                conn.commit()
        finally:
            conn.close()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# item creation (spreadsheet "add new item" form)
# --------------------------------------------------------------------------- #
class ItemCreateBody(BaseModel):
    item_name: str
    vendor: Optional[str] = None
    unit: Optional[str] = None
    category: str = "other"
    quantity_on_hand: int = 0
    reorder_threshold: int = 0
    unit_cost: float = 0.0
    sds_url: Optional[str] = None
    disposal_instructions: Optional[str] = None
    is_controlled: bool = False
    controlled_schedule: Optional[str] = None
    reorder_max: Optional[int] = None
    hazard_class: Optional[str] = None
    cas_number: Optional[str] = None
    catalog_id: Optional[int] = None
    storage_temp: Optional[str] = None
    light_sensitive: bool = False


@router.post("/items", dependencies=[Depends(auth.require_role("manager"))])
def create_item(body: ItemCreateBody, user: dict = Depends(auth.require_role("manager"))):
    name = (body.item_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="item_name cannot be empty")
    if body.category not in _ITEM_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"unknown category: {body.category}")
    if body.quantity_on_hand < 0 or body.reorder_threshold < 0:
        raise HTTPException(status_code=400, detail="quantities cannot be negative")
    if body.reorder_max is not None and body.reorder_max < 0:
        raise HTTPException(status_code=400, detail="reorder_max cannot be negative")
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO inventory
                   (item_name, vendor, unit, quantity_on_hand, reorder_threshold,
                    unit_cost, category, sds_url, disposal_instructions, status,
                    is_controlled, controlled_schedule,
                    reorder_max, hazard_class, cas_number, catalog_id,
                    storage_temp, light_sensitive)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, body.vendor, body.unit, body.quantity_on_hand,
             body.reorder_threshold, body.unit_cost, body.category, body.sds_url,
             body.disposal_instructions, 1 if body.is_controlled else 0,
             body.controlled_schedule, body.reorder_max, body.hazard_class,
             body.cas_number, body.catalog_id, body.storage_temp,
             1 if body.light_sensitive else 0),
        )
        item_id = cur.lastrowid
        # An opening balance is recorded as a restock so analytics/history line up.
        if body.quantity_on_hand > 0:
            conn.execute(
                """INSERT INTO usage_event
                       (item_id, container_id, staff_id, event_type, quantity,
                        occurred_at, note)
                   VALUES (?, NULL, NULL, 'restock', ?, datetime('now'), 'opening balance')""",
                (item_id, body.quantity_on_hand),
            )
            _open_lot(conn, item_id, body.quantity_on_hand)
        _audit(conn, user, "item.create", "inventory", item_id, name)
        conn.commit()
        return dict(
            conn.execute("SELECT * FROM inventory WHERE item_id = ?", (item_id,)).fetchone()
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CSV bulk import (mirrors the inventory.csv export columns)
# --------------------------------------------------------------------------- #
# Recognized columns; only item_name is required. Extra columns are ignored.
_IMPORT_MAX_BYTES = 10 * 1024 * 1024  # ~10MB cap, matching the other uploads
_IMPORT_INT_COLS = ("quantity_on_hand", "reorder_threshold", "reorder_max")
_IMPORT_FLOAT_COLS = ("unit_cost",)
_IMPORT_TEXT_COLS = (
    "vendor", "unit", "sds_url", "hazard_class", "cas_number",
    "disposal_instructions",
)


def _import_match(conn, row, name):
    """Resolve a CSV row to an existing item, most-specific key first.

    catalog_number -> item_id -> item_name. Matching on the product name alone
    is unreliable for a real lab: two distinct reagents can share a name, and a
    re-imported vendor sheet then either duplicates rows or merges the wrong
    ones. A catalog number identifies the actual product, and item_id (which the
    export emits) is exact, so both are preferred when the sheet carries them.
    """
    catalog_number = row.get("catalog_number", "")
    if catalog_number:
        hit = conn.execute(
            """SELECT i.item_id FROM inventory i
                 JOIN vendor_catalog vc ON vc.id = i.catalog_id
                WHERE lower(vc.catalog_number) = lower(?)
                ORDER BY i.item_id LIMIT 1""",
            (catalog_number,),
        ).fetchone()
        if hit is not None:
            return hit

    raw_id = row.get("item_id", "")
    if raw_id:
        try:
            hit = conn.execute(
                "SELECT item_id FROM inventory WHERE item_id = ?", (int(float(raw_id)),)
            ).fetchone()
        except (TypeError, ValueError):
            hit = None
        if hit is not None:
            return hit

    return conn.execute(
        "SELECT item_id FROM inventory WHERE lower(item_name) = lower(?) LIMIT 1",
        (name,),
    ).fetchone()


@router.post(
    "/import/inventory",
    dependencies=[Depends(auth.require_role("manager"))],
)
async def import_inventory(
    file: UploadFile = File(...),
    dry_run: str = Form("false"),
    user: dict = Depends(auth.require_role("manager")),
):
    """Bulk create/update inventory from a CSV (mirrors the export columns).

    Rows are matched to existing items by catalog_number, then item_id, then
    item_name (all case-insensitive) -- see _import_match: a match updates the
    provided columns, otherwise a new active item is inserted. Bad rows are
    collected as per-row errors and skipped (the import is NOT aborted).
    dry_run computes the same summary but rolls back with no writes.
    """
    is_dry = str(dry_run).strip().lower() in ("true", "1", "yes", "on")

    # Cap the read like the other upload endpoints do, so a huge file cannot be
    # pulled into memory whole.
    raw = await file.read(_IMPORT_MAX_BYTES + 1)
    if len(raw) > _IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"file is too large (limit {_IMPORT_MAX_BYTES // (1024 * 1024)}MB)",
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="file must be UTF-8 text")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no header row")

    created = 0
    updated = 0
    errors = []

    conn = get_conn()
    try:
        # 1-based data-row index (row 1 = first row after the header).
        for row_num, raw_row in enumerate(reader, start=1):
            # Normalize keys/values (strip whitespace; None-safe).
            row = {
                (k or "").strip(): (v.strip() if isinstance(v, str) else "")
                for k, v in raw_row.items()
            }
            name = row.get("item_name", "")
            if not name:
                errors.append({"row": row_num, "message": "item_name is required"})
                continue

            # Category (optional): validate only when supplied.
            category = row.get("category", "")
            if category and category not in _ITEM_CATEGORIES:
                errors.append({"row": row_num,
                               "message": f"unknown category: {category}"})
                continue

            # Coerce provided numerics; a bad value fails the whole row.
            provided = {}
            bad = None
            for col in _IMPORT_INT_COLS:
                if row.get(col, "") != "":
                    try:
                        provided[col] = int(float(row[col]))
                    except (TypeError, ValueError):
                        bad = f"{col} must be an integer"
                        break
                    if provided[col] < 0:
                        bad = f"{col} cannot be negative"
                        break
            if bad is None:
                for col in _IMPORT_FLOAT_COLS:
                    if row.get(col, "") != "":
                        try:
                            provided[col] = float(row[col])
                        except (TypeError, ValueError):
                            bad = f"{col} must be a number"
                            break
                        if provided[col] < 0:
                            bad = f"{col} cannot be negative"
                            break
            if bad is not None:
                errors.append({"row": row_num, "message": bad})
                continue

            if category:
                provided["category"] = category
            for col in _IMPORT_TEXT_COLS:
                if row.get(col, "") != "":
                    provided[col] = row[col]

            existing = _import_match(conn, row, name)

            if existing is not None:
                if provided:
                    cols = list(provided.keys())
                    set_clause = ", ".join(f"{c} = ?" for c in cols)
                    params = [provided[c] for c in cols] + [existing["item_id"]]
                    conn.execute(
                        f"UPDATE inventory SET {set_clause} WHERE item_id = ?",
                        params,
                    )
                    # A re-import that changes the stock figure must move the
                    # lots with it, or the item ends up with stock no lot
                    # accounts for -- invisible to expiry alerts and reported as
                    # drift by /api/integrity/stock. Recorded as an adjustment,
                    # not consumption, exactly as a counted correction is.
                    if "quantity_on_hand" in provided:
                        delta = _sync_lots_to_quantity(
                            conn, existing["item_id"], provided["quantity_on_hand"],
                        )
                        if delta:
                            conn.execute(
                                """INSERT INTO usage_event
                                       (item_id, container_id, staff_id, event_type,
                                        quantity, occurred_at, note)
                                   VALUES (?, NULL, NULL, 'adjust', ?, datetime('now'),
                                           'CSV import')""",
                                (existing["item_id"], delta),
                            )
                updated += 1
            else:
                qty = provided.get("quantity_on_hand", 0)
                cur = conn.execute(
                    """INSERT INTO inventory
                           (item_name, vendor, unit, quantity_on_hand,
                            reorder_threshold, unit_cost, category, sds_url,
                            disposal_instructions, status, reorder_max,
                            hazard_class, cas_number)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
                    (name, provided.get("vendor"), provided.get("unit"), qty,
                     provided.get("reorder_threshold", 0),
                     provided.get("unit_cost", 0),
                     provided.get("category", "other"), provided.get("sds_url"),
                     provided.get("disposal_instructions"),
                     provided.get("reorder_max"), provided.get("hazard_class"),
                     provided.get("cas_number")),
                )
                # Opening balance is logged as a restock (as create_item does).
                if qty > 0:
                    conn.execute(
                        """INSERT INTO usage_event
                               (item_id, container_id, staff_id, event_type,
                                quantity, occurred_at, note)
                           VALUES (?, NULL, NULL, 'restock', ?, datetime('now'),
                                   'imported opening balance')""",
                        (cur.lastrowid, qty),
                    )
                    _open_lot(conn, cur.lastrowid, qty, expiry=row.get("expiry_date") or None)
                created += 1

        if is_dry:
            conn.rollback()
        else:
            _audit(conn, user, "import", "inventory", None,
                   f"{created} created, {updated} updated")
            conn.commit()
        return {"dry_run": is_dry, "created": created, "updated": updated,
                "errors": errors}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# settings + per-member usage
# --------------------------------------------------------------------------- #
_SETTING_KEYS = {"usage_visibility", "po_approval_threshold"}
_USAGE_VISIBILITY_VALUES = {"admin_only", "all"}
_PO_APPROVAL_THRESHOLD_DEFAULT = "500"


def _get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _can_see_all_usage(conn, user):
    """Managers/admins always see everyone's usage; members only when the admin
    has opened it up via usage_visibility = 'all'."""
    role = (user or {}).get("role")
    if role in ("admin", "manager"):
        return True
    return _get_setting(conn, "usage_visibility", "admin_only") == "all"


@router.get("/settings")
def get_settings():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT key, value FROM app_setting").fetchall()
        settings = {r["key"]: r["value"] for r in rows}
        settings.setdefault("usage_visibility", "admin_only")
        settings.setdefault("po_approval_threshold", _PO_APPROVAL_THRESHOLD_DEFAULT)
        return settings
    finally:
        conn.close()


@router.patch("/settings", dependencies=[Depends(auth.require_role("admin"))])
def update_settings(payload: dict = Body(...), user: dict = Depends(auth.require_role("admin"))):
    updates = {k: payload[k] for k in _SETTING_KEYS if k in payload}
    if not updates:
        raise HTTPException(status_code=400, detail="no known settings provided")
    if "usage_visibility" in updates and updates["usage_visibility"] not in _USAGE_VISIBILITY_VALUES:
        raise HTTPException(status_code=400, detail="invalid usage_visibility value")
    if "po_approval_threshold" in updates:
        try:
            if float(updates["po_approval_threshold"]) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="po_approval_threshold must be a non-negative number")
    conn = get_conn()
    try:
        for key, value in updates.items():
            conn.execute(
                "INSERT INTO app_setting (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
        _audit(conn, user, "settings.update", "app_setting", None,
               ", ".join(f"{k}={v}" for k, v in updates.items()))
        conn.commit()
        return get_settings()
    finally:
        conn.close()


@router.get("/config")
def get_config():
    """Persisted UI config blob (app_setting key 'ui_config'). {} if absent or unparseable."""
    conn = get_conn()
    try:
        raw = _get_setting(conn, "ui_config", None)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    finally:
        conn.close()


@router.patch("/config", dependencies=[Depends(auth.require_role("admin"))])
def update_config(payload: dict = Body(...), user: dict = Depends(auth.require_role("admin"))):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="config must be a JSON object")
    try:
        blob = json.dumps(payload)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="config must be JSON-serializable")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO app_setting (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("ui_config", blob),
        )
        _audit(conn, user, "config.update", "app_setting", None, "ui_config")
        conn.commit()
        return payload
    finally:
        conn.close()


@router.get("/usage/by-member")
def usage_by_member(user: dict = Depends(auth.current_user)):
    """Per-person consumption, aggregated from tickets (the member-attributed
    workflow). Members see only their own row unless usage_visibility='all'."""
    conn = get_conn()
    try:
        see_all = _can_see_all_usage(conn, user)
        me_id = _current_uid(conn, user)
        where, params = "", []
        if not see_all:
            where = "WHERE u.id = ?"
            params = [me_id]
        totals = _rows(conn.execute(
            f"""SELECT u.id AS user_id, u.username, u.full_name, u.role,
                       COUNT(DISTINCT t.id) AS tickets,
                       COALESCE(SUM(tl.quantity), 0) AS total_qty,
                       COALESCE(SUM(tl.quantity * i.unit_cost), 0) AS total_cost
                FROM app_user u
                LEFT JOIN ticket t ON t.user_id = u.id
                LEFT JOIN ticket_line tl ON tl.ticket_id = t.id
                LEFT JOIN inventory i ON i.item_id = tl.item_id
                {where}
                GROUP BY u.id
                HAVING u.role IN ('member','manager','admin')
                ORDER BY total_qty DESC, u.username""",
            tuple(params),
        ))
        # per-purpose breakdown, same visibility scope
        pwhere = "WHERE t.purpose IS NOT NULL"
        pparams = []
        if not see_all:
            pwhere += " AND t.user_id = ?"
            pparams = [me_id]
        by_purpose = _rows(conn.execute(
            f"""SELECT t.user_id, t.purpose,
                       COALESCE(SUM(tl.quantity), 0) AS qty
                FROM ticket t
                JOIN ticket_line tl ON tl.ticket_id = t.id
                {pwhere}
                GROUP BY t.user_id, t.purpose
                ORDER BY qty DESC""",
            tuple(pparams),
        ))
        return {
            "can_see_all": see_all,
            "visibility": _get_setting(conn, "usage_visibility", "admin_only"),
            "members": totals,
            "by_purpose": by_purpose,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# task templates (recurring-procedure recipes that pre-fill a ticket)
# --------------------------------------------------------------------------- #
class TemplateLineIn(BaseModel):
    item_id: int
    default_quantity: int


class TemplateBody(BaseModel):
    name: str
    description: Optional[str] = None
    lines: List[TemplateLineIn] = []


def _template_with_lines(conn, template_id):
    t = conn.execute(
        "SELECT id, name, description FROM task_template WHERE id = ?", (template_id,)
    ).fetchone()
    if t is None:
        return None
    lines = _rows(conn.execute(
        """SELECT ttl.item_id, ttl.default_quantity, i.item_name, i.unit
           FROM task_template_line ttl
           JOIN inventory i ON i.item_id = ttl.item_id
           WHERE ttl.template_id = ?
           ORDER BY ttl.id""",
        (template_id,),
    ))
    d = dict(t)
    d["lines"] = lines
    return d


@router.get("/task-templates")
def task_templates():
    conn = get_conn()
    try:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM task_template ORDER BY name"
        ).fetchall()]
        return [_template_with_lines(conn, tid) for tid in ids]
    finally:
        conn.close()


def _write_template_lines(conn, template_id, lines):
    conn.execute("DELETE FROM task_template_line WHERE template_id = ?", (template_id,))
    for ln in lines:
        if ln.default_quantity <= 0:
            continue
        exists = conn.execute(
            "SELECT 1 FROM inventory WHERE item_id = ?", (ln.item_id,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=400, detail=f"unknown item_id {ln.item_id}")
        conn.execute(
            "INSERT INTO task_template_line (template_id, item_id, default_quantity) VALUES (?, ?, ?)",
            (template_id, ln.item_id, ln.default_quantity),
        )


@router.post("/task-templates", dependencies=[Depends(auth.require_role("manager"))])
def create_template(body: TemplateBody, user: dict = Depends(auth.require_role("manager"))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name cannot be empty")
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM task_template WHERE name = ?", (name,)).fetchone():
            raise HTTPException(status_code=400, detail="a template with that name exists")
        cur = conn.execute(
            "INSERT INTO task_template (name, description) VALUES (?, ?)",
            (name, body.description),
        )
        tid = cur.lastrowid
        _write_template_lines(conn, tid, body.lines)
        _audit(conn, user, "task.create", "task_template", tid, name)
        conn.commit()
        return _template_with_lines(conn, tid)
    finally:
        conn.close()


@router.patch("/task-templates/{template_id}", dependencies=[Depends(auth.require_role("manager"))])
def update_template(template_id: int, body: TemplateBody, user: dict = Depends(auth.require_role("manager"))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name cannot be empty")
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM task_template WHERE id = ?", (template_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="template not found")
        clash = conn.execute(
            "SELECT 1 FROM task_template WHERE name = ? AND id <> ?", (name, template_id)
        ).fetchone()
        if clash:
            raise HTTPException(status_code=400, detail="a template with that name exists")
        conn.execute(
            "UPDATE task_template SET name = ?, description = ? WHERE id = ?",
            (name, body.description, template_id),
        )
        _write_template_lines(conn, template_id, body.lines)
        _audit(conn, user, "task.update", "task_template", template_id, name)
        conn.commit()
        return _template_with_lines(conn, template_id)
    finally:
        conn.close()


@router.delete("/task-templates/{template_id}", dependencies=[Depends(auth.require_role("manager"))])
def delete_template(template_id: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT name FROM task_template WHERE id = ?", (template_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="template not found")
        conn.execute("DELETE FROM task_template_line WHERE template_id = ?", (template_id,))
        conn.execute("DELETE FROM task_template WHERE id = ?", (template_id,))
        _audit(conn, user, "task.delete", "task_template", template_id, row["name"])
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# tickets (daily usage log: who used what, and why)
# --------------------------------------------------------------------------- #
class TicketLineIn(BaseModel):
    item_id: int
    quantity: int
    unit: Optional[str] = None


class TicketCreateBody(BaseModel):
    task: Optional[str] = None
    purpose: Optional[str] = None
    note: Optional[str] = None
    ticket_date: Optional[str] = None
    lines: List[TicketLineIn] = []
    consume: bool = True


def _ticket_detail(conn, ticket_id):
    t = conn.execute(
        """SELECT t.id, t.user_id, t.ticket_date, t.task, t.purpose, t.note,
                  t.created_at, u.username, u.full_name
           FROM ticket t
           LEFT JOIN app_user u ON u.id = t.user_id
           WHERE t.id = ?""",
        (ticket_id,),
    ).fetchone()
    if t is None:
        return None
    lines = _rows(conn.execute(
        """SELECT tl.item_id, tl.quantity,
                  COALESCE(tl.unit, i.unit) AS unit, i.item_name, i.unit_cost
           FROM ticket_line tl
           JOIN inventory i ON i.item_id = tl.item_id
           WHERE tl.ticket_id = ?
           ORDER BY tl.id""",
        (ticket_id,),
    ))
    d = dict(t)
    d["lines"] = lines
    d["total_qty"] = sum(ln["quantity"] for ln in lines)
    d["total_cost"] = round(sum(ln["quantity"] * (ln["unit_cost"] or 0) for ln in lines), 2)
    return d


@router.post("/tickets", dependencies=[Depends(auth.require_role("member"))])
def create_ticket(body: TicketCreateBody, user: dict = Depends(auth.require_role("member"))):
    lines = [ln for ln in body.lines if ln.quantity and ln.quantity > 0]
    if not lines:
        raise HTTPException(status_code=400, detail="a ticket needs at least one line")
    conn = get_conn()
    try:
        uid = _current_uid(conn, user)
        today = _today(conn)
        cur = conn.execute(
            """INSERT INTO ticket (user_id, ticket_date, task, purpose, note, created_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (uid, body.ticket_date or today, body.task, body.purpose, body.note),
        )
        ticket_id = cur.lastrowid
        for ln in lines:
            item = conn.execute(
                "SELECT item_id, item_name FROM inventory WHERE item_id = ?", (ln.item_id,)
            ).fetchone()
            if item is None:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"unknown item_id {ln.item_id}")
            conn.execute(
                "INSERT INTO ticket_line (ticket_id, item_id, quantity, unit) VALUES (?, ?, ?, ?)",
                (ticket_id, ln.item_id, ln.quantity, (ln.unit or None)),
            )
            if body.consume:
                # Atomic guarded deduction, same pattern as /consume: the WHERE
                # clause is the only gate, so concurrent tickets can't overdraw.
                res = conn.execute(
                    """UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?
                       WHERE item_id = ? AND quantity_on_hand >= ?""",
                    (ln.quantity, ln.item_id, ln.quantity),
                )
                if res.rowcount == 0:
                    conn.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail=f"insufficient stock for {item['item_name']}",
                    )
                remaining = ln.quantity
                for lot in conn.execute(
                    """SELECT id, quantity FROM item_lot
                       WHERE item_id = ? AND quantity > 0
                       ORDER BY (expiry_date IS NULL), expiry_date, id""",
                    (ln.item_id,),
                ).fetchall():
                    if remaining <= 0:
                        break
                    take = min(lot["quantity"], remaining)
                    conn.execute(
                        "UPDATE item_lot SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                        (take, lot["id"], take),
                    )
                    remaining -= take
                conn.execute(
                    """INSERT INTO usage_event
                           (item_id, container_id, staff_id, event_type, quantity,
                            occurred_at, note, ticket_id, purpose)
                       VALUES (?, NULL, NULL, 'consume', ?, datetime('now'), ?, ?, ?)""",
                    (ln.item_id, ln.quantity, body.task, ticket_id, body.purpose),
                )
        _audit(conn, user, "ticket.create", "ticket", ticket_id,
               f"{body.task or 'usage'}: {len(lines)} item(s)"
               + (f" -- {body.purpose}" if body.purpose else ""))
        conn.commit()
        return _ticket_detail(conn, ticket_id)
    finally:
        conn.close()


@router.get("/tickets")
def list_tickets(user: dict = Depends(auth.current_user),
                 mine: bool = False,
                 limit: int = Query(100, ge=1, le=500)):
    conn = get_conn()
    try:
        see_all = _can_see_all_usage(conn, user)
        me_id = _current_uid(conn, user)
        clauses, params = [], []
        if mine or not see_all:
            clauses.append("t.user_id = ?")
            params.append(me_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = _rows(conn.execute(
            f"""SELECT t.id, t.user_id, t.ticket_date, t.task, t.purpose, t.note,
                       t.created_at, u.username, u.full_name,
                       COUNT(tl.id) AS line_count,
                       COALESCE(SUM(tl.quantity), 0) AS total_qty
                FROM ticket t
                LEFT JOIN app_user u ON u.id = t.user_id
                LEFT JOIN ticket_line tl ON tl.ticket_id = t.id
                {where}
                GROUP BY t.id
                ORDER BY t.ticket_date DESC, t.id DESC
                LIMIT ?""",
            (*params, limit),
        ))
        return {"can_see_all": see_all, "tickets": rows}
    finally:
        conn.close()


@router.get("/tickets/{ticket_id}")
def ticket_detail(ticket_id: int, user: dict = Depends(auth.current_user)):
    conn = get_conn()
    try:
        d = _ticket_detail(conn, ticket_id)
        if d is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        if not _can_see_all_usage(conn, user) and d["user_id"] != _current_uid(conn, user):
            raise HTTPException(status_code=403, detail="not your ticket")
        return d
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# audit history (append-only trail; oversight tool -> manager+)
# --------------------------------------------------------------------------- #
@router.get("/audit", dependencies=[Depends(auth.require_role("manager"))])
def audit_history(action: Optional[str] = None,
                  username: Optional[str] = None,
                  limit: int = Query(100, ge=1, le=500),
                  offset: int = Query(0, ge=0)):
    conn = get_conn()
    try:
        clauses, params = [], []
        if action:
            clauses.append("action = ?")
            params.append(action)
        if username:
            clauses.append("username = ?")
            params.append(username)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) c FROM audit_log {where}", tuple(params)
        ).fetchone()["c"]
        entries = _rows(conn.execute(
            f"""SELECT id, occurred_at, user_id, username, action,
                       entity_type, entity_id, detail
                FROM audit_log {where}
                ORDER BY occurred_at DESC, id DESC
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ))
        actions = [r["action"] for r in conn.execute(
            "SELECT DISTINCT action FROM audit_log ORDER BY action"
        ).fetchall()]
        return {"total": total, "entries": entries, "actions": actions}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# purchasing (draft -> submitted -> ordered -> received)
# --------------------------------------------------------------------------- #
_PO_STATUSES = (
    "draft", "pending_approval", "approved", "submitted",
    "ordered", "received", "cancelled", "rejected",
)

# Allowed status transitions. cancelled is reachable from any non-terminal
# state (handled separately below).
_PO_TRANSITIONS = {
    "draft": {"pending_approval"},
    "pending_approval": {"approved", "rejected"},
    "approved": {"submitted"},
    "submitted": {"ordered"},
    "ordered": {"received"},
}
_PO_TERMINAL = {"received", "cancelled", "rejected"}


class POLineIn(BaseModel):
    item_id: int
    quantity: int
    unit_cost: Optional[float] = None


class POCreateBody(BaseModel):
    vendor: Optional[str] = None
    note: Optional[str] = None
    fund_id: Optional[int] = None
    expected_arrival: Optional[str] = None
    lines: List[POLineIn] = []


def _po_detail(conn, po_id):
    po = conn.execute(
        """SELECT p.id, p.vendor, p.status, p.created_by, p.created_at,
                  p.approved_by, p.approved_at, p.approver_note,
                  p.submitted_at, p.ordered_at, p.received_at, p.note,
                  p.fund_id, p.expected_arrival,
                  u.username, u.full_name,
                  a.username AS approved_by_username,
                  f.name AS fund_name
           FROM purchase_order p
           LEFT JOIN app_user u ON u.id = p.created_by
           LEFT JOIN app_user a ON a.id = p.approved_by
           LEFT JOIN fund f ON f.id = p.fund_id
           WHERE p.id = ?""",
        (po_id,),
    ).fetchone()
    if po is None:
        return None
    lines = _rows(conn.execute(
        """SELECT pl.id, pl.item_id, pl.quantity, pl.unit_cost, pl.received_qty,
                  i.item_name, i.unit
           FROM po_line pl
           JOIN inventory i ON i.item_id = pl.item_id
           WHERE pl.po_id = ?
           ORDER BY pl.id""",
        (po_id,),
    ))
    d = dict(po)
    d["lines"] = lines
    d["total_cost"] = round(sum(ln["quantity"] * (ln["unit_cost"] or 0) for ln in lines), 2)
    d["auto_approved"] = bool(
        d.get("approved_by") is None
        and (d.get("approver_note") or "").startswith("Auto-approved")
    )
    d["documents"] = _documents_for(conn, "po_id", po_id)
    return d


@router.get("/purchase-orders", dependencies=[Depends(auth.require_role("manager"))])
def list_purchase_orders():
    conn = get_conn()
    try:
        rows = _rows(conn.execute(
            """SELECT p.id, p.vendor, p.status, p.created_at,
                      p.approved_at, p.submitted_at, p.ordered_at, p.received_at,
                      p.fund_id, p.expected_arrival,
                      u.username, f.name AS fund_name,
                      COUNT(pl.id) AS line_count,
                      COALESCE(SUM(pl.quantity * pl.unit_cost), 0) AS total_cost
               FROM purchase_order p
               LEFT JOIN app_user u ON u.id = p.created_by
               LEFT JOIN fund f ON f.id = p.fund_id
               LEFT JOIN po_line pl ON pl.po_id = p.id
               GROUP BY p.id
               ORDER BY p.created_at DESC, p.id DESC"""
        ))
        return rows
    finally:
        conn.close()


@router.post(
    "/purchase-orders/draft-line",
    dependencies=[Depends(auth.require_role("member"))],
)
def add_draft_line(body: dict = Body(...), user: dict = Depends(auth.require_role("member"))):
    """Cart-like helper: append an item to the caller's current draft PO,
    creating a fresh draft if they have none. Accumulates quantity when the
    item is already on the draft."""
    item_id = body.get("item_id")
    quantity = body.get("quantity")
    if not isinstance(item_id, int) or isinstance(item_id, bool):
        raise HTTPException(status_code=400, detail="item_id must be an integer")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be a positive integer")
    conn = get_conn()
    try:
        item = conn.execute(
            "SELECT item_id, vendor, unit_cost FROM inventory WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=400, detail=f"unknown item_id {item_id}")
        uid = _current_uid(conn, user)
        draft = conn.execute(
            """SELECT id FROM purchase_order
               WHERE status = 'draft' AND created_by = ?
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        created_draft = draft is None
        if created_draft:
            cur = conn.execute(
                """INSERT INTO purchase_order
                       (vendor, status, created_by, created_at)
                   VALUES (?, 'draft', ?, datetime('now'))""",
                (item["vendor"], uid),
            )
            po_id = cur.lastrowid
        else:
            po_id = draft["id"]
        existing = conn.execute(
            "SELECT id, quantity FROM po_line WHERE po_id = ? AND item_id = ?",
            (po_id, item_id),
        ).fetchone()
        if existing is not None:
            new_qty = existing["quantity"] + quantity
            conn.execute(
                "UPDATE po_line SET quantity = ? WHERE id = ?",
                (new_qty, existing["id"]),
            )
        else:
            new_qty = quantity
            conn.execute(
                "INSERT INTO po_line (po_id, item_id, quantity, unit_cost) VALUES (?, ?, ?, ?)",
                (po_id, item_id, quantity, item["unit_cost"]),
            )
        _audit(conn, user, "po.draft_line", "purchase_order", po_id,
               f"item {item_id}: +{quantity}")
        conn.commit()
        return {"po_id": po_id, "item_id": item_id, "quantity": new_qty,
                "created_draft": created_draft}
    finally:
        conn.close()


@router.get("/purchase-orders/{po_id}", dependencies=[Depends(auth.require_role("manager"))])
def purchase_order_detail(po_id: int):
    conn = get_conn()
    try:
        d = _po_detail(conn, po_id)
        if d is None:
            raise HTTPException(status_code=404, detail="purchase order not found")
        return d
    finally:
        conn.close()


@router.post("/purchase-orders", dependencies=[Depends(auth.require_role("member"))])
def create_purchase_order(body: POCreateBody, user: dict = Depends(auth.require_role("member"))):
    lines = [ln for ln in body.lines if ln.quantity and ln.quantity > 0]
    if not lines:
        raise HTTPException(status_code=400, detail="a purchase order needs at least one line")
    conn = get_conn()
    try:
        uid = _current_uid(conn, user)
        if body.fund_id is not None:
            fund = conn.execute(
                "SELECT id FROM fund WHERE id = ?", (body.fund_id,)
            ).fetchone()
            if fund is None:
                raise HTTPException(status_code=400, detail=f"unknown fund_id {body.fund_id}")
        cur = conn.execute(
            """INSERT INTO purchase_order
                   (vendor, status, created_by, created_at, note,
                    fund_id, expected_arrival)
               VALUES (?, 'draft', ?, datetime('now'), ?, ?, ?)""",
            (body.vendor, uid, body.note, body.fund_id, body.expected_arrival),
        )
        po_id = cur.lastrowid
        for ln in lines:
            item = conn.execute(
                "SELECT item_id, unit_cost FROM inventory WHERE item_id = ?", (ln.item_id,)
            ).fetchone()
            if item is None:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"unknown item_id {ln.item_id}")
            unit_cost = ln.unit_cost if ln.unit_cost is not None else item["unit_cost"]
            conn.execute(
                "INSERT INTO po_line (po_id, item_id, quantity, unit_cost) VALUES (?, ?, ?, ?)",
                (po_id, ln.item_id, ln.quantity, unit_cost),
            )
        _audit(conn, user, "po.create", "purchase_order", po_id,
               f"{body.vendor or 'PO'}: {len(lines)} line(s)")
        conn.commit()
        return _po_detail(conn, po_id)
    finally:
        conn.close()


def _receive_po(conn, po_id):
    """Receive every outstanding line: restock inventory, create a receiving lot,
    book a 'restock' usage_event, and mark the line fully received."""
    lines = conn.execute(
        "SELECT id, item_id, quantity, received_qty, unit_cost FROM po_line WHERE po_id = ?",
        (po_id,),
    ).fetchall()
    for ln in lines:
        outstanding = ln["quantity"] - ln["received_qty"]
        if outstanding <= 0:
            continue
        conn.execute(
            """INSERT INTO item_lot (item_id, lot_number, expiry_date, quantity,
                                     received_date, coa_url)
               VALUES (?, ?, NULL, ?, date('now'), NULL)""",
            (ln["item_id"], f"PO-{po_id}", outstanding),
        )
        conn.execute(
            "UPDATE inventory SET quantity_on_hand = quantity_on_hand + ? WHERE item_id = ?",
            (outstanding, ln["item_id"]),
        )
        conn.execute(
            """INSERT INTO usage_event
                   (item_id, container_id, staff_id, event_type, quantity,
                    occurred_at, note)
               VALUES (?, NULL, NULL, 'restock', ?, datetime('now'), ?)""",
            (ln["item_id"], outstanding, f"received PO-{po_id}"),
        )
        conn.execute(
            "UPDATE po_line SET received_qty = quantity WHERE id = ?", (ln["id"],)
        )


def _update_po_fields(po_id, payload, user, has_fund, has_eta):
    """Set/update fund_id and/or expected_arrival with no status change (manager+)."""
    is_manager = auth.ROLE_RANK.get((user or {}).get("role"), -1) >= auth.ROLE_RANK["manager"]
    if not is_manager:
        raise HTTPException(status_code=403, detail="requires manager role or higher")
    conn = get_conn()
    try:
        po = conn.execute(
            "SELECT id FROM purchase_order WHERE id = ?", (po_id,)
        ).fetchone()
        if po is None:
            raise HTTPException(status_code=404, detail="purchase order not found")
        if has_fund:
            if payload.get("fund_id") is not None and conn.execute(
                "SELECT 1 FROM fund WHERE id = ?", (payload["fund_id"],)
            ).fetchone() is None:
                raise HTTPException(status_code=400, detail=f"unknown fund_id {payload['fund_id']}")
            conn.execute("UPDATE purchase_order SET fund_id = ? WHERE id = ?",
                         (payload.get("fund_id"), po_id))
        if has_eta:
            conn.execute("UPDATE purchase_order SET expected_arrival = ? WHERE id = ?",
                         (payload.get("expected_arrival"), po_id))
        _audit(conn, user, "po.update", "purchase_order", po_id, "fund/eta")
        conn.commit()
        return _po_detail(conn, po_id)
    finally:
        conn.close()


def _charge_fund_on_receipt(conn, po_id, user):
    """When a PO with a fund_id reaches 'received', draw down that fund once.

    Books a fund_charge for the PO's total cost so ordering against a grant
    automatically debits it on receipt. Idempotent: a second call is a no-op if
    a purchase_order charge for this PO already exists (no double-charge).
    """
    po = conn.execute(
        "SELECT id, vendor, fund_id FROM purchase_order WHERE id = ?", (po_id,)
    ).fetchone()
    if po is None or po["fund_id"] is None:
        return
    already = conn.execute(
        """SELECT 1 FROM fund_charge
           WHERE source_type = 'purchase_order' AND source_id = ?""",
        (po_id,),
    ).fetchone()
    if already is not None:
        return
    total = conn.execute(
        "SELECT COALESCE(SUM(quantity * unit_cost), 0) AS t FROM po_line WHERE po_id = ?",
        (po_id,),
    ).fetchone()["t"]
    conn.execute(
        """INSERT INTO fund_charge
               (fund_id, amount, source_type, source_id, description,
                charged_at, charged_by)
           VALUES (?, ?, 'purchase_order', ?, ?, datetime('now'), ?)""",
        (po["fund_id"], round(total, 2), po_id,
         f"PO #{po_id} ({po['vendor'] or 'no vendor'})", _current_uid(conn, user)),
    )


@router.patch("/purchase-orders/{po_id}", dependencies=[Depends(auth.require_role("member"))])
def update_purchase_order(po_id: int, payload: dict = Body(...),
                          user: dict = Depends(auth.require_role("member"))):
    # Fund / expected-arrival edits are independent of the status machine and may
    # arrive on their own (no status field) or alongside a transition.
    has_fund = "fund_id" in payload
    has_eta = "expected_arrival" in payload
    new_status = payload.get("status")
    if new_status is None and (has_fund or has_eta):
        return _update_po_fields(po_id, payload, user, has_fund, has_eta)
    if new_status is None or new_status not in _PO_STATUSES:
        raise HTTPException(status_code=400, detail="a valid status is required")
    approver_note = payload.get("approver_note")
    conn = get_conn()
    try:
        po = conn.execute(
            "SELECT id, status, created_by FROM purchase_order WHERE id = ?", (po_id,)
        ).fetchone()
        if po is None:
            raise HTTPException(status_code=404, detail="purchase order not found")
        current = po["status"]

        # Fund / expected-arrival may ride along with a transition; apply them
        # BEFORE the status branch. Receiving charges the PO's fund by re-reading
        # purchase_order.fund_id, so writing the new fund afterwards meant a
        # "receive + set fund" in one request stored the fund and charged nothing
        # -- and the charge is idempotent, so it never caught up.
        if has_fund:
            if payload.get("fund_id") is not None and conn.execute(
                "SELECT 1 FROM fund WHERE id = ?", (payload["fund_id"],)
            ).fetchone() is None:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"unknown fund_id {payload['fund_id']}")
            conn.execute("UPDATE purchase_order SET fund_id = ? WHERE id = ?",
                         (payload.get("fund_id"), po_id))
        if has_eta:
            conn.execute("UPDATE purchase_order SET expected_arrival = ? WHERE id = ?",
                         (payload.get("expected_arrival"), po_id))

        # Validate the transition. Cancel is allowed from any non-terminal state;
        # every other move must appear in the transition map for the current one.
        if new_status == "cancelled":
            if current in _PO_TERMINAL:
                raise HTTPException(
                    status_code=400,
                    detail=f"cannot cancel a {current} purchase order",
                )
        elif new_status not in _PO_TRANSITIONS.get(current, set()):
            raise HTTPException(
                status_code=400,
                detail=f"illegal transition: {current} -> {new_status}",
            )

        # Authorization. Submitting a draft for approval (requisition) is open to
        # the PO's own creator OR any manager+; every other transition is manager+.
        is_manager = auth.ROLE_RANK.get((user or {}).get("role"), -1) >= auth.ROLE_RANK["manager"]
        submitting_own = new_status == "pending_approval" and current == "draft"
        if submitting_own:
            if not is_manager and po["created_by"] != _current_uid(conn, user):
                raise HTTPException(
                    status_code=403,
                    detail="only the requester or a manager can submit this requisition",
                )
        elif not is_manager:
            raise HTTPException(status_code=403, detail="requires manager role or higher")

        auto_approved = False
        if new_status == "pending_approval":
            # Requisition submitted: auto-approve if the total is under the
            # spend threshold, otherwise hold for manager sign-off.
            total = conn.execute(
                "SELECT COALESCE(SUM(quantity * unit_cost), 0) AS t FROM po_line WHERE po_id = ?",
                (po_id,),
            ).fetchone()["t"]
            threshold_raw = _get_setting(conn, "po_approval_threshold", _PO_APPROVAL_THRESHOLD_DEFAULT)
            try:
                threshold = float(threshold_raw)
            except (TypeError, ValueError):
                threshold = float(_PO_APPROVAL_THRESHOLD_DEFAULT)
            if total <= threshold:
                conn.execute(
                    """UPDATE purchase_order
                       SET status = 'approved', approved_by = NULL,
                           approved_at = datetime('now'), approver_note = ?
                       WHERE id = ?""",
                    (f"Auto-approved: under ${threshold_raw} threshold", po_id),
                )
                _audit(conn, user, "po.auto_approve", "purchase_order", po_id,
                       f"total {round(total, 2)} <= {threshold_raw}")
                auto_approved = True
            else:
                conn.execute(
                    "UPDATE purchase_order SET status = 'pending_approval' WHERE id = ?",
                    (po_id,),
                )
        elif new_status == "approved":
            uid = _current_uid(conn, user)
            conn.execute(
                """UPDATE purchase_order
                   SET status = 'approved', approved_by = ?,
                       approved_at = datetime('now'), approver_note = ?
                   WHERE id = ?""",
                (uid, approver_note, po_id),
            )
        elif new_status == "rejected":
            conn.execute(
                """UPDATE purchase_order
                   SET status = 'rejected', approver_note = ? WHERE id = ?""",
                (approver_note, po_id),
            )
        elif new_status == "submitted":
            conn.execute(
                "UPDATE purchase_order SET status = 'submitted', submitted_at = datetime('now') WHERE id = ?",
                (po_id,),
            )
        elif new_status == "ordered":
            conn.execute(
                "UPDATE purchase_order SET status = 'ordered', ordered_at = datetime('now') WHERE id = ?",
                (po_id,),
            )
        elif new_status == "received":
            _receive_po(conn, po_id)
            conn.execute(
                "UPDATE purchase_order SET status = 'received', received_at = datetime('now') WHERE id = ?",
                (po_id,),
            )
            _charge_fund_on_receipt(conn, po_id, user)
        else:  # cancelled
            conn.execute(
                "UPDATE purchase_order SET status = ? WHERE id = ?", (new_status, po_id)
            )
        if not auto_approved:  # the auto-approve path already audited "po.auto_approve"
            _audit(conn, user, "po.receive" if new_status == "received" else "po.update",
                   "purchase_order", po_id, f"-> {new_status}")
        conn.commit()
        return _po_detail(conn, po_id)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# preparations (in-house recipes -> dated batches)
# --------------------------------------------------------------------------- #
_PREP_BATCH_STATUSES = {"in_use", "used", "discarded"}


class PrepLineIn(BaseModel):
    item_id: int
    quantity: int


class PrepBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    shelf_life_days: Optional[int] = None
    sop_url: Optional[str] = None
    lines: List[PrepLineIn] = []


class MakeBatchBody(BaseModel):
    amount: Optional[str] = None
    lot_label: Optional[str] = None
    expiry_date: Optional[str] = None
    note: Optional[str] = None


class PrepBatchPatch(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None


def _validate_prep_lines(conn, lines):
    """Return normalized recipe lines, or raise 400. Requires >=1 line, qty>0,
    each item existing."""
    clean = [ln for ln in lines if ln.quantity and ln.quantity > 0]
    if not clean:
        raise HTTPException(status_code=400, detail="a preparation needs at least one component")
    for ln in clean:
        if ln.quantity <= 0:
            raise HTTPException(status_code=400, detail="component quantity must be positive")
        item = conn.execute(
            "SELECT item_id FROM inventory WHERE item_id = ?", (ln.item_id,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=400, detail=f"unknown item_id {ln.item_id}")
    return clean


@router.get("/preparations", dependencies=[Depends(auth.require_role("member"))])
def list_preparations():
    conn = get_conn()
    try:
        rows = _rows(conn.execute(
            """SELECT p.id, p.name, p.category, p.description, p.shelf_life_days,
                      (SELECT COUNT(*) FROM preparation_line pl
                       WHERE pl.preparation_id = p.id) AS line_count,
                      (SELECT COUNT(*) FROM preparation_batch b
                       WHERE b.preparation_id = p.id AND b.status = 'in_use')
                          AS batches_active,
                      (SELECT MIN(b.expiry_date) FROM preparation_batch b
                       WHERE b.preparation_id = p.id AND b.status = 'in_use'
                         AND b.expiry_date IS NOT NULL) AS next_batch_expiry
               FROM preparation p
               ORDER BY p.name"""
        ))
        return rows
    finally:
        conn.close()


@router.get("/preparations/{prep_id}", dependencies=[Depends(auth.require_role("member"))])
def preparation_detail(prep_id: int):
    conn = get_conn()
    try:
        p = conn.execute(
            """SELECT id, name, description, category, shelf_life_days, sop_url, note
               FROM preparation WHERE id = ?""",
            (prep_id,),
        ).fetchone()
        if p is None:
            raise HTTPException(status_code=404, detail="preparation not found")
        today = _today(conn)
        lines = _rows(conn.execute(
            """SELECT pl.item_id, pl.quantity, i.item_name, i.unit,
                      i.quantity_on_hand AS on_hand
               FROM preparation_line pl
               JOIN inventory i ON i.item_id = pl.item_id
               WHERE pl.preparation_id = ?
               ORDER BY pl.id""",
            (prep_id,),
        ))
        # Max batches makeable with current stock = min over lines of
        # floor(on_hand / quantity). No lines -> None.
        max_batches = None
        if lines:
            max_batches = min(
                (ln["on_hand"] // ln["quantity"]) if ln["quantity"] else 0
                for ln in lines
            )
        batches = _rows(conn.execute(
            """SELECT b.id, b.lot_label, b.made_by, b.made_at, b.expiry_date,
                      b.amount, b.status, b.note, u.username AS made_by_username
               FROM preparation_batch b
               LEFT JOIN app_user u ON u.id = b.made_by
               WHERE b.preparation_id = ?
               ORDER BY b.made_at DESC, b.id DESC""",
            (prep_id,),
        ))
        for b in batches:
            b["expiry_flag"] = _expiry_flag(b["expiry_date"], today)
        d = dict(p)
        d["lines"] = lines
        d["batches"] = batches
        d["max_batches"] = max_batches
        return d
    finally:
        conn.close()


@router.post("/preparations", dependencies=[Depends(auth.require_role("manager"))])
def create_preparation(body: PrepBody, user: dict = Depends(auth.require_role("manager"))):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    conn = get_conn()
    try:
        clean = _validate_prep_lines(conn, body.lines)
        exists = conn.execute(
            "SELECT id FROM preparation WHERE name = ?", (body.name.strip(),)
        ).fetchone()
        if exists is not None:
            raise HTTPException(status_code=400, detail="a preparation with that name already exists")
        cur = conn.execute(
            """INSERT INTO preparation (name, description, category, shelf_life_days, sop_url, note)
               VALUES (?, ?, ?, ?, ?, NULL)""",
            (body.name.strip(), body.description, body.category, body.shelf_life_days,
             body.sop_url),
        )
        prep_id = cur.lastrowid
        for ln in clean:
            conn.execute(
                "INSERT INTO preparation_line (preparation_id, item_id, quantity) VALUES (?, ?, ?)",
                (prep_id, ln.item_id, ln.quantity),
            )
        _audit(conn, user, "prep.create", "preparation", prep_id,
               f"{body.name.strip()}: {len(clean)} component(s)")
        conn.commit()
        return preparation_detail(prep_id)
    finally:
        conn.close()


@router.patch("/preparations/{prep_id}", dependencies=[Depends(auth.require_role("manager"))])
def update_preparation(prep_id: int, body: PrepBody,
                       user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        p = conn.execute("SELECT id FROM preparation WHERE id = ?", (prep_id,)).fetchone()
        if p is None:
            raise HTTPException(status_code=404, detail="preparation not found")
        clean = _validate_prep_lines(conn, body.lines)
        if body.name is not None:
            if not body.name.strip():
                raise HTTPException(status_code=400, detail="name is required")
            dup = conn.execute(
                "SELECT id FROM preparation WHERE name = ? AND id <> ?",
                (body.name.strip(), prep_id),
            ).fetchone()
            if dup is not None:
                raise HTTPException(status_code=400, detail="a preparation with that name already exists")
        conn.execute(
            """UPDATE preparation
               SET name = COALESCE(?, name),
                   description = ?, category = ?, shelf_life_days = ?, sop_url = ?
               WHERE id = ?""",
            (body.name.strip() if body.name else None, body.description,
             body.category, body.shelf_life_days, body.sop_url, prep_id),
        )
        conn.execute("DELETE FROM preparation_line WHERE preparation_id = ?", (prep_id,))
        for ln in clean:
            conn.execute(
                "INSERT INTO preparation_line (preparation_id, item_id, quantity) VALUES (?, ?, ?)",
                (prep_id, ln.item_id, ln.quantity),
            )
        _audit(conn, user, "prep.update", "preparation", prep_id, None)
        conn.commit()
        return preparation_detail(prep_id)
    finally:
        conn.close()


@router.delete("/preparations/{prep_id}", dependencies=[Depends(auth.require_role("manager"))])
def delete_preparation(prep_id: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        p = conn.execute("SELECT id FROM preparation WHERE id = ?", (prep_id,)).fetchone()
        if p is None:
            raise HTTPException(status_code=404, detail="preparation not found")
        conn.execute("DELETE FROM preparation_batch WHERE preparation_id = ?", (prep_id,))
        conn.execute("DELETE FROM preparation_line WHERE preparation_id = ?", (prep_id,))
        conn.execute("DELETE FROM preparation WHERE id = ?", (prep_id,))
        _audit(conn, user, "prep.delete", "preparation", prep_id, None)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/preparations/{prep_id}/make-batch",
             dependencies=[Depends(auth.require_role("member"))])
def make_preparation_batch(prep_id: int, body: MakeBatchBody,
                           user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        prep = conn.execute(
            "SELECT id, name, shelf_life_days FROM preparation WHERE id = ?", (prep_id,)
        ).fetchone()
        if prep is None:
            raise HTTPException(status_code=404, detail="preparation not found")
        lines = conn.execute(
            """SELECT pl.item_id, pl.quantity, i.item_name
               FROM preparation_line pl JOIN inventory i ON i.item_id = pl.item_id
               WHERE pl.preparation_id = ?""",
            (prep_id,),
        ).fetchall()
        if not lines:
            raise HTTPException(status_code=400, detail="preparation has no components")

        # Consume each component atomically (same guarded pattern as consume_item):
        # any shortfall rolls back the whole batch so partial draws never persist.
        for ln in lines:
            cur = conn.execute(
                """UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?
                   WHERE item_id = ? AND quantity_on_hand >= ?""",
                (ln["quantity"], ln["item_id"], ln["quantity"]),
            )
            if cur.rowcount == 0:
                conn.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"insufficient {ln['item_name']} to make {prep['name']}",
                )
            # First-expiry-first lot drawdown, same transaction.
            remaining = ln["quantity"]
            for lot in conn.execute(
                """SELECT id, quantity FROM item_lot
                   WHERE item_id = ? AND quantity > 0
                   ORDER BY (expiry_date IS NULL), expiry_date, id""",
                (ln["item_id"],),
            ).fetchall():
                if remaining <= 0:
                    break
                take = min(lot["quantity"], remaining)
                conn.execute(
                    "UPDATE item_lot SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                    (take, lot["id"], take),
                )
                remaining -= take
            conn.execute(
                """INSERT INTO usage_event
                       (item_id, container_id, staff_id, event_type, quantity,
                        occurred_at, note)
                   VALUES (?, NULL, NULL, 'consume', ?, datetime('now'), ?)""",
                (ln["item_id"], ln["quantity"], f"prep: {prep['name']}"),
            )

        # A batch's expiry defaults to made + shelf_life_days unless one is given.
        if body.expiry_date:
            expiry = body.expiry_date
        elif prep["shelf_life_days"] is not None:
            expiry = conn.execute(
                "SELECT date('now', ? ) AS d", (f"+{int(prep['shelf_life_days'])} day",)
            ).fetchone()["d"]
        else:
            expiry = None
        cur = conn.execute(
            """INSERT INTO preparation_batch
                   (preparation_id, lot_label, made_by, made_at, expiry_date,
                    amount, status, note)
               VALUES (?, ?, ?, datetime('now'), ?, ?, 'in_use', ?)""",
            (prep_id, body.lot_label, _current_uid(conn, user), expiry,
             body.amount, body.note),
        )
        batch_id = cur.lastrowid
        _audit(conn, user, "prep.make", "preparation_batch", batch_id,
               f"{prep['name']}" + (f" ({body.amount})" if body.amount else ""))
        conn.commit()
        batch = conn.execute(
            """SELECT b.id, b.preparation_id, b.lot_label, b.made_by, b.made_at,
                      b.expiry_date, b.amount, b.status, b.note,
                      u.username AS made_by_username
               FROM preparation_batch b
               LEFT JOIN app_user u ON u.id = b.made_by
               WHERE b.id = ?""",
            (batch_id,),
        ).fetchone()
        d = dict(batch)
        d["expiry_flag"] = _expiry_flag(d["expiry_date"], _today(conn))
        return d
    finally:
        conn.close()


@router.patch("/preparation-batches/{batch_id}",
              dependencies=[Depends(auth.require_role("member"))])
def update_preparation_batch(batch_id: int, body: PrepBatchPatch,
                             user: dict = Depends(auth.require_role("member"))):
    if body.status is not None and body.status not in _PREP_BATCH_STATUSES:
        raise HTTPException(status_code=400, detail="invalid batch status")
    conn = get_conn()
    try:
        b = conn.execute(
            "SELECT id FROM preparation_batch WHERE id = ?", (batch_id,)
        ).fetchone()
        if b is None:
            raise HTTPException(status_code=404, detail="batch not found")
        if body.status is not None:
            conn.execute(
                "UPDATE preparation_batch SET status = ? WHERE id = ?",
                (body.status, batch_id),
            )
        if body.note is not None:
            conn.execute(
                "UPDATE preparation_batch SET note = ? WHERE id = ?",
                (body.note, batch_id),
            )
        _audit(conn, user, "prep.batch", "preparation_batch", batch_id,
               body.status or "note")
        conn.commit()
        batch = conn.execute(
            """SELECT b.id, b.preparation_id, b.lot_label, b.made_by, b.made_at,
                      b.expiry_date, b.amount, b.status, b.note,
                      u.username AS made_by_username
               FROM preparation_batch b
               LEFT JOIN app_user u ON u.id = b.made_by
               WHERE b.id = ?""",
            (batch_id,),
        ).fetchone()
        d = dict(batch)
        d["expiry_flag"] = _expiry_flag(d["expiry_date"], _today(conn))
        return d
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# lab maintenance (recurring chores)
# --------------------------------------------------------------------------- #
class ChoreBody(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    location_id: Optional[int] = None
    interval_days: Optional[int] = None
    next_due: Optional[str] = None
    instructions: Optional[str] = None
    note: Optional[str] = None


class ChoreCompleteBody(BaseModel):
    note: Optional[str] = None


@router.get("/chores", dependencies=[Depends(auth.require_role("member"))])
def list_chores(include_deprecated: bool = False):
    conn = get_conn()
    try:
        today = _today(conn)
        where = "" if include_deprecated else "WHERE status = 'active'"
        rows = _rows(conn.execute(
            f"""SELECT id, name, category, location_id, interval_days,
                      last_done, next_due, instructions, status
               FROM chore
               {where}
               ORDER BY (next_due IS NULL), next_due, name"""
        ))
        for r in rows:
            r["location_path"] = _location_path(conn, r["location_id"])
            r["overdue"] = bool(r["next_due"] and r["next_due"] < today)
            r["days_to_due"] = (
                _days_between(today, r["next_due"]) if r["next_due"] else None
            )
        return rows
    finally:
        conn.close()


@router.get("/chores/{chore_id}", dependencies=[Depends(auth.require_role("member"))])
def chore_detail(chore_id: int):
    conn = get_conn()
    try:
        c = conn.execute(
            """SELECT id, name, category, location_id, interval_days,
                      last_done, next_due, instructions, note, status
               FROM chore WHERE id = ?""",
            (chore_id,),
        ).fetchone()
        if c is None:
            raise HTTPException(status_code=404, detail="chore not found")
        today = _today(conn)
        d = dict(c)
        d["location_path"] = _location_path(conn, d["location_id"])
        d["overdue"] = bool(d["next_due"] and d["next_due"] < today)
        d["days_to_due"] = _days_between(today, d["next_due"]) if d["next_due"] else None
        d["log"] = _rows(conn.execute(
            """SELECT cl.id, cl.done_at, cl.note, u.username AS done_by_username
               FROM chore_log cl LEFT JOIN app_user u ON u.id = cl.done_by
               WHERE cl.chore_id = ?
               ORDER BY cl.done_at DESC, cl.id DESC""",
            (chore_id,),
        ))
        return d
    finally:
        conn.close()


@router.post("/chores", dependencies=[Depends(auth.require_role("manager"))])
def create_chore(body: ChoreBody, user: dict = Depends(auth.require_role("manager"))):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO chore
                   (name, category, location_id, interval_days, next_due,
                    instructions, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (body.name.strip(), body.category, body.location_id, body.interval_days,
             body.next_due, body.instructions, body.note),
        )
        chore_id = cur.lastrowid
        _audit(conn, user, "chore.create", "chore", chore_id, body.name.strip())
        conn.commit()
        return chore_detail(chore_id)
    finally:
        conn.close()


@router.patch("/chores/{chore_id}", dependencies=[Depends(auth.require_role("manager"))])
def update_chore(chore_id: int, body: ChoreBody,
                 user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        c = conn.execute("SELECT id FROM chore WHERE id = ?", (chore_id,)).fetchone()
        if c is None:
            raise HTTPException(status_code=404, detail="chore not found")
        if body.name is not None and not body.name.strip():
            raise HTTPException(status_code=400, detail="name is required")
        conn.execute(
            """UPDATE chore
               SET name = COALESCE(?, name),
                   category = ?, location_id = ?, interval_days = ?,
                   next_due = ?, instructions = ?, note = ?
               WHERE id = ?""",
            (body.name.strip() if body.name else None, body.category,
             body.location_id, body.interval_days, body.next_due,
             body.instructions, body.note, chore_id),
        )
        _audit(conn, user, "chore.update", "chore", chore_id, None)
        conn.commit()
        return chore_detail(chore_id)
    finally:
        conn.close()


@router.delete("/chores/{chore_id}", dependencies=[Depends(auth.require_role("manager"))])
def delete_chore(chore_id: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        c = conn.execute("SELECT id FROM chore WHERE id = ?", (chore_id,)).fetchone()
        if c is None:
            raise HTTPException(status_code=404, detail="chore not found")
        conn.execute("DELETE FROM chore_log WHERE chore_id = ?", (chore_id,))
        conn.execute("DELETE FROM chore WHERE id = ?", (chore_id,))
        _audit(conn, user, "chore.delete", "chore", chore_id, None)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def _set_chore_status(chore_id, status, user):
    conn = get_conn()
    try:
        c = conn.execute("SELECT id FROM chore WHERE id = ?", (chore_id,)).fetchone()
        if c is None:
            raise HTTPException(status_code=404, detail="chore not found")
        conn.execute("UPDATE chore SET status = ? WHERE id = ?", (status, chore_id))
        _audit(conn, user, "chore." + status, "chore", chore_id, None)
        conn.commit()
        return {"ok": True, "status": status}
    finally:
        conn.close()


@router.post("/chores/{chore_id}/deprecate",
             dependencies=[Depends(auth.require_role("manager"))])
def deprecate_chore(chore_id: int, user: dict = Depends(auth.require_role("manager"))):
    """Retire a chore without deleting its completion history."""
    return _set_chore_status(chore_id, "deprecated", user)


@router.post("/chores/{chore_id}/restore",
             dependencies=[Depends(auth.require_role("manager"))])
def restore_chore(chore_id: int, user: dict = Depends(auth.require_role("manager"))):
    return _set_chore_status(chore_id, "active", user)


@router.post("/chores/{chore_id}/complete",
             dependencies=[Depends(auth.require_role("member"))])
def complete_chore(chore_id: int, body: ChoreCompleteBody,
                   user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        c = conn.execute(
            "SELECT id, interval_days FROM chore WHERE id = ?", (chore_id,)
        ).fetchone()
        if c is None:
            raise HTTPException(status_code=404, detail="chore not found")
        conn.execute(
            """INSERT INTO chore_log (chore_id, done_by, done_at, note)
               VALUES (?, ?, datetime('now'), ?)""",
            (chore_id, _current_uid(conn, user), body.note),
        )
        today = _today(conn)
        if c["interval_days"]:
            next_due = conn.execute(
                "SELECT date('now', ?) AS d", (f"+{int(c['interval_days'])} day",)
            ).fetchone()["d"]
            conn.execute(
                "UPDATE chore SET last_done = ?, next_due = ? WHERE id = ?",
                (today, next_due, chore_id),
            )
        else:
            conn.execute(
                "UPDATE chore SET last_done = ? WHERE id = ?", (today, chore_id)
            )
        _audit(conn, user, "chore.complete", "chore", chore_id, None)
        conn.commit()
        return chore_detail(chore_id)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# chemical compatibility / storage segregation
# --------------------------------------------------------------------------- #
# Location kinds that count as a discrete "storage unit" for segregation. A box
# lives inside one of these; a conflict is reported at the deepest such unit that
# co-locates two incompatible hazards.
_STORAGE_UNIT_KINDS = {
    "cabinet", "fridge", "freezer", "shelf", "drawer",
    "rack", "tank", "incubator", "room",
}

# Standard hazard vocabulary (comma-separated keywords in inventory.hazard_class).
_HAZARD_KEYWORDS = {
    "flammable", "oxidizer", "corrosive", "toxic",
    "irritant", "acid", "base", "water-reactive",
}

# Unordered incompatible pairs: ((hazard_a, hazard_b), severity, reason).
_INCOMPATIBLE_PAIRS = [
    (("flammable", "oxidizer"), "danger",
     "Flammables must be segregated from oxidizers (fire/explosion risk)."),
    (("acid", "base"), "danger",
     "Acids and bases must not be co-stored (violent neutralization)."),
    (("flammable", "corrosive"), "warn",
     "Keep flammables away from corrosives."),
    (("oxidizer", "corrosive"), "warn",
     "Oxidizers and corrosives should be separated."),
    (("water-reactive", "acid"), "danger",
     "Water-reactives must be isolated from aqueous acids."),
]


def _parse_hazards(raw):
    """Split a comma-separated hazard_class string into known keywords."""
    if not raw:
        return set()
    return {t.strip().lower() for t in raw.split(",")} & _HAZARD_KEYWORDS


def _compat_conflicts(conn):
    """Scan storage-unit subtrees for co-located incompatible hazard pairs.

    Items are located physically as containers inside boxes; a box sits inside a
    hierarchy of location_nodes. For every storage-unit ancestor of a box we
    accumulate the hazards of the items it holds, then flag each incompatible
    pair present. A pair is reported only at the deepest unit that co-locates it
    (an ancestor room is suppressed when a tighter cabinet/fridge already flags it).
    """
    nodes = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, parent_id, kind, name FROM location_node"
    )}

    _anc = {}

    def ancestors(nid):
        if nid in _anc:
            return _anc[nid]
        out, seen = [], set()
        pid = nodes.get(nid, {}).get("parent_id")
        while pid is not None and pid in nodes and pid not in seen:
            seen.add(pid)
            out.append(pid)
            pid = nodes[pid]["parent_id"]
        _anc[nid] = out
        return out

    unit_haz = {}  # unit_id -> {hazard: set(item_name)}
    rows = conn.execute(
        """SELECT c.box_id, i.item_name, i.hazard_class
           FROM container c
           JOIN item_lot l ON l.id = c.item_lot_id
           JOIN inventory i ON i.item_id = l.item_id
           WHERE c.status = 'in_use'
             AND i.hazard_class IS NOT NULL AND i.hazard_class <> ''"""
    ).fetchall()
    for r in rows:
        hz = _parse_hazards(r["hazard_class"])
        if not hz:
            continue
        for aid in ancestors(r["box_id"]):
            if nodes[aid]["kind"] in _STORAGE_UNIT_KINDS:
                d = unit_haz.setdefault(aid, {})
                for h in hz:
                    d.setdefault(h, set()).add(r["item_name"])

    # Which storage units carry each incompatible pair.
    pair_units = {}  # pair index -> set(unit_id)
    for uid, hmap in unit_haz.items():
        present = set(hmap.keys())
        for idx, (pair, _sev, _reason) in enumerate(_INCOMPATIBLE_PAIRS):
            if pair[0] in present and pair[1] in present:
                pair_units.setdefault(idx, set()).add(uid)

    conflicts = []
    for idx, units in pair_units.items():
        pair, sev, reason = _INCOMPATIBLE_PAIRS[idx]
        for uid in units:
            # Suppress this unit if a descendant unit also flags the same pair.
            if any(uid in ancestors(other) for other in units if other != uid):
                continue
            hmap = unit_haz[uid]
            conflicts.append({
                "location_id": uid,
                "location_path": _location_path(conn, uid),
                "location_kind": nodes[uid]["kind"],
                "hazard_a": pair[0],
                "hazard_b": pair[1],
                "severity": sev,
                "reason": reason,
                "items_a": sorted(hmap[pair[0]]),
                "items_b": sorted(hmap[pair[1]]),
            })

    sev_rank = {"danger": 0, "warn": 1}
    conflicts.sort(key=lambda c: (
        sev_rank.get(c["severity"], 9), c["location_path"] or "",
        c["hazard_a"], c["hazard_b"],
    ))
    return conflicts


def _placement_warnings(conn):
    """Flag items stored in a compartment that isn't rated for them.

    A storage-unit node may declare `allowed_hazards` (comma keywords it is rated
    to hold) and/or `temp_rating` (its temperature). For each in-use container we
    find the nearest storage-unit ancestor that declares such a rating and check
    the item against it: a hazard the compartment isn't rated for, or a required
    storage_temp that doesn't match the compartment's temp_rating, is a warning.
    """
    nodes = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, parent_id, kind, name, allowed_hazards, temp_rating "
        "FROM location_node"
    )}

    _anc = {}

    def ancestors(nid):
        if nid in _anc:
            return _anc[nid]
        out, seen = [], set()
        pid = nodes.get(nid, {}).get("parent_id")
        while pid is not None and pid in nodes and pid not in seen:
            seen.add(pid)
            out.append(pid)
            pid = nodes[pid]["parent_id"]
        _anc[nid] = out
        return out

    def nearest_rated(box_id, field):
        for aid in ancestors(box_id):
            n = nodes[aid]
            if n["kind"] in _STORAGE_UNIT_KINDS and (n.get(field) or "").strip():
                return n
        return None

    rows = conn.execute(
        """SELECT c.box_id, i.item_name, i.hazard_class, i.storage_temp
           FROM container c
           JOIN item_lot l ON l.id = c.item_lot_id
           JOIN inventory i ON i.item_id = l.item_id
           WHERE c.status = 'in_use'"""
    ).fetchall()

    # Dedupe by (location, kind, item): an item with N containers must warn once.
    seen = {}
    for r in rows:
        # hazard-suitability: item hazard not in the compartment's allowed set
        haz = _parse_hazards(r["hazard_class"])
        if haz:
            unit = nearest_rated(r["box_id"], "allowed_hazards")
            if unit is not None:
                allowed = {t.strip().lower() for t in
                           (unit["allowed_hazards"] or "").split(",")} & _HAZARD_KEYWORDS
                bad = sorted(haz - allowed)
                if bad:
                    seen[(unit["id"], "hazard", r["item_name"])] = {
                        "location_id": unit["id"],
                        "location_path": _location_path(conn, unit["id"]),
                        "kind": "hazard",
                        "severity": "danger",
                        "item_name": r["item_name"],
                        "detail": (f"{r['item_name']} is {', '.join(bad)}; "
                                   f"this compartment is only rated for "
                                   f"{unit['allowed_hazards']}."),
                    }
        # temperature: item's required storage_temp differs from compartment rating
        temp = (r["storage_temp"] or "").strip()
        if temp:
            unit = nearest_rated(r["box_id"], "temp_rating")
            if unit is not None and (unit["temp_rating"] or "").strip() != temp:
                seen[(unit["id"], "temperature", r["item_name"])] = {
                    "location_id": unit["id"],
                    "location_path": _location_path(conn, unit["id"]),
                    "kind": "temperature",
                    "severity": "warn",
                    "item_name": r["item_name"],
                    "detail": (f"{r['item_name']} needs {temp} storage but this "
                               f"compartment is rated {unit['temp_rating']}."),
                }

    sev_rank = {"danger": 0, "warn": 1}
    warnings = sorted(seen.values(), key=lambda w: (
        sev_rank.get(w["severity"], 9), w["location_path"] or "", w["item_name"]))
    return warnings


@router.get("/compatibility/conflicts")
def compatibility_conflicts():
    conn = get_conn()
    try:
        return _compat_conflicts(conn)
    finally:
        conn.close()


@router.get("/compatibility/placement")
def compatibility_placement():
    conn = get_conn()
    try:
        return _placement_warnings(conn)
    finally:
        conn.close()


@router.get("/compatibility/rules")
def compatibility_rules():
    return [
        {"hazard_a": pair[0], "hazard_b": pair[1], "severity": sev, "reason": reason}
        for (pair, sev, reason) in _INCOMPATIBLE_PAIRS
    ]


# --------------------------------------------------------------------------- #
# in-app notifications (live, deduplicated broadcast + targeted alerts)
# --------------------------------------------------------------------------- #
_NOTIFICATION_KINDS = (
    "low_stock", "expiring", "approval_pending", "compatibility", "maintenance_due",
    "other",
)

# The exact (kind, entity_type) pairs _sync_notifications regenerates from live
# state, and therefore the only ones it may auto-clear. Matching on kind alone
# swept up one-off alerts that share a kind but are not reconciled -- notably the
# stocktake's ("other", "count_session") alert, which was marked read by the very
# next notification poll and so could never be seen.
_RECONCILED_PAIRS = frozenset({
    ("low_stock", "inventory"),
    ("expiring", "item_lot"),
    ("expiring", "preparation_batch"),
    ("expiring", "software_license"),
    ("maintenance_due", "chore"),
    ("maintenance_due", "equipment"),
    ("approval_pending", "purchase_order"),
    ("compatibility", "location_node"),
    ("other", "glassware_item"),
})


def _sync_notifications(conn):
    """Reconcile broadcast operational alerts with live state, idempotently.

    Builds the set of conditions that currently hold (low stock, expiring lots,
    POs awaiting approval, storage-compatibility conflicts), inserts one unread
    broadcast per new condition (deduped on (kind,entity_type,entity_id) among
    unread rows), and auto-clears (marks read) any unread broadcast in these
    managed kinds whose condition no longer holds.
    """
    # This read-then-insert reconciliation is invoked from a GET that several
    # clients poll concurrently. BEGIN IMMEDIATE takes the write lock up front so
    # two syncs cannot both observe "no alert exists" and both insert one; the
    # second simply waits (busy_timeout) and then sees the first one's rows.
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        # Already inside a transaction -- the caller owns it, which is fine.
        pass

    today = _today(conn)
    desired = {}  # (kind, entity_type, entity_id) -> {severity, message, link_view}

    # LOW STOCK
    for r in conn.execute(
        """SELECT item_id, item_name, quantity_on_hand, reorder_threshold
           FROM inventory
           WHERE status = 'active' AND quantity_on_hand <= reorder_threshold"""
    ):
        desired[("low_stock", "inventory", r["item_id"])] = {
            "severity": "warn", "link_view": "inventory",
            "message": f"{r['item_name']} low: {r['quantity_on_hand']}/{r['reorder_threshold']}",
        }

    # EXPIRING (within 30 days, or already expired) with stock remaining
    for r in conn.execute(
        """SELECT l.id, l.expiry_date, i.item_name
           FROM item_lot l JOIN inventory i ON i.item_id = l.item_id
           WHERE l.expiry_date IS NOT NULL AND l.quantity > 0
             AND l.expiry_date <= date(?, '+30 day')""",
        (today,),
    ):
        expired = r["expiry_date"] < today
        desired[("expiring", "item_lot", r["id"])] = {
            "severity": "danger" if expired else "warn", "link_view": "inventory",
            "message": (
                f"{r['item_name']} lot {'expired' if expired else 'expiring'} "
                f"({r['expiry_date']})"
            ),
        }

    # EXPIRING PREPARATION BATCHES (in_use, within 30 days or already past)
    for r in conn.execute(
        """SELECT b.id, b.expiry_date, p.name
           FROM preparation_batch b JOIN preparation p ON p.id = b.preparation_id
           WHERE b.status = 'in_use' AND b.expiry_date IS NOT NULL
             AND b.expiry_date <= date(?, '+30 day')""",
        (today,),
    ):
        past = r["expiry_date"] < today
        desired[("expiring", "preparation_batch", r["id"])] = {
            "severity": "danger" if past else "warn", "link_view": "preparations",
            "message": f"{r['name']} batch expires {r['expiry_date']}",
        }

    # CHORES DUE (next service within 3 days or overdue); deprecated chores retire.
    for r in conn.execute(
        """SELECT id, name, next_due FROM chore
           WHERE status = 'active'
             AND next_due IS NOT NULL AND next_due <= date(?, '+3 day')""",
        (today,),
    ):
        overdue = r["next_due"] < today
        desired[("maintenance_due", "chore", r["id"])] = {
            "severity": "danger" if overdue else "warn", "link_view": "maintenance",
            "message": f"{r['name']} due {r['next_due']}",
        }

    # APPROVAL PENDING
    for r in conn.execute(
        "SELECT id, vendor FROM purchase_order WHERE status = 'pending_approval'"
    ):
        desired[("approval_pending", "purchase_order", r["id"])] = {
            "severity": "warn", "link_view": "purchasing",
            "message": f"PO #{r['id']} ({r['vendor'] or 'no vendor'}) awaits approval",
        }

    # MAINTENANCE DUE (equipment whose next service is within 14 days or past)
    for r in conn.execute(
        """SELECT id, name, next_service_date
           FROM equipment
           WHERE next_service_date IS NOT NULL
             AND next_service_date <= date(?, '+14 day')""",
        (today,),
    ):
        past = r["next_service_date"] < today
        desired[("maintenance_due", "equipment", r["id"])] = {
            "severity": "danger" if past else "warn", "link_view": "equipment",
            "message": f"{r['name']} service due {r['next_service_date']}",
        }

    # SOFTWARE LICENSES expiring (within 30 days, or already past)
    for r in conn.execute(
        """SELECT id, name, expiry_date FROM software_license
           WHERE expiry_date IS NOT NULL
             AND expiry_date <= date(?, '+30 day')""",
        (today,),
    ):
        past = r["expiry_date"] < today
        desired[("expiring", "software_license", r["id"])] = {
            "severity": "danger" if past else "warn", "link_view": "it",
            "message": f"{r['name']} license expires {r['expiry_date']}",
        }

    # GLASSWARE OVERDUE (open checkout whose due_at is in the past)
    for r in conn.execute(
        """SELECT c.glassware_id, g.name, u.username
           FROM glassware_checkout c
           JOIN glassware_item g ON g.id = c.glassware_id
           LEFT JOIN app_user u ON u.id = c.user_id
           WHERE c.returned_at IS NULL AND c.due_at IS NOT NULL
             AND c.due_at < datetime('now')"""
    ):
        desired[("other", "glassware_item", r["glassware_id"])] = {
            "severity": "warn", "link_view": "glassware",
            "message": f"{r['name']} overdue (held by {r['username'] or 'someone'})",
        }

    # COMPATIBILITY (one notification per conflicting location)
    per_loc = {}
    for c in _compat_conflicts(conn):
        e = per_loc.get(c["location_id"])
        if e is None:
            per_loc[c["location_id"]] = {
                "severity": c["severity"], "path": c["location_path"],
                "pairs": [(c["hazard_a"], c["hazard_b"])],
            }
        else:
            e["pairs"].append((c["hazard_a"], c["hazard_b"]))
            if c["severity"] == "danger":
                e["severity"] = "danger"
    for loc_id, e in per_loc.items():
        if len(e["pairs"]) == 1:
            a, b = e["pairs"][0]
            msg = f"Incompatible storage: {a} + {b} co-located in {e['path']}"
        else:
            msg = f"{len(e['pairs'])} incompatible hazard pairs co-located in {e['path']}"
        desired[("compatibility", "location_node", loc_id)] = {
            "severity": e["severity"], "link_view": "safety", "message": msg,
        }

    # Reconcile against currently-unread broadcasts of the managed kinds.
    placeholders = ",".join("?" for _ in _NOTIFICATION_KINDS)
    existing = {}
    for e in conn.execute(
        f"""SELECT id, kind, entity_type, entity_id FROM notification
            WHERE read_at IS NULL AND user_id IS NULL
              AND kind IN ({placeholders})""",
        _NOTIFICATION_KINDS,
    ):
        # Only rows this function regenerates are eligible for auto-clearing;
        # anything else (e.g. the stocktake's count_session alert) is left alone.
        if (e["kind"], e["entity_type"]) not in _RECONCILED_PAIRS:
            continue
        existing.setdefault((e["kind"], e["entity_type"], e["entity_id"]), []).append(e["id"])

    for key, info in desired.items():
        if key in existing:
            continue
        conn.execute(
            # ON CONFLICT DO NOTHING pairs with the UNIQUE partial index on open
            # broadcasts: if another worker inserted the same alert first, skip it
            # rather than duplicating (or erroring).
            """INSERT INTO notification
                   (created_at, user_id, kind, severity, message,
                    entity_type, entity_id, link_view, read_at)
               VALUES (datetime('now'), NULL, ?, ?, ?, ?, ?, ?, NULL)
               ON CONFLICT DO NOTHING""",
            (key[0], info["severity"], info["message"], key[1], key[2], info["link_view"]),
        )

    for key, ids in existing.items():
        if key not in desired:
            for nid in ids:
                conn.execute(
                    "UPDATE notification SET read_at = datetime('now') WHERE id = ?",
                    (nid,),
                )
    conn.commit()


def _notification_visibility(conn, user):
    """Return (sql_clause, params) selecting notifications this user may see:
    broadcasts for manager+, plus the user's own targeted notifications. Returns
    (None, None) when the user can see nothing."""
    is_manager = auth.ROLE_RANK.get((user or {}).get("role"), -1) >= auth.ROLE_RANK["manager"]
    me = _current_uid(conn, user)
    clauses, params = [], []
    if is_manager:
        clauses.append("user_id IS NULL")
    if me is not None:
        clauses.append("user_id = ?")
        params.append(me)
    if not clauses:
        return None, None
    return "(" + " OR ".join(clauses) + ")", params


@router.get("/notifications")
def list_notifications(user: dict = Depends(auth.current_user),
                       unread_only: bool = Query(False),
                       limit: int = Query(50, ge=1, le=500)):
    conn = get_conn()
    try:
        _sync_notifications(conn)
        vis, params = _notification_visibility(conn, user)
        if vis is None:
            return {"unread_count": 0, "notifications": []}
        unread_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM notification WHERE read_at IS NULL AND {vis}",
            params,
        ).fetchone()["c"]
        where = vis
        if unread_only:
            where += " AND read_at IS NULL"
        rows = _rows(conn.execute(
            f"""SELECT id, created_at, user_id, kind, severity, message,
                       entity_type, entity_id, link_view, read_at
                FROM notification
                WHERE {where}
                ORDER BY (read_at IS NOT NULL), created_at DESC, id DESC
                LIMIT ?""",
            params + [limit],
        ))
        return {"unread_count": unread_count, "notifications": rows}
    finally:
        conn.close()


@router.post("/notifications/{nid}/read")
def mark_notification_read(nid: int, user: dict = Depends(auth.current_user)):
    conn = get_conn()
    try:
        n = conn.execute(
            "SELECT id, user_id FROM notification WHERE id = ?", (nid,)
        ).fetchone()
        if n is None:
            raise HTTPException(status_code=404, detail="notification not found")
        is_manager = auth.ROLE_RANK.get((user or {}).get("role"), -1) >= auth.ROLE_RANK["manager"]
        me = _current_uid(conn, user)
        visible = (n["user_id"] is None and is_manager) or (
            n["user_id"] is not None and n["user_id"] == me
        )
        if not visible:
            raise HTTPException(status_code=403, detail="not your notification")
        conn.execute(
            "UPDATE notification SET read_at = datetime('now') WHERE id = ? AND read_at IS NULL",
            (nid,),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/notifications/read-all")
def mark_all_notifications_read(user: dict = Depends(auth.current_user)):
    conn = get_conn()
    try:
        vis, params = _notification_visibility(conn, user)
        if vis is None:
            return {"ok": True, "marked": 0}
        cur = conn.execute(
            f"UPDATE notification SET read_at = datetime('now') WHERE read_at IS NULL AND {vis}",
            params,
        )
        conn.commit()
        return {"ok": True, "marked": cur.rowcount}
    finally:
        conn.close()


@router.get("/notifications/digest/preview")
def preview_digest(user: dict = Depends(auth.require_role("manager"))):
    """Render the current alert digest (subject + grouped items + counts) without
    sending anything -- powers the in-app 'Email digest' preview. Also reports
    whether email delivery is configured, so the UI can say so."""
    conn = get_conn()
    try:
        digest = notify.build_digest(conn)
    finally:
        conn.close()
    digest["email_configured"] = notify.smtp_configured()
    digest["recipients"] = notify.digest_recipients()
    return digest


@router.post("/notifications/digest/send", dependencies=[Depends(auth.require_role("admin"))])
def send_digest_now(user: dict = Depends(auth.require_role("admin"))):
    """Send the alert digest immediately (a manual/test trigger). Returns what
    happened: sent + recipients on success, or a reason (no-recipients /
    smtp-not-configured / no-open-alerts) so the admin gets clear feedback."""
    conn = get_conn()
    try:
        result = notify.send_digest(conn, force_when_empty=True)
    finally:
        conn.close()
    return {
        "sent": result["sent"],
        "reason": result["reason"],
        "recipients": result["recipients"],
        "total": result["total"],
        "urgent": result["urgent"],
    }


# --------------------------------------------------------------------------- #
# controlled-substance register (running-balance log with witness)
# --------------------------------------------------------------------------- #
@router.get("/controlled")
def controlled_items():
    conn = get_conn()
    try:
        rows = _rows(conn.execute(
            """SELECT item_id, item_name, unit, quantity_on_hand,
                      controlled_schedule, status
               FROM inventory
               WHERE is_controlled = 1
               ORDER BY item_name"""
        ))
        for r in rows:
            r["last_entry"] = conn.execute(
                "SELECT MAX(occurred_at) m FROM controlled_log WHERE item_id = ?",
                (r["item_id"],),
            ).fetchone()["m"]
        return rows
    finally:
        conn.close()


@router.get("/controlled/{item_id}/log")
def controlled_log_list(item_id: int):
    conn = get_conn()
    try:
        item = conn.execute(
            "SELECT item_id, item_name, unit, quantity_on_hand, controlled_schedule, is_controlled "
            "FROM inventory WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        entries = _rows(conn.execute(
            """SELECT id, occurred_at, user_id, username, change, balance_after,
                      reason, witness
               FROM controlled_log WHERE item_id = ?
               ORDER BY occurred_at DESC, id DESC""",
            (item_id,),
        ))
        return {"item": dict(item), "entries": entries}
    finally:
        conn.close()


class ControlledLogBody(BaseModel):
    change: int
    reason: Optional[str] = None
    witness: Optional[str] = None


@router.post("/controlled/{item_id}/log", dependencies=[Depends(auth.require_role("member"))])
def controlled_log_add(item_id: int, body: ControlledLogBody,
                       user: dict = Depends(auth.require_role("member"))):
    if body.change == 0:
        raise HTTPException(status_code=400, detail="change cannot be zero")
    if body.change < 0 and not (body.witness or "").strip():
        raise HTTPException(status_code=400, detail="a witness is required to dispense a controlled substance")
    conn = get_conn()
    try:
        item = conn.execute(
            "SELECT item_id, is_controlled, quantity_on_hand FROM inventory WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        if not item["is_controlled"]:
            raise HTTPException(status_code=400, detail="item is not a controlled substance")
        # Guarded balance change: a dispense can never drive the register negative.
        res = conn.execute(
            "UPDATE inventory SET quantity_on_hand = quantity_on_hand + ? "
            "WHERE item_id = ? AND quantity_on_hand + ? >= 0",
            (body.change, item_id, body.change),
        )
        if res.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=400, detail="insufficient balance on the register")
        # Keep the lot ledger in step with the register. Every other outflow
        # draws lots down FEFO in the same transaction; without this the
        # controlled register and item_lot diverge on every dispense, which then
        # shows up as drift in GET /api/integrity/stock.
        if body.change < 0:
            _draw_down_lots(conn, item_id, -body.change)
        else:
            _open_lot(conn, item_id, body.change, label="controlled receipt")
        balance = conn.execute(
            "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()["quantity_on_hand"]
        uid = _current_uid(conn, user)
        conn.execute(
            """INSERT INTO controlled_log
                   (item_id, occurred_at, user_id, username, change, balance_after,
                    reason, witness)
               VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)""",
            (item_id, uid, user.get("username"), body.change, balance,
             body.reason, body.witness),
        )
        _audit(conn, user, "controlled.log", "inventory", item_id,
               f"{'+' if body.change > 0 else ''}{body.change} -> {balance}"
               + (f" ({body.reason})" if body.reason else ""))
        conn.commit()
        return {"ok": True, "balance_after": balance}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# cost-per-task analytics
# --------------------------------------------------------------------------- #
@router.get("/analytics/cost-by-task")
def cost_by_task():
    conn = get_conn()
    try:
        by_task = _rows(conn.execute(
            """SELECT COALESCE(t.task, '(unspecified)') AS task,
                      COUNT(DISTINCT t.id) AS tickets,
                      COALESCE(SUM(tl.quantity), 0) AS total_qty,
                      COALESCE(SUM(tl.quantity * i.unit_cost), 0) AS total_cost
               FROM ticket t
               JOIN ticket_line tl ON tl.ticket_id = t.id
               JOIN inventory i ON i.item_id = tl.item_id
               GROUP BY t.task
               ORDER BY total_cost DESC"""
        ))
        by_purpose = _rows(conn.execute(
            """SELECT COALESCE(t.purpose, '(unspecified)') AS purpose,
                      COUNT(DISTINCT t.id) AS tickets,
                      COALESCE(SUM(tl.quantity * i.unit_cost), 0) AS total_cost
               FROM ticket t
               JOIN ticket_line tl ON tl.ticket_id = t.id
               JOIN inventory i ON i.item_id = tl.item_id
               GROUP BY t.purpose
               ORDER BY total_cost DESC"""
        ))
        for r in by_task:
            r["avg_cost"] = round(r["total_cost"] / r["tickets"], 2) if r["tickets"] else 0
        return {"by_task": by_task, "by_purpose": by_purpose}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# global search
# --------------------------------------------------------------------------- #
@router.get("/search")
def search(q: str = Query(..., min_length=1), user: dict = Depends(auth.current_user)):
    term = q.strip()
    if not term:
        return {"items": [], "locations": [], "tickets": [],
                "equipment": [], "funds": [], "kits": []}
    like = f"%{term}%"
    conn = get_conn()
    try:
        items = _rows(conn.execute(
            """SELECT item_id, item_name, vendor, category, status
               FROM inventory
               WHERE item_name LIKE ? OR vendor LIKE ? OR category LIKE ?
               ORDER BY (status='deprecated'), item_name
               LIMIT 8""",
            (like, like, like),
        ))
        locations = _rows(conn.execute(
            """SELECT id, name, kind FROM location_node
               WHERE name LIKE ? OR kind LIKE ?
               ORDER BY name LIMIT 8""",
            (like, like),
        ))
        tickets = []
        if _can_see_all_usage(conn, user):
            tickets = _rows(conn.execute(
                """SELECT t.id, t.ticket_date, t.task, t.purpose, u.username
                   FROM ticket t LEFT JOIN app_user u ON u.id = t.user_id
                   WHERE t.task LIKE ? OR t.purpose LIKE ?
                   ORDER BY t.ticket_date DESC LIMIT 8""",
                (like, like),
            ))
        equipment = _rows(conn.execute(
            """SELECT id, name, category, make_model FROM equipment
               WHERE name LIKE ? OR make_model LIKE ? OR serial_number LIKE ?
               ORDER BY name LIMIT 8""",
            (like, like, like),
        ))
        funds = []
        if _can_see_all_usage(conn, user):
            funds = _rows(conn.execute(
                """SELECT id, name, sponsor FROM fund
                   WHERE name LIKE ? OR sponsor LIKE ?
                   ORDER BY name LIMIT 8""",
                (like, like),
            ))
        kits = _rows(conn.execute(
            """SELECT id, name FROM kit
               WHERE name LIKE ?
               ORDER BY name LIMIT 8""",
            (like,),
        ))
        return {"items": items, "locations": locations, "tickets": tickets,
                "equipment": equipment, "funds": funds, "kits": kits}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# QR labels (printable deep links; a phone camera opens the item)
# --------------------------------------------------------------------------- #
@router.get("/items/{item_id}/qr.svg")
def item_qr(item_id: int, request: Request):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT item_id FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="item not found")
    finally:
        conn.close()
    # Deep link back into the SPA; a phone camera scanning this opens the app on
    # this item. app.js reads ?item= on boot and focuses it in the Inventory view.
    base = str(request.base_url).rstrip("/")
    url = f"{base}/?item={item_id}"
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=4, border=2,
                                    dark="#000000", light="#ffffff")
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


# =========================================================================== #
# WAVE 2: user management, vendor catalog, substitute groups, documents,
# purchase-order approval/receiving, reorder suggestions, location contents.
# =========================================================================== #

# --------------------------------------------------------------------------- #
# user management (admin only)
# --------------------------------------------------------------------------- #
_USER_ROLES = {"viewer", "member", "manager", "admin"}


def _user_public(conn, user_id):
    row = conn.execute(
        """SELECT id, username, full_name, role, is_active, staff_id, created_at
           FROM app_user WHERE id = ?""",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def _active_admin_count(conn, exclude_id=None):
    if exclude_id is None:
        return conn.execute(
            "SELECT COUNT(*) c FROM app_user WHERE role = 'admin' AND is_active = 1"
        ).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) c FROM app_user WHERE role = 'admin' AND is_active = 1 AND id <> ?",
        (exclude_id,),
    ).fetchone()["c"]


@router.get("/users", dependencies=[Depends(auth.require_role("admin"))])
def list_users():
    conn = get_conn()
    try:
        return _rows(conn.execute(
            """SELECT id, username, full_name, role, is_active, staff_id, created_at
               FROM app_user ORDER BY username"""
        ))
    finally:
        conn.close()


class UserCreateBody(BaseModel):
    username: str
    full_name: str
    role: str
    password: str


@router.post("/users", dependencies=[Depends(auth.require_role("admin"))])
def create_user_endpoint(body: UserCreateBody,
                         user: dict = Depends(auth.require_role("admin"))):
    username = (body.username or "").strip()
    full_name = (body.full_name or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if body.role not in _USER_ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role: {body.role}")
    _require_password(body.password)
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT 1 FROM app_user WHERE username = ?", (username,)
        ).fetchone():
            raise HTTPException(status_code=409, detail="username already exists")
        uid = auth.create_user(conn, username, body.password, body.role,
                               full_name or username)
        _audit(conn, user, "user.create", "app_user", uid, username)
        conn.commit()
        return _user_public(conn, uid)
    finally:
        conn.close()


@router.patch("/users/{user_id}", dependencies=[Depends(auth.require_role("admin"))])
def update_user_endpoint(user_id: int, payload: dict = Body(...),
                         user: dict = Depends(auth.require_role("admin"))):
    fields = {}
    if "full_name" in payload:
        full_name = str(payload["full_name"] or "").strip()
        if not full_name:
            raise HTTPException(status_code=400, detail="full_name cannot be empty")
        fields["full_name"] = full_name
    if "role" in payload:
        if payload["role"] not in _USER_ROLES:
            raise HTTPException(status_code=400, detail=f"unknown role: {payload['role']}")
        fields["role"] = payload["role"]
    if "is_active" in payload:
        fields["is_active"] = 1 if payload["is_active"] else 0
    if not fields:
        raise HTTPException(status_code=400, detail="no updatable fields provided")
    conn = get_conn()
    try:
        target = conn.execute(
            "SELECT id, username, role, is_active FROM app_user WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")

        deactivating = fields.get("is_active") == 0 and target["is_active"] == 1
        demoting = "role" in fields and fields["role"] != "admin" and target["role"] == "admin"

        my_uid = _current_uid(conn, user)
        if (deactivating or demoting) and my_uid == user_id:
            raise HTTPException(status_code=400,
                                detail="you cannot deactivate or demote your own account")
        if (deactivating or demoting) and target["role"] == "admin" \
                and _active_admin_count(conn, exclude_id=user_id) == 0:
            raise HTTPException(status_code=400,
                                detail="cannot deactivate or demote the last active admin")

        set_sql = ", ".join(f"{col} = ?" for col in fields)  # whitelisted names
        conn.execute(
            f"UPDATE app_user SET {set_sql} WHERE id = ?",
            (*fields.values(), user_id),
        )
        _audit(conn, user, "user.update", "app_user", user_id,
               f"{target['username']}: {', '.join(sorted(fields))}")
        conn.commit()
        return _user_public(conn, user_id)
    finally:
        conn.close()


class PasswordBody(BaseModel):
    password: str


@router.post("/users/{user_id}/password", dependencies=[Depends(auth.require_role("admin"))])
def reset_user_password(user_id: int, body: PasswordBody,
                        user: dict = Depends(auth.require_role("admin"))):
    _require_password(body.password)
    conn = get_conn()
    try:
        target = conn.execute(
            "SELECT id, username FROM app_user WHERE id = ?", (user_id,)
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        salt, pw_hash, iterations = auth.hash_password(body.password)
        conn.execute(
            """UPDATE app_user
               SET password_hash = ?, password_salt = ?, iterations = ?
               WHERE id = ?""",
            (pw_hash, salt, iterations, user_id),
        )
        _audit(conn, user, "user.password_reset", "app_user", user_id,
               target["username"])
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.delete("/users/{user_id}", dependencies=[Depends(auth.require_role("admin"))])
def delete_user_endpoint(user_id: int, user: dict = Depends(auth.require_role("admin"))):
    conn = get_conn()
    try:
        target = conn.execute(
            "SELECT id, username, role, is_active FROM app_user WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        if _current_uid(conn, user) == user_id:
            raise HTTPException(status_code=400,
                                detail="you cannot delete your own account")
        if target["role"] == "admin" and target["is_active"] \
                and _active_admin_count(conn, exclude_id=user_id) == 0:
            raise HTTPException(status_code=400,
                                detail="cannot delete the last active admin")
        conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM app_user WHERE id = ?", (user_id,))
        _audit(conn, user, "user.delete", "app_user", user_id, target["username"])
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# vendor catalog
# --------------------------------------------------------------------------- #
_CATALOG_COLS = (
    "id", "vendor", "catalog_number", "product_name", "category", "pack_size",
    "unit", "list_price", "sds_url", "product_url", "cas_number", "hazard_class",
    "substitute_group_id", "preference_rank", "availability",
)
_CATALOG_WRITE_COLS = tuple(c for c in _CATALOG_COLS if c != "id")
_AVAILABILITY = {"in_stock", "backorder", "discontinued"}


def _catalog_row(conn, catalog_id):
    row = conn.execute(
        f"SELECT {', '.join(_CATALOG_COLS)} FROM vendor_catalog WHERE id = ?",
        (catalog_id,),
    ).fetchone()
    return dict(row) if row else None


@router.get("/catalog")
def list_catalog(q: Optional[str] = None, category: Optional[str] = None,
                 vendor: Optional[str] = None, group: Optional[int] = None,
                 availability: Optional[str] = None):
    conn = get_conn()
    try:
        clauses, params = [], []
        if q:
            like = f"%{q.strip()}%"
            clauses.append("(c.product_name LIKE ? OR c.catalog_number LIKE ? OR c.vendor LIKE ?)")
            params += [like, like, like]
        if category:
            clauses.append("c.category = ?")
            params.append(category)
        if vendor:
            clauses.append("c.vendor = ?")
            params.append(vendor)
        if group is not None:
            clauses.append("c.substitute_group_id = ?")
            params.append(group)
        if availability:
            clauses.append("c.availability = ?")
            params.append(availability)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cols = ", ".join(f"c.{col}" for col in _CATALOG_COLS)
        return _rows(conn.execute(
            f"""SELECT {cols}, g.name AS group_name
                FROM vendor_catalog c
                LEFT JOIN substitute_group g ON g.id = c.substitute_group_id
                {where}
                ORDER BY c.product_name""",
            tuple(params),
        ))
    finally:
        conn.close()


@router.get("/catalog/vendors")
def catalog_vendors():
    conn = get_conn()
    try:
        return _rows(conn.execute(
            """SELECT vendor, COUNT(*) AS count FROM vendor_catalog
               GROUP BY vendor ORDER BY vendor"""
        ))
    finally:
        conn.close()


@router.get("/catalog/{catalog_id}")
def catalog_detail(catalog_id: int):
    conn = get_conn()
    try:
        cols = ", ".join(f"c.{col}" for col in _CATALOG_COLS)
        row = conn.execute(
            f"""SELECT {cols}, g.name AS group_name
                FROM vendor_catalog c
                LEFT JOIN substitute_group g ON g.id = c.substitute_group_id
                WHERE c.id = ?""",
            (catalog_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="catalog item not found")
        row = dict(row)
        siblings = []
        if row["substitute_group_id"] is not None:
            siblings = _rows(conn.execute(
                f"""SELECT {', '.join(_CATALOG_COLS)} FROM vendor_catalog
                    WHERE substitute_group_id = ? AND id <> ?
                    ORDER BY (preference_rank IS NULL), preference_rank, list_price""",
                (row["substitute_group_id"], catalog_id),
            ))
        row["siblings"] = siblings
        return row
    finally:
        conn.close()


@router.post("/catalog", dependencies=[Depends(auth.require_role("manager"))])
def create_catalog(payload: dict = Body(...),
                   user: dict = Depends(auth.require_role("manager"))):
    for req in ("vendor", "catalog_number", "product_name"):
        if not str(payload.get(req) or "").strip():
            raise HTTPException(status_code=400, detail=f"{req} is required")
    availability = payload.get("availability") or "in_stock"
    if availability not in _AVAILABILITY:
        raise HTTPException(status_code=400, detail=f"invalid availability: {availability}")
    payload["availability"] = availability
    payload.setdefault("category", "other")
    conn = get_conn()
    try:
        values = [payload.get(col) for col in _CATALOG_WRITE_COLS]
        placeholders = ", ".join("?" for _ in _CATALOG_WRITE_COLS)
        cur = conn.execute(
            f"""INSERT INTO vendor_catalog ({', '.join(_CATALOG_WRITE_COLS)})
                VALUES ({placeholders})""",
            tuple(values),
        )
        cat_id = cur.lastrowid
        _audit(conn, user, "catalog.create", "vendor_catalog", cat_id,
               str(payload.get("product_name")))
        conn.commit()
        return _catalog_row(conn, cat_id)
    finally:
        conn.close()


@router.patch("/catalog/{catalog_id}", dependencies=[Depends(auth.require_role("manager"))])
def update_catalog(catalog_id: int, payload: dict = Body(...),
                   user: dict = Depends(auth.require_role("manager"))):
    fields = {k: payload[k] for k in _CATALOG_WRITE_COLS if k in payload}
    if not fields:
        raise HTTPException(status_code=400, detail="no updatable fields provided")
    if "availability" in fields and fields["availability"] not in _AVAILABILITY:
        raise HTTPException(status_code=400,
                            detail=f"invalid availability: {fields['availability']}")
    conn = get_conn()
    try:
        if _catalog_row(conn, catalog_id) is None:
            raise HTTPException(status_code=404, detail="catalog item not found")
        set_sql = ", ".join(f"{col} = ?" for col in fields)  # whitelisted names
        conn.execute(
            f"UPDATE vendor_catalog SET {set_sql} WHERE id = ?",
            (*fields.values(), catalog_id),
        )
        _audit(conn, user, "catalog.update", "vendor_catalog", catalog_id,
               ", ".join(sorted(fields)))
        conn.commit()
        return _catalog_row(conn, catalog_id)
    finally:
        conn.close()


class AddToInventoryBody(BaseModel):
    quantity: int = 0
    reorder_threshold: int = 0
    reorder_max: Optional[int] = None


@router.post("/catalog/{catalog_id}/add-to-inventory",
             dependencies=[Depends(auth.require_role("manager"))])
def catalog_add_to_inventory(catalog_id: int, body: AddToInventoryBody,
                             user: dict = Depends(auth.require_role("manager"))):
    if body.quantity < 0 or body.reorder_threshold < 0:
        raise HTTPException(status_code=400, detail="quantities cannot be negative")
    conn = get_conn()
    try:
        cat = _catalog_row(conn, catalog_id)
        if cat is None:
            raise HTTPException(status_code=404, detail="catalog item not found")
        cur = conn.execute(
            """INSERT INTO inventory
                   (item_name, vendor, unit, quantity_on_hand, reorder_threshold,
                    unit_cost, category, sds_url, disposal_instructions, status,
                    is_controlled, controlled_schedule,
                    reorder_max, hazard_class, cas_number, catalog_id, pack_size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', 0, NULL, ?, ?, ?, ?, ?)""",
            (cat["product_name"], cat["vendor"], cat["unit"], body.quantity,
             body.reorder_threshold, cat["list_price"] or 0, cat["category"],
             cat["sds_url"], body.reorder_max, cat["hazard_class"],
             cat["cas_number"], catalog_id, cat.get("pack_size")),
        )
        item_id = cur.lastrowid
        if body.quantity > 0:
            conn.execute(
                """INSERT INTO usage_event
                       (item_id, container_id, staff_id, event_type, quantity,
                        occurred_at, note)
                   VALUES (?, NULL, NULL, 'restock', ?, datetime('now'),
                           'opening balance from catalog')""",
                (item_id, body.quantity),
            )
        _audit(conn, user, "item.create", "inventory", item_id,
               f"{cat['product_name']} (from catalog #{catalog_id})")
        conn.commit()
        return dict(conn.execute(
            "SELECT * FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone())
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# substitute groups
# --------------------------------------------------------------------------- #
def _preferred_in_stock_member(conn, group_id):
    row = conn.execute(
        """SELECT id, vendor, product_name, list_price FROM vendor_catalog
           WHERE substitute_group_id = ? AND availability = 'in_stock'
           ORDER BY (preference_rank IS NULL), preference_rank, list_price
           LIMIT 1""",
        (group_id,),
    ).fetchone()
    return dict(row) if row else None


@router.get("/substitute-groups")
def list_substitute_groups():
    conn = get_conn()
    try:
        groups = _rows(conn.execute(
            "SELECT id, name, category, description FROM substitute_group ORDER BY name"
        ))
        for g in groups:
            g["member_count"] = conn.execute(
                "SELECT COUNT(*) c FROM vendor_catalog WHERE substitute_group_id = ?",
                (g["id"],),
            ).fetchone()["c"]
            g["in_stock_count"] = conn.execute(
                """SELECT COUNT(*) c FROM vendor_catalog
                   WHERE substitute_group_id = ? AND availability = 'in_stock'""",
                (g["id"],),
            ).fetchone()["c"]
            pref = _preferred_in_stock_member(conn, g["id"])
            g["preferred"] = (
                {"catalog_id": pref["id"], "vendor": pref["vendor"],
                 "product_name": pref["product_name"], "list_price": pref["list_price"]}
                if pref else None
            )
        return groups
    finally:
        conn.close()


@router.get("/substitute-groups/{group_id}")
def substitute_group_detail(group_id: int):
    conn = get_conn()
    try:
        g = conn.execute(
            "SELECT id, name, category, description FROM substitute_group WHERE id = ?",
            (group_id,),
        ).fetchone()
        if g is None:
            raise HTTPException(status_code=404, detail="substitute group not found")
        g = dict(g)
        g["members"] = _rows(conn.execute(
            f"""SELECT {', '.join(_CATALOG_COLS)} FROM vendor_catalog
                WHERE substitute_group_id = ?
                ORDER BY (preference_rank IS NULL), preference_rank, list_price""",
            (group_id,),
        ))
        pref = _preferred_in_stock_member(conn, group_id)
        g["preferred_catalog_id"] = pref["id"] if pref else None
        return g
    finally:
        conn.close()


@router.post("/substitute-groups", dependencies=[Depends(auth.require_role("manager"))])
def create_substitute_group(payload: dict = Body(...),
                            user: dict = Depends(auth.require_role("manager"))):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT 1 FROM substitute_group WHERE name = ?", (name,)
        ).fetchone():
            raise HTTPException(status_code=400, detail="a group with that name exists")
        cur = conn.execute(
            "INSERT INTO substitute_group (name, category, description) VALUES (?, ?, ?)",
            (name, payload.get("category"), payload.get("description")),
        )
        gid = cur.lastrowid
        _audit(conn, user, "substitute.create", "substitute_group", gid, name)
        conn.commit()
        return dict(conn.execute(
            "SELECT id, name, category, description FROM substitute_group WHERE id = ?",
            (gid,),
        ).fetchone())
    finally:
        conn.close()


@router.patch("/substitute-groups/{group_id}", dependencies=[Depends(auth.require_role("manager"))])
def update_substitute_group(group_id: int, payload: dict = Body(...),
                            user: dict = Depends(auth.require_role("manager"))):
    fields = {}
    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        fields["name"] = name
    for key in ("category", "description"):
        if key in payload:
            fields[key] = payload[key]
    if not fields:
        raise HTTPException(status_code=400, detail="no updatable fields provided")
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT 1 FROM substitute_group WHERE id = ?", (group_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="substitute group not found")
        if "name" in fields and conn.execute(
            "SELECT 1 FROM substitute_group WHERE name = ? AND id <> ?",
            (fields["name"], group_id),
        ).fetchone():
            raise HTTPException(status_code=400, detail="a group with that name exists")
        set_sql = ", ".join(f"{col} = ?" for col in fields)  # whitelisted names
        conn.execute(
            f"UPDATE substitute_group SET {set_sql} WHERE id = ?",
            (*fields.values(), group_id),
        )
        _audit(conn, user, "substitute.update", "substitute_group", group_id,
               ", ".join(sorted(fields)))
        conn.commit()
        return dict(conn.execute(
            "SELECT id, name, category, description FROM substitute_group WHERE id = ?",
            (group_id,),
        ).fetchone())
    finally:
        conn.close()


@router.delete("/substitute-groups/{group_id}", dependencies=[Depends(auth.require_role("manager"))])
def delete_substitute_group(group_id: int,
                            user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        g = conn.execute(
            "SELECT name FROM substitute_group WHERE id = ?", (group_id,)
        ).fetchone()
        if g is None:
            raise HTTPException(status_code=404, detail="substitute group not found")
        conn.execute(
            "UPDATE vendor_catalog SET substitute_group_id = NULL WHERE substitute_group_id = ?",
            (group_id,),
        )
        conn.execute("DELETE FROM substitute_group WHERE id = ?", (group_id,))
        _audit(conn, user, "substitute.delete", "substitute_group", group_id, g["name"])
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/substitute-groups/{group_id}/members",
             dependencies=[Depends(auth.require_role("manager"))])
def add_substitute_member(group_id: int, payload: dict = Body(...),
                          user: dict = Depends(auth.require_role("manager"))):
    catalog_id = payload.get("catalog_id")
    if catalog_id is None:
        raise HTTPException(status_code=400, detail="catalog_id is required")
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT 1 FROM substitute_group WHERE id = ?", (group_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="substitute group not found")
        if _catalog_row(conn, catalog_id) is None:
            raise HTTPException(status_code=400, detail="catalog item not found")
        conn.execute(
            "UPDATE vendor_catalog SET substitute_group_id = ?, preference_rank = ? WHERE id = ?",
            (group_id, payload.get("preference_rank"), catalog_id),
        )
        _audit(conn, user, "substitute.update", "substitute_group", group_id,
               f"add catalog #{catalog_id}")
        conn.commit()
        return substitute_group_detail(group_id)
    finally:
        conn.close()


@router.delete("/substitute-groups/{group_id}/members/{catalog_id}",
               dependencies=[Depends(auth.require_role("manager"))])
def remove_substitute_member(group_id: int, catalog_id: int,
                             user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT 1 FROM substitute_group WHERE id = ?", (group_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="substitute group not found")
        conn.execute(
            "UPDATE vendor_catalog SET substitute_group_id = NULL WHERE id = ? AND substitute_group_id = ?",
            (catalog_id, group_id),
        )
        _audit(conn, user, "substitute.update", "substitute_group", group_id,
               f"remove catalog #{catalog_id}")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# document attachments
# --------------------------------------------------------------------------- #
def _doc_target(item_id, lot_id, po_id):
    """Return (col, id) for the single provided target, or raise 400."""
    provided = [(c, v) for c, v in
                (("item_id", item_id), ("lot_id", lot_id), ("po_id", po_id))
                if v is not None]
    if len(provided) != 1:
        raise HTTPException(
            status_code=400,
            detail="exactly one of item_id / lot_id / po_id must be provided",
        )
    return provided[0]


def _doc_target_exists(conn, col, target_id):
    table_key = {"item_id": ("inventory", "item_id"),
                 "lot_id": ("item_lot", "id"),
                 "po_id": ("purchase_order", "id")}[col]
    table, pk = table_key
    return conn.execute(
        f"SELECT 1 FROM {table} WHERE {pk} = ?", (target_id,)
    ).fetchone() is not None


def _doc_public(conn, doc_id):
    row = conn.execute(
        f"SELECT {', '.join(_DOC_COLS)} FROM item_document WHERE id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["href"] = _doc_href(d)
    return d


@router.get("/documents")
def list_documents(item_id: Optional[int] = None, lot_id: Optional[int] = None,
                   po_id: Optional[int] = None):
    col, target_id = _doc_target(item_id, lot_id, po_id)
    conn = get_conn()
    try:
        return _documents_for(conn, col, target_id)
    finally:
        conn.close()


@router.post("/documents", dependencies=[Depends(auth.require_role("member"))])
def add_document(payload: dict = Body(...),
                 user: dict = Depends(auth.require_role("member"))):
    col, target_id = _doc_target(payload.get("item_id"), payload.get("lot_id"),
                                 payload.get("po_id"))
    kind = payload.get("kind")
    if kind not in _DOC_KINDS:
        raise HTTPException(status_code=400, detail=f"invalid kind: {kind}")
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    conn = get_conn()
    try:
        if not _doc_target_exists(conn, col, target_id):
            raise HTTPException(status_code=400, detail="target not found")
        uid = _current_uid(conn, user)
        cur = conn.execute(
            f"""INSERT INTO item_document
                    ({col}, kind, label, url, filename, uploaded_at, uploaded_by)
                VALUES (?, ?, ?, ?, NULL, datetime('now'), ?)""",
            (target_id, kind, payload.get("label"), url, uid),
        )
        doc_id = cur.lastrowid
        _audit(conn, user, "document.add", "item_document", doc_id,
               f"{kind} ({col} {target_id})")
        conn.commit()
        return _doc_public(conn, doc_id)
    finally:
        conn.close()


@router.post("/documents/upload", dependencies=[Depends(auth.require_role("member"))])
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form(...),
    label: Optional[str] = Form(None),
    item_id: Optional[int] = Form(None),
    lot_id: Optional[int] = Form(None),
    po_id: Optional[int] = Form(None),
    user: dict = Depends(auth.require_role("member")),
):
    col, target_id = _doc_target(item_id, lot_id, po_id)
    if kind not in _DOC_KINDS:
        raise HTTPException(status_code=400, detail=f"invalid kind: {kind}")

    original = os.path.basename(file.filename or "")
    stem, dot, ext = original.rpartition(".")
    ext = ext.lower()
    if not dot or ext not in _DOC_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"extension must be one of: {', '.join(sorted(_DOC_EXTS))}",
        )
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:60] or "doc"
    filename = f"{_secrets.token_hex(8)}_{safe_stem}.{ext}"

    data = await file.read(_DOC_MAX_BYTES + 1)
    if len(data) > _DOC_MAX_BYTES:
        raise HTTPException(status_code=400, detail="file exceeds 20MB limit")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    conn = get_conn()
    try:
        if not _doc_target_exists(conn, col, target_id):
            raise HTTPException(status_code=400, detail="target not found")
        os.makedirs(_DOC_UPLOAD_DIR, exist_ok=True)
        dest = os.path.join(_DOC_UPLOAD_DIR, filename)
        if os.path.dirname(os.path.abspath(dest)) != os.path.abspath(_DOC_UPLOAD_DIR):
            raise HTTPException(status_code=400, detail="invalid filename")
        with open(dest, "wb") as fh:
            fh.write(data)
        uid = _current_uid(conn, user)
        cur = conn.execute(
            f"""INSERT INTO item_document
                    ({col}, kind, label, url, filename, uploaded_at, uploaded_by)
                VALUES (?, ?, ?, NULL, ?, datetime('now'), ?)""",
            (target_id, kind, label, filename, uid),
        )
        doc_id = cur.lastrowid
        _audit(conn, user, "document.add", "item_document", doc_id,
               f"{kind} upload ({col} {target_id})")
        conn.commit()
        return _doc_public(conn, doc_id)
    finally:
        conn.close()


@router.delete("/documents/{doc_id}", dependencies=[Depends(auth.require_role("manager"))])
def delete_document(doc_id: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, kind, filename FROM item_document WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="document not found")
        conn.execute("DELETE FROM item_document WHERE id = ?", (doc_id,))
        _audit(conn, user, "document.delete", "item_document", doc_id, row["kind"])
        conn.commit()
        _unlink_doc_file(row["filename"])
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# purchase-order partial receiving + auto-draft
# --------------------------------------------------------------------------- #
def _receive_po_line(conn, po_id, line, qty):
    """Restock one line by qty: bump received_qty, create a lot, book restock."""
    conn.execute(
        """INSERT INTO item_lot (item_id, lot_number, expiry_date, quantity,
                                 received_date, coa_url)
           VALUES (?, ?, NULL, ?, date('now'), NULL)""",
        (line["item_id"], f"PO-{po_id}", qty),
    )
    conn.execute(
        "UPDATE inventory SET quantity_on_hand = quantity_on_hand + ? WHERE item_id = ?",
        (qty, line["item_id"]),
    )
    conn.execute(
        """INSERT INTO usage_event
               (item_id, container_id, staff_id, event_type, quantity,
                occurred_at, note)
           VALUES (?, NULL, NULL, 'restock', ?, datetime('now'), ?)""",
        (line["item_id"], qty, f"received PO-{po_id}"),
    )
    conn.execute(
        "UPDATE po_line SET received_qty = received_qty + ? WHERE id = ?",
        (qty, line["id"]),
    )


@router.post("/purchase-orders/{po_id}/receive",
             dependencies=[Depends(auth.require_role("manager"))])
def receive_purchase_order(po_id: int, payload: dict = Body(...),
                           user: dict = Depends(auth.require_role("manager"))):
    receipts = payload.get("receipts") or []
    if not receipts:
        raise HTTPException(status_code=400, detail="no receipts provided")
    conn = get_conn()
    try:
        po = conn.execute(
            "SELECT id, status FROM purchase_order WHERE id = ?", (po_id,)
        ).fetchone()
        if po is None:
            raise HTTPException(status_code=404, detail="purchase order not found")
        if po["status"] in _PO_TERMINAL:
            raise HTTPException(status_code=400,
                                detail=f"cannot receive a {po['status']} purchase order")
        total_received = 0
        for rec in receipts:
            line_id = rec.get("line_id") if isinstance(rec, dict) else None
            qty = rec.get("qty") if isinstance(rec, dict) else None
            if line_id is None or qty is None:
                raise HTTPException(status_code=400, detail="each receipt needs line_id and qty")
            # Coerce explicitly: a string/list/float qty otherwise reached the
            # comparison below (TypeError -> 500) or was written straight into an
            # INTEGER column as a float.
            try:
                line_id = int(line_id)
                qty = int(qty)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail="line_id and qty must be whole numbers"
                ) from None
            line = conn.execute(
                "SELECT id, item_id, quantity, received_qty FROM po_line WHERE id = ? AND po_id = ?",
                (line_id, po_id),
            ).fetchone()
            if line is None:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"unknown line_id {line_id}")
            outstanding = line["quantity"] - line["received_qty"]
            if not (0 < qty <= outstanding):
                conn.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"qty for line {line_id} must be between 1 and {outstanding}",
                )
            _receive_po_line(conn, po_id, line, qty)
            total_received += qty

        remaining = conn.execute(
            "SELECT COALESCE(SUM(quantity - received_qty), 0) AS r FROM po_line WHERE po_id = ?",
            (po_id,),
        ).fetchone()["r"]
        if remaining == 0:
            conn.execute(
                "UPDATE purchase_order SET status = 'received', received_at = datetime('now') WHERE id = ?",
                (po_id,),
            )
            _charge_fund_on_receipt(conn, po_id, user)
        _audit(conn, user, "po.receive", "purchase_order", po_id,
               f"received {total_received} unit(s)")
        conn.commit()
        return _po_detail(conn, po_id)
    finally:
        conn.close()


def _suggested_qty(item):
    target = max(item["reorder_max"] or 0, item["reorder_threshold"] + 1)
    return max(target - item["quantity_on_hand"], 1)


def _reorder_source(conn, item):
    """Resolve vendor + unit cost for reordering an item.

    Priority: the item's linked catalog product; if that product is backordered
    or discontinued and belongs to a substitute group, fall through to the
    group's preferred in-stock member. Otherwise the item's own vendor/cost.
    Also surfaces preferred_vendor/preferred_price for display.
    """
    vendor = item["vendor"]
    unit_cost = item["unit_cost"] or 0
    catalog_id = item["catalog_id"]
    preferred_vendor = None
    preferred_price = None
    if catalog_id:
        cat = conn.execute(
            """SELECT vendor, list_price, substitute_group_id, availability
               FROM vendor_catalog WHERE id = ?""",
            (catalog_id,),
        ).fetchone()
        if cat is not None:
            vendor = cat["vendor"]
            if cat["list_price"] is not None:
                unit_cost = cat["list_price"]
            if cat["substitute_group_id"] is not None:
                pref = _preferred_in_stock_member(conn, cat["substitute_group_id"])
                if pref is not None:
                    preferred_vendor = pref["vendor"]
                    preferred_price = pref["list_price"]
                    if cat["availability"] != "in_stock":
                        vendor = pref["vendor"]
                        if pref["list_price"] is not None:
                            unit_cost = pref["list_price"]
    return {
        "vendor": vendor,
        "unit_cost": unit_cost or 0,
        "preferred_vendor": preferred_vendor,
        "preferred_price": preferred_price,
    }


@router.get("/reorder/suggestions")
def reorder_suggestions():
    conn = get_conn()
    try:
        items = _rows(conn.execute(
            """SELECT item_id, item_name, vendor, quantity_on_hand,
                      reorder_threshold, reorder_max, unit_cost, catalog_id
               FROM inventory
               WHERE status = 'active' AND quantity_on_hand <= reorder_threshold
               ORDER BY (quantity_on_hand - reorder_threshold), item_name"""
        ))
        out = []
        for it in items:
            src = _reorder_source(conn, it)
            out.append({
                "item_id": it["item_id"],
                "item_name": it["item_name"],
                "vendor": src["vendor"],
                "quantity_on_hand": it["quantity_on_hand"],
                "reorder_threshold": it["reorder_threshold"],
                "reorder_max": it["reorder_max"],
                "suggested_qty": _suggested_qty(it),
                "unit_cost": src["unit_cost"],
                "catalog_id": it["catalog_id"],
                "preferred_vendor": src["preferred_vendor"],
                "preferred_price": src["preferred_price"],
            })
        return out
    finally:
        conn.close()


@router.post("/purchase-orders/auto", dependencies=[Depends(auth.require_role("manager"))])
def auto_purchase_order(user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        items = _rows(conn.execute(
            """SELECT item_id, item_name, vendor, quantity_on_hand,
                      reorder_threshold, reorder_max, unit_cost, catalog_id
               FROM inventory
               WHERE status = 'active' AND quantity_on_hand <= reorder_threshold
               ORDER BY item_name"""
        ))
        if not items:
            return {"created": False, "reason": "nothing below reorder point"}

        lines = []
        vendors = set()
        for it in items:
            src = _reorder_source(conn, it)
            qty = _suggested_qty(it)
            lines.append((it["item_id"], qty, src["unit_cost"], src["vendor"]))
            vendors.add(src["vendor"])
        vendor = vendors.pop() if len(vendors) == 1 else "Auto (mixed)"

        uid = _current_uid(conn, user)
        cur = conn.execute(
            """INSERT INTO purchase_order (vendor, status, created_by, created_at, note)
               VALUES (?, 'draft', ?, datetime('now'), ?)""",
            (vendor, uid, "auto-generated from low stock"),
        )
        po_id = cur.lastrowid
        for item_id, qty, unit_cost, _v in lines:
            conn.execute(
                "INSERT INTO po_line (po_id, item_id, quantity, unit_cost) VALUES (?, ?, ?, ?)",
                (po_id, item_id, qty, unit_cost),
            )
        _audit(conn, user, "po.create", "purchase_order", po_id,
               f"auto-generated from {len(lines)} low-stock items")
        conn.commit()
        return {"created": True, "po": _po_detail(conn, po_id)}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# location contents (everything stored at or under a node)
# --------------------------------------------------------------------------- #
@router.get("/locations/{node_id}/contents")
def location_contents(node_id: int):
    conn = get_conn()
    try:
        node = conn.execute(
            "SELECT id, name, kind FROM location_node WHERE id = ?", (node_id,)
        ).fetchone()
        if node is None:
            raise HTTPException(status_code=404, detail="location not found")
        containers = _rows(conn.execute(
            """WITH RECURSIVE subtree(id) AS (
                   SELECT id FROM location_node WHERE id = ?
                   UNION ALL
                   SELECT n.id FROM location_node n
                   JOIN subtree s ON n.parent_id = s.id
               )
               SELECT c.id, i.item_id, i.item_name, l.lot_number,
                      c.box_id, b.name AS box_name, c.row, c.col, c.status,
                      i.hazard_class
               FROM container c
               JOIN item_lot l ON l.id = c.item_lot_id
               JOIN inventory i ON i.item_id = l.item_id
               LEFT JOIN location_node b ON b.id = c.box_id
               WHERE c.box_id IN (SELECT id FROM subtree)
               ORDER BY i.item_name, c.id""",
            (node_id,),
        ))
        # union of hazard keywords present across the returned containers
        hazards = set()
        for c in containers:
            hazards |= _parse_hazards(c.get("hazard_class"))
        # descendant set (this node + subtree) to filter compat conflicts
        subtree_ids = {
            r["id"] for r in conn.execute(
                """WITH RECURSIVE subtree(id) AS (
                       SELECT id FROM location_node WHERE id = ?
                       UNION ALL
                       SELECT n.id FROM location_node n
                       JOIN subtree s ON n.parent_id = s.id
                   )
                   SELECT id FROM subtree""",
                (node_id,),
            )
        }
        conflicts = [
            c for c in _compat_conflicts(conn) if c.get("location_id") in subtree_ids
        ]
        placement = [
            w for w in _placement_warnings(conn) if w.get("location_id") in subtree_ids
        ]
        return {
            "node": dict(node),
            "containers": containers,
            "hazards": sorted(hazards),
            "conflicts": conflicts,
            "placement": placement,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# cycle count / stocktake
# --------------------------------------------------------------------------- #
class CountCreateBody(BaseModel):
    location_id: Optional[int] = None
    name: Optional[str] = None
    note: Optional[str] = None


class CountScanBody(BaseModel):
    code: str


class CountLineBody(BaseModel):
    status: Optional[str] = None
    counted: Optional[int] = None


def _count_summary(conn, session_id):
    """Roll a session's lines up into the accuracy KPI + status buckets."""
    row = conn.execute(
        """SELECT
               COALESCE(SUM(expected), 0)                              AS expected,
               COALESCE(SUM(COALESCE(counted, 0)), 0)                  AS counted,
               COALESCE(SUM(status = 'found'), 0)                      AS found,
               COALESCE(SUM(status = 'missing'), 0)                    AS missing,
               COALESCE(SUM(status = 'extra'), 0)                      AS extra,
               COALESCE(SUM(status = 'pending'), 0)                    AS pending
           FROM count_line WHERE session_id = ?""",
        (session_id,),
    ).fetchone()
    expected = row["expected"]
    found = row["found"]
    accuracy = 1.0 if expected == 0 else round(found / expected, 4)
    return {
        "expected": expected,
        "counted": row["counted"],
        "found": found,
        "missing": row["missing"],
        "extra": row["extra"],
        "pending": row["pending"],
        "accuracy": accuracy,
    }


def _count_lines(conn, session_id):
    return _rows(conn.execute(
        """SELECT cl.id, cl.container_id, cl.item_id, i.item_name,
                  cl.box_name, cl.row, cl.col, cl.expected, cl.counted,
                  cl.status, cl.counted_at
           FROM count_line cl
           LEFT JOIN inventory i ON i.item_id = cl.item_id
           WHERE cl.session_id = ?
           ORDER BY (cl.status = 'extra'), cl.box_name, cl.row, cl.col, cl.id""",
        (session_id,),
    ))


def _count_detail(conn, session_id):
    s = conn.execute(
        """SELECT cs.id, cs.location_id, cs.name, cs.status,
                  cs.started_at, cs.closed_at, cs.note,
                  u.username AS started_by_username
           FROM count_session cs
           LEFT JOIN app_user u ON u.id = cs.started_by
           WHERE cs.id = ?""",
        (session_id,),
    ).fetchone()
    if s is None:
        return None
    d = dict(s)
    d["location_name"] = _location_path(conn, d["location_id"]) if d["location_id"] else None
    d["lines"] = _count_lines(conn, session_id)
    d["summary"] = _count_summary(conn, session_id)
    d["discrepancies"] = _count_discrepancies(conn, session_id)
    return d


def _count_discrepancies(conn, session_id):
    """Per-item summary of what the count could not find, for reconciliation.

    Containers are not necessarily one stock unit each, so this reports the
    facts -- how many containers are unaccounted for against the recorded
    on-hand -- and leaves the correction to an explicit per-item
    'set actual quantity', rather than inferring unit math.
    """
    return _rows(conn.execute(
        """SELECT cl.item_id,
                  i.item_name,
                  i.unit,
                  i.quantity_on_hand,
                  COUNT(*) AS missing_containers
             FROM count_line cl
             JOIN inventory i ON i.item_id = cl.item_id
            WHERE cl.session_id = ? AND cl.status = 'missing'
              AND cl.item_id IS NOT NULL
            GROUP BY cl.item_id, i.item_name, i.unit, i.quantity_on_hand
            ORDER BY i.item_name""",
        (session_id,),
    ))


@router.post("/counts", dependencies=[Depends(auth.require_role("member"))])
def create_count(body: CountCreateBody, user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        loc_id = body.location_id
        if loc_id is not None:
            node = conn.execute(
                "SELECT id FROM location_node WHERE id = ?", (loc_id,)
            ).fetchone()
            if node is None:
                raise HTTPException(status_code=404, detail="location not found")

        uid = _current_uid(conn, user)
        cur = conn.execute(
            """INSERT INTO count_session
                   (location_id, name, status, started_by, started_at, note)
               VALUES (?, ?, 'open', ?, datetime('now'), ?)""",
            (loc_id, (body.name or None), uid, (body.note or None)),
        )
        session_id = cur.lastrowid

        # Snapshot: every in_use container at/under the location (whole lab when
        # location_id is NULL) becomes a pending expected line. Same recursive
        # subtree walk as /locations/{id}/contents.
        if loc_id is None:
            containers = conn.execute(
                """SELECT c.id AS container_id, l.item_id,
                          b.name AS box_name, c.row, c.col
                   FROM container c
                   JOIN item_lot l ON l.id = c.item_lot_id
                   LEFT JOIN location_node b ON b.id = c.box_id
                   WHERE c.status = 'in_use'
                   ORDER BY c.id""",
            ).fetchall()
        else:
            containers = conn.execute(
                """WITH RECURSIVE subtree(id) AS (
                       SELECT id FROM location_node WHERE id = ?
                       UNION ALL
                       SELECT n.id FROM location_node n
                       JOIN subtree s ON n.parent_id = s.id
                   )
                   SELECT c.id AS container_id, l.item_id,
                          b.name AS box_name, c.row, c.col
                   FROM container c
                   JOIN item_lot l ON l.id = c.item_lot_id
                   LEFT JOIN location_node b ON b.id = c.box_id
                   WHERE c.status = 'in_use' AND c.box_id IN (SELECT id FROM subtree)
                   ORDER BY c.id""",
                (loc_id,),
            ).fetchall()

        for c in containers:
            conn.execute(
                """INSERT INTO count_line
                       (session_id, container_id, item_id, box_name, row, col,
                        expected, status)
                   VALUES (?, ?, ?, ?, ?, ?, 1, 'pending')""",
                (session_id, c["container_id"], c["item_id"], c["box_name"],
                 c["row"], c["col"]),
            )

        _audit(conn, user, "count.start", "count_session", session_id,
               f"{len(containers)} containers")
        conn.commit()
        return _count_detail(conn, session_id)
    finally:
        conn.close()


@router.get("/counts", dependencies=[Depends(auth.require_role("member"))])
def list_counts():
    conn = get_conn()
    try:
        sessions = _rows(conn.execute(
            """SELECT cs.id, cs.location_id, cs.name, cs.status,
                      cs.started_at, cs.closed_at,
                      u.username AS started_by_username,
                      COALESCE(SUM(cl.expected), 0)          AS expected,
                      COALESCE(SUM(cl.status = 'found'), 0)  AS found
               FROM count_session cs
               LEFT JOIN app_user u ON u.id = cs.started_by
               LEFT JOIN count_line cl ON cl.session_id = cs.id
               GROUP BY cs.id
               ORDER BY (cs.status = 'closed'), cs.started_at DESC, cs.id DESC""",
        ))
        for s in sessions:
            expected = s.pop("expected")
            found = s.pop("found")
            s["location_name"] = (
                _location_path(conn, s["location_id"]) if s["location_id"] else None
            )
            s["expected"] = expected
            s["counted"] = found
            s["accuracy"] = 1.0 if expected == 0 else round(found / expected, 4)
        return sessions
    finally:
        conn.close()


@router.get("/counts/{session_id}", dependencies=[Depends(auth.require_role("member"))])
def count_detail(session_id: int):
    conn = get_conn()
    try:
        d = _count_detail(conn, session_id)
        if d is None:
            raise HTTPException(status_code=404, detail="count session not found")
        return d
    finally:
        conn.close()


def _resolve_scan_code(conn, code):
    """Resolve a scanned code to an inventory item_id, or None.

    Order: an `item=<n>` QR deep-link, then an all-digit item_id, then a
    vendor_catalog.catalog_number whose linked inventory item is on file.
    """
    code = (code or "").strip()
    if not code:
        return None
    m = re.search(r"item=(\d+)", code)
    item_id = None
    if m:
        item_id = int(m.group(1))
    elif code.isdigit():
        item_id = int(code)
    if item_id is not None:
        row = conn.execute(
            "SELECT item_id FROM inventory WHERE item_id = ?", (item_id,)
        ).fetchone()
        return row["item_id"] if row else None
    # Fall back to a vendor catalog number -> its linked inventory item.
    row = conn.execute(
        """SELECT i.item_id
           FROM vendor_catalog vc
           JOIN inventory i ON i.catalog_id = vc.id
           WHERE vc.catalog_number = ?
           ORDER BY i.item_id LIMIT 1""",
        (code,),
    ).fetchone()
    return row["item_id"] if row else None


@router.post("/counts/{session_id}/scan", dependencies=[Depends(auth.require_role("member"))])
def scan_count(session_id: int, body: CountScanBody,
               user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        s = conn.execute(
            "SELECT id, status FROM count_session WHERE id = ?", (session_id,)
        ).fetchone()
        if s is None:
            raise HTTPException(status_code=404, detail="count session not found")
        if s["status"] != "open":
            raise HTTPException(status_code=400, detail="count session is closed")

        item_id = _resolve_scan_code(conn, body.code)
        if item_id is None:
            return {
                "matched": False,
                "reason": "code did not resolve to a known item",
                "line": None,
                "summary": _count_summary(conn, session_id),
            }

        uid = _current_uid(conn, user)
        pending = conn.execute(
            """SELECT id, expected FROM count_line
               WHERE session_id = ? AND item_id = ? AND status = 'pending'
               ORDER BY id LIMIT 1""",
            (session_id, item_id),
        ).fetchone()

        if pending is not None:
            conn.execute(
                """UPDATE count_line
                   SET status = 'found', counted = expected,
                       counted_at = datetime('now'), counted_by = ?
                   WHERE id = ?""",
                (uid, pending["id"]),
            )
            line_id = pending["id"]
            matched = True
        else:
            cur = conn.execute(
                """INSERT INTO count_line
                       (session_id, container_id, item_id, expected, counted,
                        status, counted_at, counted_by)
                   VALUES (?, NULL, ?, 0, 1, 'extra', datetime('now'), ?)""",
                (session_id, item_id, uid),
            )
            line_id = cur.lastrowid
            matched = False

        conn.commit()
        line = conn.execute(
            """SELECT cl.id, cl.container_id, cl.item_id, i.item_name,
                      cl.box_name, cl.row, cl.col, cl.expected, cl.counted,
                      cl.status, cl.counted_at
               FROM count_line cl
               LEFT JOIN inventory i ON i.item_id = cl.item_id
               WHERE cl.id = ?""",
            (line_id,),
        ).fetchone()
        return {
            "matched": matched,
            "line": dict(line) if line else None,
            "summary": _count_summary(conn, session_id),
        }
    finally:
        conn.close()


@router.patch("/counts/{session_id}/lines/{line_id}",
              dependencies=[Depends(auth.require_role("member"))])
def update_count_line(session_id: int, line_id: int, body: CountLineBody,
                      user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        s = conn.execute(
            "SELECT id, status FROM count_session WHERE id = ?", (session_id,)
        ).fetchone()
        if s is None:
            raise HTTPException(status_code=404, detail="count session not found")
        if s["status"] != "open":
            raise HTTPException(status_code=400, detail="count session is closed")
        line = conn.execute(
            "SELECT id, expected FROM count_line WHERE id = ? AND session_id = ?",
            (line_id, session_id),
        ).fetchone()
        if line is None:
            raise HTTPException(status_code=404, detail="count line not found")

        sets, params = [], []
        if body.status is not None:
            if body.status not in ("pending", "found", "missing", "extra"):
                raise HTTPException(status_code=400, detail="invalid status")
            sets.append("status = ?")
            params.append(body.status)
            # A bare status change to found stamps counted to expected.
            if body.status == "found" and body.counted is None:
                sets.append("counted = expected")
            elif body.status == "missing" and body.counted is None:
                sets.append("counted = 0")
        if body.counted is not None:
            sets.append("counted = ?")
            params.append(body.counted)
        if not sets:
            raise HTTPException(status_code=400, detail="nothing to update")

        uid = _current_uid(conn, user)
        sets.append("counted_at = datetime('now')")
        sets.append("counted_by = ?")
        params.append(uid)
        params.extend([line_id, session_id])
        conn.execute(
            f"UPDATE count_line SET {', '.join(sets)} WHERE id = ? AND session_id = ?",
            params,
        )
        conn.commit()
        upd = conn.execute(
            """SELECT cl.id, cl.container_id, cl.item_id, i.item_name,
                      cl.box_name, cl.row, cl.col, cl.expected, cl.counted,
                      cl.status, cl.counted_at
               FROM count_line cl
               LEFT JOIN inventory i ON i.item_id = cl.item_id
               WHERE cl.id = ?""",
            (line_id,),
        ).fetchone()
        return {"line": dict(upd), "summary": _count_summary(conn, session_id)}
    finally:
        conn.close()


@router.post("/counts/{session_id}/close",
             dependencies=[Depends(auth.require_role("member"))])
def close_count(session_id: int, user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        s = conn.execute(
            "SELECT id, name, status FROM count_session WHERE id = ?", (session_id,)
        ).fetchone()
        if s is None:
            raise HTTPException(status_code=404, detail="count session not found")
        if s["status"] == "closed":
            raise HTTPException(status_code=400, detail="count session already closed")

        # Anything never accounted for is missing.
        conn.execute(
            """UPDATE count_line SET status = 'missing', counted = 0
               WHERE session_id = ? AND status = 'pending'""",
            (session_id,),
        )
        # Act on that finding: a container the count proved absent must stop
        # reading as physically present. Every "is it here" query filters
        # status = 'in_use', so flagging it 'missing' removes it from the map,
        # item container lists, dashboard counts and misplacement checks.
        # Reversible: a manager can PATCH the container back if it turns up.
        applied = conn.execute(
            """UPDATE container SET status = 'missing'
                WHERE status = 'in_use' AND id IN (
                    SELECT container_id FROM count_line
                     WHERE session_id = ? AND status = 'missing'
                       AND container_id IS NOT NULL)""",
            (session_id,),
        ).rowcount
        conn.execute(
            "UPDATE count_session SET status = 'closed', closed_at = datetime('now') WHERE id = ?",
            (session_id,),
        )
        summary = _count_summary(conn, session_id)
        _audit(conn, user, "count.close", "count_session", session_id,
               f"accuracy {summary['accuracy']:.0%}, {summary['missing']} missing"
               + (f", {applied} container(s) flagged missing" if applied else ""))
        if summary["missing"] > 0:
            conn.execute(
                """INSERT INTO notification
                       (created_at, user_id, kind, severity, message,
                        entity_type, entity_id, link_view)
                   VALUES (datetime('now'), NULL, 'other', 'warn', ?,
                           'count_session', ?, 'stocktake')""",
                (f"Stocktake found {summary['missing']} missing container(s)",
                 session_id),
            )
        conn.commit()
        return _count_detail(conn, session_id)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# kits / bill of materials
# --------------------------------------------------------------------------- #
class KitLineBody(BaseModel):
    item_id: int
    quantity: int


class KitBody(BaseModel):
    name: str
    description: Optional[str] = None
    output_item_id: Optional[int] = None
    output_qty: Optional[int] = 0
    lines: List[KitLineBody] = []


class KitAssembleBody(BaseModel):
    count: Optional[int] = 1


_KIT_ASSEMBLE_UNBOUNDED = 999999  # "max" when a kit has no components


def _kit_detail(conn, kit_id):
    k = conn.execute(
        """SELECT k.id, k.name, k.description, k.output_item_id, k.output_qty,
                  o.item_name AS output_item_name
           FROM kit k
           LEFT JOIN inventory o ON o.item_id = k.output_item_id
           WHERE k.id = ?""",
        (kit_id,),
    ).fetchone()
    if k is None:
        return None
    lines = _rows(conn.execute(
        """SELECT kl.item_id, i.item_name, i.unit, kl.quantity,
                  i.unit_cost, i.quantity_on_hand AS on_hand
           FROM kit_line kl
           JOIN inventory i ON i.item_id = kl.item_id
           WHERE kl.kit_id = ?
           ORDER BY kl.id""",
        (kit_id,),
    ))
    total_cost = sum((ln["quantity"] or 0) * (ln["unit_cost"] or 0) for ln in lines)
    if not lines:
        max_assemblies = _KIT_ASSEMBLE_UNBOUNDED
    else:
        max_assemblies = min(
            (ln["on_hand"] // ln["quantity"]) if ln["quantity"] else 0
            for ln in lines
        )
    d = dict(k)
    d["lines"] = lines
    d["total_cost"] = round(total_cost, 2)
    d["max_assemblies"] = max_assemblies
    return d


@router.get("/kits", dependencies=[Depends(auth.require_role("member"))])
def list_kits():
    conn = get_conn()
    try:
        return _rows(conn.execute(
            """SELECT k.id, k.name, k.description, k.output_item_id,
                      o.item_name AS output_item_name, k.output_qty,
                      COUNT(kl.id) AS line_count,
                      COALESCE(SUM(kl.quantity * i.unit_cost), 0) AS total_cost
               FROM kit k
               LEFT JOIN inventory o ON o.item_id = k.output_item_id
               LEFT JOIN kit_line kl ON kl.kit_id = k.id
               LEFT JOIN inventory i ON i.item_id = kl.item_id
               GROUP BY k.id
               ORDER BY k.name""",
        ))
    finally:
        conn.close()


@router.get("/kits/{kit_id}", dependencies=[Depends(auth.require_role("member"))])
def kit_detail(kit_id: int):
    conn = get_conn()
    try:
        d = _kit_detail(conn, kit_id)
        if d is None:
            raise HTTPException(status_code=404, detail="kit not found")
        return d
    finally:
        conn.close()


def _validate_kit_body(conn, body, exclude_kit_id=None):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name cannot be empty")
    dup = conn.execute(
        "SELECT id FROM kit WHERE name = ? AND id IS NOT ?",
        (name, exclude_kit_id),
    ).fetchone()
    if dup is not None:
        raise HTTPException(status_code=400, detail="a kit with that name exists")
    if body.output_item_id is not None:
        if conn.execute(
            "SELECT 1 FROM inventory WHERE item_id = ?", (body.output_item_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=400, detail="unknown output_item_id")
    for ln in body.lines:
        if ln.quantity is None or ln.quantity <= 0:
            raise HTTPException(status_code=400, detail="quantities must be positive")
        if conn.execute(
            "SELECT 1 FROM inventory WHERE item_id = ?", (ln.item_id,)
        ).fetchone() is None:
            raise HTTPException(status_code=400, detail=f"unknown item_id {ln.item_id}")
    return name


def _write_kit_lines(conn, kit_id, lines):
    conn.execute("DELETE FROM kit_line WHERE kit_id = ?", (kit_id,))
    for ln in lines:
        conn.execute(
            "INSERT INTO kit_line (kit_id, item_id, quantity) VALUES (?, ?, ?)",
            (kit_id, ln.item_id, ln.quantity),
        )


@router.post("/kits", dependencies=[Depends(auth.require_role("manager"))])
def create_kit(body: KitBody, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        name = _validate_kit_body(conn, body)
        cur = conn.execute(
            """INSERT INTO kit (name, description, output_item_id, output_qty)
               VALUES (?, ?, ?, ?)""",
            (name, body.description, body.output_item_id, body.output_qty or 0),
        )
        kit_id = cur.lastrowid
        _write_kit_lines(conn, kit_id, body.lines)
        _audit(conn, user, "kit.create", "kit", kit_id, name)
        conn.commit()
        return _kit_detail(conn, kit_id)
    finally:
        conn.close()


@router.patch("/kits/{kit_id}", dependencies=[Depends(auth.require_role("manager"))])
def update_kit(kit_id: int, body: KitBody,
               user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM kit WHERE id = ?", (kit_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="kit not found")
        name = _validate_kit_body(conn, body, exclude_kit_id=kit_id)
        conn.execute(
            """UPDATE kit SET name = ?, description = ?,
                   output_item_id = ?, output_qty = ? WHERE id = ?""",
            (name, body.description, body.output_item_id, body.output_qty or 0, kit_id),
        )
        _write_kit_lines(conn, kit_id, body.lines)
        _audit(conn, user, "kit.update", "kit", kit_id, name)
        conn.commit()
        return _kit_detail(conn, kit_id)
    finally:
        conn.close()


@router.delete("/kits/{kit_id}", dependencies=[Depends(auth.require_role("manager"))])
def delete_kit(kit_id: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        k = conn.execute("SELECT id, name FROM kit WHERE id = ?", (kit_id,)).fetchone()
        if k is None:
            raise HTTPException(status_code=404, detail="kit not found")
        conn.execute("DELETE FROM kit_line WHERE kit_id = ?", (kit_id,))
        conn.execute("DELETE FROM kit WHERE id = ?", (kit_id,))
        _audit(conn, user, "kit.delete", "kit", kit_id, k["name"])
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def _sync_lots_to_quantity(conn, item_id, target, label="import adjustment"):
    """Make SUM(item_lot.quantity) equal target for one item.

    Trims lots first-expiry-first when they over-state the new figure, and opens
    a lot for the shortfall when they under-state it, so a bulk write cannot
    leave stock that no lot accounts for (which expiry alerts would never see).
    Returns the signed change applied to the lot total.
    """
    lot_total = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS t FROM item_lot WHERE item_id = ?",
        (item_id,),
    ).fetchone()["t"]
    if target > lot_total:
        _open_lot(conn, item_id, target - lot_total, label=label)
    elif target < lot_total:
        _draw_down_lots(conn, item_id, lot_total - target)
    return target - lot_total


def _canonical_dt(value):
    """Normalize a client datetime to SQLite's 'YYYY-MM-DD HH:MM:SS' text form.

    The browser's <input type="datetime-local"> posts 'YYYY-MM-DDTHH:MM' while
    everything server-side writes a space separator. Both are valid to SQLite's
    datetime(), but comparing them as raw TEXT is not: 'T' (0x54) sorts above
    ' ' (0x20). Canonicalizing on write keeps stored values directly comparable.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("T", " ")
    if len(text) == 16:      # 'YYYY-MM-DD HH:MM' -> add seconds
        text += ":00"
    return text


def _draw_down_lots(conn, item_id, quantity):
    """FIFO-by-expiry lot drawdown mirroring consume_item."""
    remaining = quantity
    lots = conn.execute(
        """SELECT id, quantity FROM item_lot
           WHERE item_id = ? AND quantity > 0
           ORDER BY (expiry_date IS NULL), expiry_date, id""",
        (item_id,),
    ).fetchall()
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot["quantity"], remaining)
        conn.execute(
            "UPDATE item_lot SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
            (take, lot["id"], take),
        )
        remaining -= take


@router.post("/kits/{kit_id}/assemble",
             dependencies=[Depends(auth.require_role("member"))])
def assemble_kit(kit_id: int, body: KitAssembleBody,
                 user: dict = Depends(auth.require_role("member"))):
    count = body.count if body.count is not None else 1
    if count <= 0:
        raise HTTPException(status_code=400, detail="count must be positive")
    conn = get_conn()
    try:
        kit = conn.execute(
            """SELECT id, name, output_item_id, output_qty
               FROM kit WHERE id = ?""",
            (kit_id,),
        ).fetchone()
        if kit is None:
            raise HTTPException(status_code=404, detail="kit not found")
        lines = conn.execute(
            """SELECT kl.item_id, kl.quantity, i.item_name
               FROM kit_line kl JOIN inventory i ON i.item_id = kl.item_id
               WHERE kl.kit_id = ? ORDER BY kl.id""",
            (kit_id,),
        ).fetchall()
        if not lines:
            raise HTTPException(status_code=400, detail="kit has no components")

        consumed = []
        for ln in lines:
            need = ln["quantity"] * count
            # Atomic guarded deduction: the conditional UPDATE is the single
            # arbiter of success, exactly like consume_item.
            cur = conn.execute(
                """UPDATE inventory SET quantity_on_hand = quantity_on_hand - ?
                   WHERE item_id = ? AND quantity_on_hand >= ?""",
                (need, ln["item_id"], need),
            )
            if cur.rowcount == 0:
                conn.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"insufficient {ln['item_name']} to assemble",
                )
            _draw_down_lots(conn, ln["item_id"], need)
            conn.execute(
                """INSERT INTO usage_event
                       (item_id, container_id, staff_id, event_type, quantity,
                        occurred_at, note)
                   VALUES (?, NULL, NULL, 'consume', ?, datetime('now'), ?)""",
                (ln["item_id"], need, f"kit: {kit['name']}"),
            )
            consumed.append({
                "item_id": ln["item_id"],
                "item_name": ln["item_name"],
                "qty": need,
            })

        produced = None
        if kit["output_item_id"] is not None and (kit["output_qty"] or 0) > 0:
            out_qty = kit["output_qty"] * count
            conn.execute(
                "UPDATE inventory SET quantity_on_hand = quantity_on_hand + ? WHERE item_id = ?",
                (out_qty, kit["output_item_id"]),
            )
            conn.execute(
                """INSERT INTO item_lot (item_id, lot_number, expiry_date, quantity, received_date)
                   VALUES (?, NULL, NULL, ?, date('now'))""",
                (kit["output_item_id"], out_qty),
            )
            conn.execute(
                """INSERT INTO usage_event
                       (item_id, container_id, staff_id, event_type, quantity,
                        occurred_at, note)
                   VALUES (?, NULL, NULL, 'restock', ?, datetime('now'), ?)""",
                (kit["output_item_id"], out_qty, f"assembled {kit['name']}"),
            )
            out_name = conn.execute(
                "SELECT item_name FROM inventory WHERE item_id = ?",
                (kit["output_item_id"],),
            ).fetchone()["item_name"]
            produced = {
                "item_id": kit["output_item_id"],
                "item_name": out_name,
                "qty": out_qty,
            }

        _audit(conn, user, "kit.assemble", "kit", kit_id, f"{kit['name']} x{count}")
        conn.commit()
        return {"ok": True, "count": count, "consumed": consumed, "produced": produced}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# equipment registry, booking, maintenance
# --------------------------------------------------------------------------- #
_EQUIPMENT_FIELDS = (
    "name", "category", "make_model", "serial_number", "location_id", "status",
    "purchase_date", "service_interval_days", "last_service_date",
    "next_service_date", "note", "cleanup_url",
)
_EQUIPMENT_STATUSES = ("operational", "maintenance", "out_of_service")


def _is_manager(user):
    return auth.ROLE_RANK.get((user or {}).get("role"), -1) >= auth.ROLE_RANK["manager"]


def _equipment_row(conn, eid):
    row = conn.execute("SELECT * FROM equipment WHERE id = ?", (eid,)).fetchone()
    return dict(row) if row else None


def _equipment_detail(conn, eid):
    d = _equipment_row(conn, eid)
    if d is None:
        return None
    d["location_path"] = _location_path(conn, d["location_id"])
    today = _today(conn)
    nsd = d["next_service_date"]
    d["service_due"] = bool(nsd and nsd <= today) or bool(
        nsd and _days_between(today, nsd) is not None and _days_between(today, nsd) <= 14
    )
    d["days_to_service"] = _days_between(today, nsd) if nsd else None
    d["reservations"] = _rows(conn.execute(
        """SELECT r.id, r.user_id, u.username, r.starts_at, r.ends_at, r.purpose
           FROM equipment_reservation r
           LEFT JOIN app_user u ON u.id = r.user_id
           WHERE r.equipment_id = ? AND r.ends_at >= datetime('now')
           ORDER BY r.starts_at ASC, r.id ASC""",
        (eid,),
    ))
    d["maintenance"] = _rows(conn.execute(
        """SELECT id, kind, performed_at, performed_by, note, next_due
           FROM equipment_maintenance
           WHERE equipment_id = ?
           ORDER BY performed_at DESC, id DESC""",
        (eid,),
    ))
    return d


@router.get("/equipment", dependencies=[Depends(auth.require_role("member"))])
def list_equipment():
    conn = get_conn()
    try:
        today = _today(conn)
        rows = _rows(conn.execute(
            """SELECT e.*,
                      (SELECT COUNT(*) FROM equipment_reservation r
                       WHERE r.equipment_id = e.id AND r.ends_at >= datetime('now'))
                          AS open_reservations
               FROM equipment e
               ORDER BY e.name COLLATE NOCASE ASC, e.id ASC"""
        ))
        for d in rows:
            d["location_path"] = _location_path(conn, d["location_id"])
            nsd = d["next_service_date"]
            days = _days_between(today, nsd) if nsd else None
            d["service_due"] = bool(nsd and nsd <= today) or bool(
                nsd and days is not None and days <= 14
            )
            d["days_to_service"] = days
        return rows
    finally:
        conn.close()


@router.get("/equipment/{eid}", dependencies=[Depends(auth.require_role("member"))])
def equipment_detail(eid: int):
    conn = get_conn()
    try:
        d = _equipment_detail(conn, eid)
        if d is None:
            raise HTTPException(status_code=404, detail="equipment not found")
        return d
    finally:
        conn.close()


@router.post("/equipment", dependencies=[Depends(auth.require_role("manager"))])
def create_equipment(payload: dict = Body(...),
                     user: dict = Depends(auth.require_role("manager"))):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    status = payload.get("status") or "operational"
    if status not in _EQUIPMENT_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    conn = get_conn()
    try:
        cols, vals = [], []
        for f in _EQUIPMENT_FIELDS:
            if f == "name":
                cols.append(f)
                vals.append(name)
            elif f == "status":
                cols.append(f)
                vals.append(status)
            elif f in payload:
                cols.append(f)
                vals.append(payload[f])
        placeholders = ",".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO equipment ({','.join(cols)}) VALUES ({placeholders})", vals
        )
        eid = cur.lastrowid
        _audit(conn, user, "equipment.create", "equipment", eid, name)
        conn.commit()
        return _equipment_detail(conn, eid)
    finally:
        conn.close()


@router.patch("/equipment/{eid}", dependencies=[Depends(auth.require_role("manager"))])
def update_equipment(eid: int, payload: dict = Body(...),
                     user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if _equipment_row(conn, eid) is None:
            raise HTTPException(status_code=404, detail="equipment not found")
        if "status" in payload and payload["status"] not in _EQUIPMENT_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")
        sets, vals = [], []
        for f in _EQUIPMENT_FIELDS:
            if f in payload:
                sets.append(f"{f} = ?")
                vals.append(payload[f])
        if sets:
            vals.append(eid)
            conn.execute(f"UPDATE equipment SET {','.join(sets)} WHERE id = ?", vals)
        _audit(conn, user, "equipment.update", "equipment", eid)
        conn.commit()
        return _equipment_detail(conn, eid)
    finally:
        conn.close()


@router.delete("/equipment/{eid}", dependencies=[Depends(auth.require_role("manager"))])
def delete_equipment(eid: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if _equipment_row(conn, eid) is None:
            raise HTTPException(status_code=404, detail="equipment not found")
        conn.execute("DELETE FROM equipment_reservation WHERE equipment_id = ?", (eid,))
        conn.execute("DELETE FROM equipment_maintenance WHERE equipment_id = ?", (eid,))
        conn.execute("DELETE FROM equipment WHERE id = ?", (eid,))
        _audit(conn, user, "equipment.delete", "equipment", eid)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/equipment/{eid}/reservations",
             dependencies=[Depends(auth.require_role("member"))])
def create_reservation(eid: int, payload: dict = Body(...),
                       user: dict = Depends(auth.require_role("member"))):
    starts_at = _canonical_dt(payload.get("starts_at"))
    ends_at = _canonical_dt(payload.get("ends_at"))
    if not starts_at or not ends_at:
        raise HTTPException(status_code=400, detail="starts_at and ends_at are required")
    if starts_at >= ends_at:
        raise HTTPException(status_code=400, detail="starts_at must be before ends_at")
    conn = get_conn()
    try:
        if _equipment_row(conn, eid) is None:
            raise HTTPException(status_code=404, detail="equipment not found")
        # Compare through datetime() rather than raw TEXT: rows written before
        # inputs were canonicalized may still hold the browser's
        # "YYYY-MM-DDTHH:MM" form, and 'T' sorts above ' ', which silently made
        # the overlap test false and allowed double-booking.
        clash = conn.execute(
            """SELECT id FROM equipment_reservation
               WHERE equipment_id = ?
                 AND datetime(?) < datetime(ends_at)
                 AND datetime(?) > datetime(starts_at)
               LIMIT 1""",
            (eid, starts_at, ends_at),
        ).fetchone()
        if clash is not None:
            raise HTTPException(
                status_code=400,
                detail="that time slot overlaps an existing reservation",
            )
        uid = _current_uid(conn, user)
        cur = conn.execute(
            """INSERT INTO equipment_reservation
                   (equipment_id, user_id, starts_at, ends_at, purpose, created_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (eid, uid, starts_at, ends_at, payload.get("purpose")),
        )
        rid = cur.lastrowid
        _audit(conn, user, "equipment.book", "equipment", eid,
               f"{starts_at} -> {ends_at}")
        conn.commit()
        row = conn.execute(
            """SELECT r.id, r.equipment_id, r.user_id, u.username,
                      r.starts_at, r.ends_at, r.purpose, r.created_at
               FROM equipment_reservation r
               LEFT JOIN app_user u ON u.id = r.user_id
               WHERE r.id = ?""",
            (rid,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


@router.delete("/equipment/{eid}/reservations/{rid}",
               dependencies=[Depends(auth.require_role("member"))])
def delete_reservation(eid: int, rid: int,
                       user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, user_id FROM equipment_reservation WHERE id = ? AND equipment_id = ?",
            (rid, eid),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="reservation not found")
        if not _is_manager(user) and row["user_id"] != _current_uid(conn, user):
            raise HTTPException(
                status_code=403, detail="you can only cancel your own reservation"
            )
        conn.execute("DELETE FROM equipment_reservation WHERE id = ?", (rid,))
        _audit(conn, user, "equipment.unbook", "equipment", eid, f"reservation {rid}")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/equipment/{eid}/maintenance",
             dependencies=[Depends(auth.require_role("manager"))])
def add_maintenance(eid: int, payload: dict = Body(...),
                    user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        eq = _equipment_row(conn, eid)
        if eq is None:
            raise HTTPException(status_code=404, detail="equipment not found")
        performed_at = payload.get("performed_at") or _today(conn)
        next_due = payload.get("next_due")
        conn.execute(
            """INSERT INTO equipment_maintenance
                   (equipment_id, kind, performed_at, performed_by, note, next_due)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (eid, payload.get("kind"), performed_at, payload.get("performed_by"),
             payload.get("note"), next_due),
        )
        # Advance the equipment service dates.
        new_next = next_due
        if new_next is None and eq["service_interval_days"]:
            row = conn.execute(
                "SELECT date(?, '+' || ? || ' day') AS d",
                (performed_at, eq["service_interval_days"]),
            ).fetchone()
            new_next = row["d"]
        conn.execute(
            "UPDATE equipment SET last_service_date = ?, next_service_date = ? WHERE id = ?",
            (performed_at, new_next, eid),
        )
        _audit(conn, user, "equipment.maintenance", "equipment", eid,
               payload.get("kind") or "service")
        conn.commit()
        _sync_notifications(conn)
        return _equipment_detail(conn, eid)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# funds / budget
# --------------------------------------------------------------------------- #
_FUND_FIELDS = ("name", "sponsor", "budget", "start_date", "end_date", "note")


def _fund_summary(fund, spent):
    budget = fund["budget"] or 0
    remaining = round(budget - spent, 2)
    pct = round(spent / budget * 100, 1) if budget > 0 else 0
    return {"spent": round(spent, 2), "remaining": remaining, "pct_spent": pct}


def _fund_detail(conn, fid):
    row = conn.execute("SELECT * FROM fund WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    spent = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM fund_charge WHERE fund_id = ?", (fid,)
    ).fetchone()["s"]
    d.update(_fund_summary(d, spent))
    d["charges"] = _rows(conn.execute(
        """SELECT c.id, c.amount, c.source_type, c.source_id, c.description,
                  c.charged_at, u.username AS charged_by_username
           FROM fund_charge c
           LEFT JOIN app_user u ON u.id = c.charged_by
           WHERE c.fund_id = ?
           ORDER BY c.charged_at DESC, c.id DESC""",
        (fid,),
    ))
    return d


@router.get("/funds", dependencies=[Depends(auth.require_role("member"))])
def list_funds():
    conn = get_conn()
    try:
        rows = _rows(conn.execute(
            """SELECT f.id, f.name, f.sponsor, f.budget, f.start_date, f.end_date, f.note,
                      COALESCE(SUM(c.amount), 0) AS spent
               FROM fund f
               LEFT JOIN fund_charge c ON c.fund_id = f.id
               GROUP BY f.id
               ORDER BY f.name COLLATE NOCASE ASC, f.id ASC"""
        ))
        for d in rows:
            d.update(_fund_summary(d, d.pop("spent")))
        return rows
    finally:
        conn.close()


@router.get("/funds/spend-by-person", dependencies=[Depends(auth.require_role("member"))])
def funds_spend_by_person(user: dict = Depends(auth.current_user)):
    """Aggregate fund_charge by the person who booked each charge (charged_by).

    Managers/admins see everyone; members see only their own row unless
    usage_visibility='all' (mirrors usage_by_member visibility)."""
    conn = get_conn()
    try:
        see_all = _can_see_all_usage(conn, user)
        where, params = "", []
        if not see_all:
            where = "AND u.id = ?"
            params = [_current_uid(conn, user)]
        people = _rows(conn.execute(
            f"""SELECT u.id AS user_id, u.username, u.full_name, u.role,
                       COUNT(c.id) AS charge_count,
                       COALESCE(SUM(c.amount), 0) AS total_charged
                FROM app_user u
                JOIN fund_charge c ON c.charged_by = u.id
                WHERE c.charged_by IS NOT NULL {where}
                GROUP BY u.id
                ORDER BY total_charged DESC, u.username""",
            tuple(params),
        ))
        for p in people:
            p["total_charged"] = round(p["total_charged"] or 0, 2)
            p["funds"] = [
                {
                    "fund_id": r["fund_id"],
                    "fund_name": r["fund_name"],
                    "amount": round(r["amount"] or 0, 2),
                }
                for r in conn.execute(
                    """SELECT c.fund_id, f.name AS fund_name,
                              COALESCE(SUM(c.amount), 0) AS amount
                       FROM fund_charge c
                       LEFT JOIN fund f ON f.id = c.fund_id
                       WHERE c.charged_by = ?
                       GROUP BY c.fund_id
                       ORDER BY amount DESC, fund_name""",
                    (p["user_id"],),
                )
            ]
        return {"can_see_all": see_all, "people": people}
    finally:
        conn.close()


@router.get("/funds/{fid}", dependencies=[Depends(auth.require_role("member"))])
def fund_detail(fid: int):
    conn = get_conn()
    try:
        d = _fund_detail(conn, fid)
        if d is None:
            raise HTTPException(status_code=404, detail="fund not found")
        return d
    finally:
        conn.close()


@router.post("/funds", dependencies=[Depends(auth.require_role("manager"))])
def create_fund(payload: dict = Body(...),
                user: dict = Depends(auth.require_role("manager"))):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO fund (name, sponsor, budget, start_date, end_date, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, payload.get("sponsor"), payload.get("budget") or 0,
             payload.get("start_date"), payload.get("end_date"), payload.get("note")),
        )
        fid = cur.lastrowid
        _audit(conn, user, "fund.create", "fund", fid, name)
        conn.commit()
        return _fund_detail(conn, fid)
    finally:
        conn.close()


@router.patch("/funds/{fid}", dependencies=[Depends(auth.require_role("manager"))])
def update_fund(fid: int, payload: dict = Body(...),
                user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM fund WHERE id = ?", (fid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="fund not found")
        sets, vals = [], []
        for f in _FUND_FIELDS:
            if f in payload:
                sets.append(f"{f} = ?")
                vals.append(payload[f])
        if sets:
            vals.append(fid)
            conn.execute(f"UPDATE fund SET {','.join(sets)} WHERE id = ?", vals)
        _audit(conn, user, "fund.update", "fund", fid)
        conn.commit()
        return _fund_detail(conn, fid)
    finally:
        conn.close()


@router.delete("/funds/{fid}", dependencies=[Depends(auth.require_role("manager"))])
def delete_fund(fid: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM fund WHERE id = ?", (fid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="fund not found")
        conn.execute("DELETE FROM fund_charge WHERE fund_id = ?", (fid,))
        conn.execute("DELETE FROM fund WHERE id = ?", (fid,))
        _audit(conn, user, "fund.delete", "fund", fid)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.post("/funds/{fid}/charges", dependencies=[Depends(auth.require_role("manager"))])
def add_fund_charge(fid: int, payload: dict = Body(...),
                    user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM fund WHERE id = ?", (fid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="fund not found")
        source_type = payload.get("source_type") or "manual"
        source_id = payload.get("source_id")
        amount = payload.get("amount")
        description = payload.get("description")

        if source_type == "purchase_order" and source_id is not None:
            po = conn.execute(
                "SELECT id, vendor FROM purchase_order WHERE id = ?", (source_id,)
            ).fetchone()
            if po is None:
                raise HTTPException(status_code=400, detail="unknown purchase order")
            total = conn.execute(
                "SELECT COALESCE(SUM(quantity * unit_cost), 0) AS t FROM po_line WHERE po_id = ?",
                (source_id,),
            ).fetchone()["t"]
            if amount is None:
                amount = round(total, 2)
            if not description:
                description = f"PO #{source_id} ({po['vendor'] or 'no vendor'})"

        if amount is None:
            raise HTTPException(status_code=400, detail="amount is required")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="amount must be a number")

        conn.execute(
            """INSERT INTO fund_charge
                   (fund_id, amount, source_type, source_id, description,
                    charged_at, charged_by)
               VALUES (?, ?, ?, ?, ?, datetime('now'), ?)""",
            (fid, amount, source_type, source_id, description, _current_uid(conn, user)),
        )
        _audit(conn, user, "fund.charge", "fund", fid, f"{amount} ({source_type})")
        conn.commit()
        return _fund_detail(conn, fid)
    finally:
        conn.close()


@router.delete("/funds/{fid}/charges/{cid}",
               dependencies=[Depends(auth.require_role("manager"))])
def delete_fund_charge(fid: int, cid: int,
                       user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM fund_charge WHERE id = ? AND fund_id = ?", (cid, fid)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="charge not found")
        conn.execute("DELETE FROM fund_charge WHERE id = ?", (cid,))
        _audit(conn, user, "fund.charge_remove", "fund", fid, f"charge {cid}")
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# CSV exports
# --------------------------------------------------------------------------- #
def _csv_cell(v):
    """Coerce a value to a CSV-safe string. Stored free-text can contain NUL or
    other C0 control bytes (the fuzz suite POSTs them into notes/tasks); those
    make csv.writer raise, so strip them here."""
    if v is None:
        return ""
    s = str(v)
    if any(ord(c) < 32 and c not in "\t\n\r" for c in s):
        s = "".join(c for c in s if ord(c) >= 32 or c in "\t\n\r")
    # Neutralize spreadsheet formula injection: a member can type "=cmd|..." into
    # an item note, and Excel/Sheets would execute it when the exported CSV is
    # opened. Prefixing with an apostrophe makes the cell literal text.
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return s


def _csv_response(filename, header, rows):
    """Build a text/csv attachment Response from a header + iterable of rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_cell(v) for v in row])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/inventory.csv")
def export_inventory_csv(user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT i.item_id, i.item_name, i.category, i.vendor, i.unit,
                      i.quantity_on_hand, i.reorder_threshold, i.reorder_max,
                      i.unit_cost, i.status, i.is_controlled, i.hazard_class,
                      i.cas_number, vc.catalog_number,
                      MIN(CASE WHEN l.expiry_date IS NOT NULL AND l.quantity > 0
                               THEN l.expiry_date END) AS nearest_expiry
               FROM inventory i
               LEFT JOIN item_lot l ON l.item_id = i.item_id
               LEFT JOIN vendor_catalog vc ON vc.id = i.catalog_id
               GROUP BY i.item_id
               ORDER BY i.item_name COLLATE NOCASE""",
        ).fetchall()
        _audit(conn, user, "export", "export", None, "inventory")
        conn.commit()
        # catalog_number is exported so an edited sheet re-imports against a
        # stable key instead of matching on the (ambiguous) product name.
        header = [
            "item_id", "item_name", "catalog_number", "category", "vendor",
            "unit", "quantity_on_hand", "reorder_threshold", "reorder_max",
            "unit_cost", "status", "is_controlled", "hazard_class",
            "cas_number", "nearest_expiry",
        ]
        return _csv_response(
            "inventory.csv", header, ([r[c] for c in header] for r in rows)
        )
    finally:
        conn.close()


@router.get("/export/usage.csv")
def export_usage_csv(user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT e.occurred_at, e.event_type, i.item_name, e.quantity,
                      e.purpose
               FROM usage_event e
               LEFT JOIN inventory i ON i.item_id = e.item_id
               ORDER BY e.occurred_at DESC, e.id DESC
               LIMIT 5000""",
        ).fetchall()
        _audit(conn, user, "export", "export", None, "usage")
        conn.commit()
        header = ["occurred_at", "event_type", "item_name", "quantity", "purpose"]
        return _csv_response(
            "usage.csv", header, ([r[c] for c in header] for r in rows)
        )
    finally:
        conn.close()


@router.get("/export/funds.csv")
def export_funds_csv(user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT f.name, f.sponsor, f.budget,
                      COALESCE(SUM(c.amount), 0) AS spent
               FROM fund f
               LEFT JOIN fund_charge c ON c.fund_id = f.id
               GROUP BY f.id
               ORDER BY f.name COLLATE NOCASE""",
        ).fetchall()
        _audit(conn, user, "export", "export", None, "funds")
        conn.commit()
        header = ["fund_name", "sponsor", "budget", "spent", "remaining"]
        data = (
            [r["name"], r["sponsor"], r["budget"], r["spent"],
             round((r["budget"] or 0) - (r["spent"] or 0), 2)]
            for r in rows
        )
        return _csv_response("funds.csv", header, data)
    finally:
        conn.close()


@router.get("/export/equipment.csv")
def export_equipment_csv(user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, name, category, make_model, serial_number, status,
                      location_id, next_service_date
               FROM equipment
               ORDER BY name COLLATE NOCASE""",
        ).fetchall()
        header = [
            "name", "category", "make_model", "serial_number", "status",
            "location", "next_service_date",
        ]
        data = [
            [r["name"], r["category"], r["make_model"], r["serial_number"],
             r["status"], _location_path(conn, r["location_id"]),
             r["next_service_date"]]
            for r in rows
        ]
        _audit(conn, user, "export", "export", None, "equipment")
        conn.commit()
        return _csv_response("equipment.csv", header, data)
    finally:
        conn.close()


@router.get("/export/audit.csv")
def export_audit_csv(user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT occurred_at, username, action, entity_type, entity_id, detail
               FROM audit_log
               ORDER BY occurred_at DESC, id DESC
               LIMIT 5000""",
        ).fetchall()
        _audit(conn, user, "export", "export", None, "audit")
        conn.commit()
        header = [
            "occurred_at", "username", "action", "entity_type", "entity_id",
            "detail",
        ]
        return _csv_response(
            "audit.csv", header, ([r[c] for c in header] for r in rows)
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# computers / IT assets
# --------------------------------------------------------------------------- #
_IT_ASSET_COLS = (
    "name", "kind", "make_model", "serial_number", "location_id", "assigned_to",
    "purchase_date", "warranty_end", "status", "note",
)
_IT_ASSET_STATUSES = ("in_service", "repair", "retired")


class ITAssetBody(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    make_model: Optional[str] = None
    serial_number: Optional[str] = None
    location_id: Optional[int] = None
    assigned_to: Optional[int] = None
    purchase_date: Optional[str] = None
    warranty_end: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None


def _it_asset_detail(conn, aid):
    row = conn.execute(
        """SELECT a.*, u.username AS assigned_username
           FROM it_asset a
           LEFT JOIN app_user u ON u.id = a.assigned_to
           WHERE a.id = ?""",
        (aid,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    today = _today(conn)
    d["location_path"] = _location_path(conn, d["location_id"])
    we = d["warranty_end"]
    days = _days_between(today, we) if we else None
    # within 30 days or already past
    d["warranty_soon"] = bool(we and days is not None and days <= 30)
    d["days_to_warranty"] = days
    return d


@router.get("/it-assets", dependencies=[Depends(auth.require_role("member"))])
def list_it_assets():
    conn = get_conn()
    try:
        today = _today(conn)
        rows = _rows(conn.execute(
            """SELECT a.*, u.username AS assigned_username
               FROM it_asset a
               LEFT JOIN app_user u ON u.id = a.assigned_to
               ORDER BY a.name COLLATE NOCASE ASC, a.id ASC"""
        ))
        for d in rows:
            d["location_path"] = _location_path(conn, d["location_id"])
            we = d["warranty_end"]
            days = _days_between(today, we) if we else None
            d["warranty_soon"] = bool(we and days is not None and days <= 30)
            d["days_to_warranty"] = days
        return rows
    finally:
        conn.close()


@router.get("/it-assets/{aid}", dependencies=[Depends(auth.require_role("member"))])
def it_asset_detail(aid: int):
    conn = get_conn()
    try:
        d = _it_asset_detail(conn, aid)
        if d is None:
            raise HTTPException(status_code=404, detail="it asset not found")
        return d
    finally:
        conn.close()


@router.post("/it-assets", dependencies=[Depends(auth.require_role("manager"))])
def create_it_asset(body: ITAssetBody,
                    user: dict = Depends(auth.require_role("manager"))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    status = body.status or "in_service"
    if status not in _IT_ASSET_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    data = body.model_dump(exclude_unset=True)
    conn = get_conn()
    try:
        cols, vals = [], []
        for f in _IT_ASSET_COLS:
            if f == "name":
                cols.append(f)
                vals.append(name)
            elif f == "status":
                cols.append(f)
                vals.append(status)
            elif f in data:
                cols.append(f)
                vals.append(data[f])
        placeholders = ",".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO it_asset ({','.join(cols)}) VALUES ({placeholders})", vals
        )
        aid = cur.lastrowid
        _audit(conn, user, "it_asset.create", "it_asset", aid, name)
        conn.commit()
        return _it_asset_detail(conn, aid)
    finally:
        conn.close()


@router.patch("/it-assets/{aid}", dependencies=[Depends(auth.require_role("manager"))])
def update_it_asset(aid: int, body: ITAssetBody,
                    user: dict = Depends(auth.require_role("manager"))):
    data = body.model_dump(exclude_unset=True)
    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM it_asset WHERE id = ?", (aid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="it asset not found")
        if "name" in data and not (data["name"] or "").strip():
            raise HTTPException(status_code=400, detail="name is required")
        if "status" in data and data["status"] not in _IT_ASSET_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")
        sets, vals = [], []
        for f in _IT_ASSET_COLS:
            if f in data:
                sets.append(f"{f} = ?")
                vals.append(data[f].strip() if f == "name" else data[f])
        if sets:
            vals.append(aid)
            conn.execute(f"UPDATE it_asset SET {','.join(sets)} WHERE id = ?", vals)
        _audit(conn, user, "it_asset.update", "it_asset", aid)
        conn.commit()
        return _it_asset_detail(conn, aid)
    finally:
        conn.close()


@router.delete("/it-assets/{aid}", dependencies=[Depends(auth.require_role("manager"))])
def delete_it_asset(aid: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute("SELECT id FROM it_asset WHERE id = ?", (aid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="it asset not found")
        conn.execute("DELETE FROM it_asset WHERE id = ?", (aid,))
        _audit(conn, user, "it_asset.delete", "it_asset", aid)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# software licenses
# --------------------------------------------------------------------------- #
_LICENSE_COLS = (
    "name", "vendor", "product_code", "seats", "assigned_asset_id",
    "expiry_date", "annual_cost", "server_cost", "note",
)


class LicenseBody(BaseModel):
    name: Optional[str] = None
    vendor: Optional[str] = None
    product_code: Optional[str] = None
    seats: Optional[int] = None
    assigned_asset_id: Optional[int] = None
    expiry_date: Optional[str] = None
    annual_cost: Optional[float] = None
    server_cost: Optional[float] = None
    note: Optional[str] = None


def _license_detail(conn, lid):
    row = conn.execute(
        """SELECT l.*, a.name AS assigned_asset_name
           FROM software_license l
           LEFT JOIN it_asset a ON a.id = l.assigned_asset_id
           WHERE l.id = ?""",
        (lid,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["expiry_flag"] = _expiry_flag(d["expiry_date"], _today(conn))
    return d


@router.get("/software-licenses", dependencies=[Depends(auth.require_role("member"))])
def list_software_licenses():
    conn = get_conn()
    try:
        today = _today(conn)
        rows = _rows(conn.execute(
            """SELECT l.*, a.name AS assigned_asset_name
               FROM software_license l
               LEFT JOIN it_asset a ON a.id = l.assigned_asset_id
               ORDER BY l.name COLLATE NOCASE ASC, l.id ASC"""
        ))
        for d in rows:
            d["expiry_flag"] = _expiry_flag(d["expiry_date"], today)
        return rows
    finally:
        conn.close()


@router.get("/software-licenses/{lid}",
            dependencies=[Depends(auth.require_role("member"))])
def software_license_detail(lid: int):
    conn = get_conn()
    try:
        d = _license_detail(conn, lid)
        if d is None:
            raise HTTPException(status_code=404, detail="license not found")
        return d
    finally:
        conn.close()


@router.post("/software-licenses", dependencies=[Depends(auth.require_role("manager"))])
def create_software_license(body: LicenseBody,
                            user: dict = Depends(auth.require_role("manager"))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    data = body.model_dump(exclude_unset=True)
    conn = get_conn()
    try:
        cols, vals = [], []
        for f in _LICENSE_COLS:
            if f == "name":
                cols.append(f)
                vals.append(name)
            elif f in data:
                cols.append(f)
                vals.append(data[f])
        placeholders = ",".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO software_license ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        lid = cur.lastrowid
        _audit(conn, user, "license.create", "software_license", lid, name)
        conn.commit()
        _sync_notifications(conn)
        return _license_detail(conn, lid)
    finally:
        conn.close()


@router.patch("/software-licenses/{lid}",
              dependencies=[Depends(auth.require_role("manager"))])
def update_software_license(lid: int, body: LicenseBody,
                            user: dict = Depends(auth.require_role("manager"))):
    data = body.model_dump(exclude_unset=True)
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT id FROM software_license WHERE id = ?", (lid,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="license not found")
        if "name" in data and not (data["name"] or "").strip():
            raise HTTPException(status_code=400, detail="name is required")
        sets, vals = [], []
        for f in _LICENSE_COLS:
            if f in data:
                sets.append(f"{f} = ?")
                vals.append(data[f].strip() if f == "name" else data[f])
        if sets:
            vals.append(lid)
            conn.execute(
                f"UPDATE software_license SET {','.join(sets)} WHERE id = ?", vals
            )
        _audit(conn, user, "license.update", "software_license", lid)
        conn.commit()
        _sync_notifications(conn)
        return _license_detail(conn, lid)
    finally:
        conn.close()


@router.delete("/software-licenses/{lid}",
               dependencies=[Depends(auth.require_role("manager"))])
def delete_software_license(lid: int,
                            user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT id FROM software_license WHERE id = ?", (lid,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="license not found")
        conn.execute("DELETE FROM software_license WHERE id = ?", (lid,))
        _audit(conn, user, "license.delete", "software_license", lid)
        conn.commit()
        _sync_notifications(conn)
        return {"ok": True}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# glassware / dishware check-out
# --------------------------------------------------------------------------- #
_GLASSWARE_COLS = ("name", "kind", "identifier", "location_id", "status", "note")
_GLASSWARE_STATUSES = ("available", "checked_out", "broken", "retired")


class GlasswareBody(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    identifier: Optional[str] = None
    location_id: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None


class GlasswareCheckoutBody(BaseModel):
    due_at: Optional[str] = None
    purpose: Optional[str] = None


def _open_checkout(conn, gid):
    """The current open (unreturned) checkout for an item, or None."""
    row = conn.execute(
        """SELECT c.id, c.user_id, u.username AS held_by_username,
                  c.checked_out_at, c.due_at, c.purpose
           FROM glassware_checkout c
           LEFT JOIN app_user u ON u.id = c.user_id
           WHERE c.glassware_id = ? AND c.returned_at IS NULL
           ORDER BY c.checked_out_at DESC, c.id DESC
           LIMIT 1""",
        (gid,),
    ).fetchone()
    return dict(row) if row else None


def _glassware_detail(conn, gid):
    row = conn.execute(
        "SELECT * FROM glassware_item WHERE id = ?", (gid,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    now = conn.execute("SELECT datetime('now') AS n").fetchone()["n"]
    d["location_path"] = _location_path(conn, d["location_id"])
    open_co = _open_checkout(conn, gid)
    if d["status"] == "checked_out" and open_co:
        d["held_by_username"] = open_co["held_by_username"]
        d["checked_out_at"] = open_co["checked_out_at"]
        d["due_at"] = open_co["due_at"]
        d["overdue"] = bool(open_co["due_at"] and open_co["due_at"] < now)
    else:
        d["held_by_username"] = None
        d["checked_out_at"] = None
        d["due_at"] = None
        d["overdue"] = False
    d["checkouts"] = _rows(conn.execute(
        """SELECT c.id, c.user_id, u.username, c.checked_out_at, c.due_at,
                  c.returned_at, c.purpose, c.note
           FROM glassware_checkout c
           LEFT JOIN app_user u ON u.id = c.user_id
           WHERE c.glassware_id = ?
           ORDER BY c.checked_out_at DESC, c.id DESC""",
        (gid,),
    ))
    return d


@router.get("/glassware", dependencies=[Depends(auth.require_role("member"))])
def list_glassware():
    conn = get_conn()
    try:
        now = conn.execute("SELECT datetime('now') AS n").fetchone()["n"]
        rows = _rows(conn.execute(
            "SELECT * FROM glassware_item ORDER BY name COLLATE NOCASE ASC, id ASC"
        ))
        for d in rows:
            d["location_path"] = _location_path(conn, d["location_id"])
            open_co = (
                _open_checkout(conn, d["id"])
                if d["status"] == "checked_out" else None
            )
            if open_co:
                d["held_by_username"] = open_co["held_by_username"]
                d["checked_out_at"] = open_co["checked_out_at"]
                d["due_at"] = open_co["due_at"]
                d["overdue"] = bool(open_co["due_at"] and open_co["due_at"] < now)
            else:
                d["held_by_username"] = None
                d["checked_out_at"] = None
                d["due_at"] = None
                d["overdue"] = False
        return rows
    finally:
        conn.close()


# NOTE: this literal path is registered BEFORE /glassware/{gid} so it wins.
@router.get("/glassware/checkouts",
            dependencies=[Depends(auth.require_role("member"))])
def glassware_checkouts_board(open: bool = Query(True)):
    conn = get_conn()
    try:
        now = conn.execute("SELECT datetime('now') AS n").fetchone()["n"]
        where = "WHERE c.returned_at IS NULL" if open else ""
        rows = _rows(conn.execute(
            f"""SELECT c.id, c.glassware_id, g.name AS item_name,
                       c.user_id, u.username AS held_by_username,
                       c.checked_out_at, c.due_at, c.returned_at, c.purpose
                FROM glassware_checkout c
                JOIN glassware_item g ON g.id = c.glassware_id
                LEFT JOIN app_user u ON u.id = c.user_id
                {where}
                ORDER BY (c.due_at IS NULL), c.due_at ASC, c.id ASC"""
        ))
        for d in rows:
            d["overdue"] = bool(
                d["returned_at"] is None and d["due_at"] and d["due_at"] < now
            )
        return rows
    finally:
        conn.close()


@router.get("/glassware/{gid}", dependencies=[Depends(auth.require_role("member"))])
def glassware_detail(gid: int):
    conn = get_conn()
    try:
        d = _glassware_detail(conn, gid)
        if d is None:
            raise HTTPException(status_code=404, detail="glassware not found")
        return d
    finally:
        conn.close()


@router.post("/glassware", dependencies=[Depends(auth.require_role("manager"))])
def create_glassware(body: GlasswareBody,
                     user: dict = Depends(auth.require_role("manager"))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    status = body.status or "available"
    if status not in _GLASSWARE_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")
    data = body.model_dump(exclude_unset=True)
    conn = get_conn()
    try:
        cols, vals = [], []
        for f in _GLASSWARE_COLS:
            if f == "name":
                cols.append(f)
                vals.append(name)
            elif f == "status":
                cols.append(f)
                vals.append(status)
            elif f in data:
                cols.append(f)
                vals.append(data[f])
        placeholders = ",".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO glassware_item ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        gid = cur.lastrowid
        _audit(conn, user, "glassware.create", "glassware_item", gid, name)
        conn.commit()
        return _glassware_detail(conn, gid)
    finally:
        conn.close()


@router.patch("/glassware/{gid}", dependencies=[Depends(auth.require_role("manager"))])
def update_glassware(gid: int, body: GlasswareBody,
                     user: dict = Depends(auth.require_role("manager"))):
    data = body.model_dump(exclude_unset=True)
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT id FROM glassware_item WHERE id = ?", (gid,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="glassware not found")
        if "name" in data and not (data["name"] or "").strip():
            raise HTTPException(status_code=400, detail="name is required")
        if "status" in data and data["status"] not in _GLASSWARE_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")
        sets, vals = [], []
        for f in _GLASSWARE_COLS:
            if f in data:
                sets.append(f"{f} = ?")
                vals.append(data[f].strip() if f == "name" else data[f])
        if sets:
            vals.append(gid)
            conn.execute(
                f"UPDATE glassware_item SET {','.join(sets)} WHERE id = ?", vals
            )
        _audit(conn, user, "glassware.update", "glassware_item", gid)
        conn.commit()
        return _glassware_detail(conn, gid)
    finally:
        conn.close()


@router.delete("/glassware/{gid}", dependencies=[Depends(auth.require_role("manager"))])
def delete_glassware(gid: int, user: dict = Depends(auth.require_role("manager"))):
    conn = get_conn()
    try:
        if conn.execute(
            "SELECT id FROM glassware_item WHERE id = ?", (gid,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail="glassware not found")
        conn.execute("DELETE FROM glassware_checkout WHERE glassware_id = ?", (gid,))
        conn.execute("DELETE FROM glassware_item WHERE id = ?", (gid,))
        _audit(conn, user, "glassware.delete", "glassware_item", gid)
        conn.commit()
        _sync_notifications(conn)
        return {"ok": True}
    finally:
        conn.close()


@router.post("/glassware/{gid}/checkout",
             dependencies=[Depends(auth.require_role("member"))])
def checkout_glassware(gid: int, body: GlasswareCheckoutBody,
                       user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        item = conn.execute(
            "SELECT id, status FROM glassware_item WHERE id = ?", (gid,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="glassware not found")
        if item["status"] != "available":
            raise HTTPException(
                status_code=400, detail="item is not available for checkout"
            )
        uid = _current_uid(conn, user)
        conn.execute(
            """INSERT INTO glassware_checkout
                   (glassware_id, user_id, checked_out_at, due_at,
                    returned_at, purpose)
               VALUES (?, ?, datetime('now'), ?, NULL, ?)""",
            (gid, uid, body.due_at, body.purpose),
        )
        conn.execute(
            "UPDATE glassware_item SET status = 'checked_out' WHERE id = ?", (gid,)
        )
        _audit(conn, user, "glassware.checkout", "glassware_item", gid, body.purpose)
        conn.commit()
        _sync_notifications(conn)
        return _glassware_detail(conn, gid)
    finally:
        conn.close()


@router.post("/glassware/{gid}/return",
             dependencies=[Depends(auth.require_role("member"))])
def return_glassware(gid: int, user: dict = Depends(auth.require_role("member"))):
    conn = get_conn()
    try:
        item = conn.execute(
            "SELECT id, status FROM glassware_item WHERE id = ?", (gid,)
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="glassware not found")
        open_co = conn.execute(
            """SELECT id FROM glassware_checkout
               WHERE glassware_id = ? AND returned_at IS NULL
               ORDER BY checked_out_at DESC, id DESC LIMIT 1""",
            (gid,),
        ).fetchone()
        if item["status"] != "checked_out" or open_co is None:
            raise HTTPException(status_code=400, detail="item is not checked out")
        conn.execute(
            "UPDATE glassware_checkout SET returned_at = datetime('now') WHERE id = ?",
            (open_co["id"],),
        )
        conn.execute(
            "UPDATE glassware_item SET status = 'available' WHERE id = ?", (gid,)
        )
        _audit(conn, user, "glassware.return", "glassware_item", gid)
        conn.commit()
        _sync_notifications(conn)
        return _glassware_detail(conn, gid)
    finally:
        conn.close()
