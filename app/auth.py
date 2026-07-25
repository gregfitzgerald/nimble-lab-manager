"""Authentication + role-based authorization for Nimble Lab Manager.

Stdlib-only crypto: PBKDF2-HMAC-SHA256 for passwords (per-user random salt +
stored iteration count) and secrets.token_urlsafe for opaque session tokens
carried in the httponly 'nlm_session' cookie.

Set NLM_AUTH=off to disable auth entirely (every request acts as an admin);
the default is on.
"""

import hashlib
import hmac
import os
import secrets

from fastapi import Depends, HTTPException, Request

from .db import get_conn

COOKIE_NAME = "nlm_session"
CSRF_COOKIE_NAME = "nlm_csrf"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 210_000

# Role hierarchy, ascending. require_role(min_role) admits any role whose rank
# is at or above min_role's rank.
ROLE_RANK = {"viewer": 0, "member": 1, "manager": 2, "admin": 3}

# Demo logins ensured on every init_db/reset:
# (username, password, role, full_name, staff_id)
DEMO_USERS = [
    ("admin", "admin", "admin", "System Admin", None),
    ("manager", "manager", "manager", "J. Chen", 2),
    ("member", "member", "member", "S. Patel", 4),
    ("viewer", "viewer", "viewer", "L. Nguyen", 5),
]

# Mirrors schema.sql (with IF NOT EXISTS) so a lab.db created before auth
# existed upgrades in place on startup instead of crashing on login.
_AUTH_TABLES = """
CREATE TABLE IF NOT EXISTS app_user (
    id             INTEGER PRIMARY KEY,
    username       TEXT    NOT NULL UNIQUE,
    full_name      TEXT    NOT NULL,
    role           TEXT    NOT NULL CHECK (role IN ('admin','manager','member','viewer')),
    password_hash  TEXT    NOT NULL,
    password_salt  TEXT    NOT NULL,
    iterations     INTEGER NOT NULL,
    staff_id       INTEGER NULL REFERENCES staff(staff_id),
    created_at     TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES app_user(id),
    created_at  TIMESTAMP NOT NULL,
    expires_at  TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id);
"""


def auth_enabled():
    """Auth is on unless NLM_AUTH=off (read per-call so tests can flip it)."""
    return os.environ.get("NLM_AUTH", "on").strip().lower() != "off"


def secure_cookies():
    """Whether to set the Secure flag on auth cookies.

    Reads NLM_SECURE_COOKIES per-call; default False so local http works.
    """
    return os.environ.get("NLM_SECURE_COOKIES", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


# --------------------------------------------------------------------------- #
# password hashing
# --------------------------------------------------------------------------- #
def hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS):
    """Return (salt_hex, hash_hex, iterations) for a password."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    )
    return salt, digest.hex(), iterations


def verify_password(password, salt, stored_hash, iterations):
    """Constant-time check of a password against a stored salt/hash pair."""
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), stored_hash)


# --------------------------------------------------------------------------- #
# users + sessions
# --------------------------------------------------------------------------- #
def create_user(conn, username, password, role, full_name, staff_id=None):
    """Insert a user if the username is free; return the user id either way.

    Idempotent on username so seed/init/reset can call it repeatedly. Works
    with both Row-factory and plain-tuple connections. Does not commit.
    """
    if role not in ROLE_RANK:
        raise ValueError(f"unknown role: {role}")
    row = conn.execute(
        "SELECT id FROM app_user WHERE username = ?", (username,)
    ).fetchone()
    if row is not None:
        return row[0]
    salt, pw_hash, iterations = hash_password(password)
    cur = conn.execute(
        """INSERT INTO app_user
               (username, full_name, role, password_hash, password_salt,
                iterations, staff_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (username, full_name, role, pw_hash, salt, iterations, staff_id),
    )
    return cur.lastrowid


def ensure_demo_users(conn):
    """Make sure the auth tables and the four demo logins exist. Idempotent."""
    conn.executescript(_AUTH_TABLES)
    for username, password, role, full_name, staff_id in DEMO_USERS:
        create_user(conn, username, password, role, full_name, staff_id=staff_id)


def login_user(conn, username, password):
    """Verify credentials; on success create a session row and return
    (token, user_dict). Returns None on unknown username or bad password."""
    row = conn.execute(
        "SELECT * FROM app_user WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        # Burn a hash anyway so timing does not reveal valid usernames.
        hash_password(password)
        return None
    if not verify_password(
        password, row["password_salt"], row["password_hash"], row["iterations"]
    ):
        return None
    # A deactivated account cannot log in (treated like a bad password).
    try:
        if not row["is_active"]:
            return None
    except (IndexError, KeyError):
        pass
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM session WHERE expires_at <= datetime('now')")
    conn.execute(
        """INSERT INTO session (token, user_id, created_at, expires_at)
           VALUES (?, ?, datetime('now'), datetime('now', ?))""",
        (token, row["id"], f"+{SESSION_DAYS} day"),
    )
    conn.commit()
    user = {k: row[k] for k in ("id", "username", "full_name", "role")}
    return token, user


def delete_session(conn, token):
    conn.execute("DELETE FROM session WHERE token = ?", (token,))
    conn.commit()


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def current_user(request: Request):
    """Resolve the 'nlm_session' cookie to a live user, or raise 401.

    With NLM_AUTH=off this no-ops to a synthetic admin so the app runs open.
    """
    if not auth_enabled():
        return {"id": 0, "username": "admin", "full_name": "System Admin", "role": "admin"}
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    conn = get_conn()
    try:
        row = conn.execute(
            """SELECT u.id, u.username, u.full_name, u.role
               FROM session s
               JOIN app_user u ON u.id = s.user_id
               WHERE s.token = ? AND s.expires_at > datetime('now')
                 AND u.is_active = 1""",
            (token,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return dict(row)


def require_role(min_role):
    """Dependency factory: admit only users at or above min_role in the
    viewer < member < manager < admin hierarchy."""
    min_rank = ROLE_RANK[min_role]

    def dep(user: dict = Depends(current_user)):
        if ROLE_RANK.get(user["role"], -1) < min_rank:
            raise HTTPException(
                status_code=403, detail=f"requires {min_role} role or higher"
            )
        return user

    return dep
