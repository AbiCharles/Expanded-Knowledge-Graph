"""Auth: bcrypt password hashing + JWT tokens + FastAPI dependencies.

Hardening notes (2026-Q2):

- ``JWT_SECRET`` is **required**. The backend refuses to start when it's
  unset or matches the built-in placeholder. Set ``HITL_ALLOW_DEFAULT_
  SECRET=1`` to bypass for transient local runs (warns loudly).
- Tokens carry a ``jti`` claim (random uuid) and are revocable via the
  ``RevokedTokenStore``. The ``/auth/logout`` endpoint adds the current
  token's jti; ``current_user`` rejects revoked tokens.
- Logins are rate-limited at the route level (see ``api/auth.py``).

Still demo-grade in three places: tokens are HS256 (single shared secret,
no key rotation), no refresh tokens (24h hard expiry), no email
verification or password reset.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select

from .persistence.db import UserRow

log = logging.getLogger(__name__)

_DEFAULT_SECRET = "dev-secret-change-me-in-production"
JWT_SECRET = os.environ.get("JWT_SECRET", _DEFAULT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# tokenUrl points at our login endpoint; FastAPI uses it for the docs UI.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def assert_jwt_secret_set() -> None:
    """Refuse to start when ``JWT_SECRET`` is unset or matches the placeholder.

    Set ``HITL_ALLOW_DEFAULT_SECRET=1`` to bypass for transient local runs
    (the bypass logs a loud warning). Production deploys must always set a
    real secret — the docker-compose stack already enforces this via
    ``${JWT_SECRET:?...}`` substitution.
    """
    if JWT_SECRET != _DEFAULT_SECRET:
        return
    if os.environ.get("HITL_ALLOW_DEFAULT_SECRET") == "1":
        log.warning(
            "JWT_SECRET is the built-in placeholder; HITL_ALLOW_DEFAULT_SECRET=1 "
            "is set so we'll boot anyway. Tokens are forgeable by anyone who "
            "reads this source — DO NOT use this in any deployment."
        )
        return
    raise RuntimeError(
        "JWT_SECRET is unset (or equal to the built-in placeholder). "
        "Set it to a strong random string before starting the backend:\n"
        "  echo \"JWT_SECRET=$(openssl rand -hex 32)\" >> .env\n"
        "For a transient local run without setting it, export "
        "HITL_ALLOW_DEFAULT_SECRET=1."
    )


# =============================================================================
# Token revocation — in-memory blocklist of jti claims.
#
# Sized for the lifetime of a single uvicorn process; that's enough for our
# 24h JWT expiry. A horizontally-scaled deploy would back this with Redis
# (the framework is already designed to swap in different stores).
# =============================================================================
class RevokedTokenStore:
    """Tracks revoked token jti claims with their expiry times.

    We prune expired entries on each ``add`` so the set doesn't grow
    unboundedly. ``is_revoked`` is the hot-path check on every request.
    """

    def __init__(self) -> None:
        # jti -> expiry datetime
        self._revoked: dict[str, datetime] = {}

    def add(self, jti: str, exp: datetime) -> None:
        self._prune()
        self._revoked[jti] = exp

    def is_revoked(self, jti: str) -> bool:
        return jti in self._revoked

    def _prune(self) -> None:
        now = datetime.now(timezone.utc)
        stale = [j for j, exp in self._revoked.items() if exp <= now]
        for j in stale:
            self._revoked.pop(j, None)

    def __len__(self) -> int:
        return len(self._revoked)


revoked_tokens = RevokedTokenStore()


@dataclass
class CurrentUser:
    id: int
    username: str
    role: str
    display_name: Optional[str]


# =============================================================================
# Hashing + tokens
# =============================================================================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user: UserRow) -> str:
    """Mint a fresh JWT for ``user``. The ``jti`` claim is unique per token
    and is what gets blocklisted on logout."""
    expires = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "jti": uuid.uuid4().hex,
        "exp": expires,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Verify signature + expiry; return the claims dict or None on failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


# =============================================================================
# FastAPI dependencies
# =============================================================================
async def current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> CurrentUser:
    """Required-auth dependency. Raises 401 on missing / invalid / revoked
    token, or when the user row no longer exists."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    jti = payload.get("jti")
    if jti and revoked_tokens.is_revoked(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token revoked")
    user_id = int(payload.get("sub", "0"))
    state = request.app.state.app_state
    with state.database.session() as session:
        row = session.get(UserRow, user_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
        return CurrentUser(id=row.id, username=row.username, role=row.role, display_name=row.display_name)


async def optional_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[CurrentUser]:
    """Optional-auth dependency. Returns ``None`` for missing / invalid
    tokens. Used by SSE streams (which can't send headers cleanly) and any
    read-only endpoint that wants the caller's identity but doesn't require
    it."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    jti = payload.get("jti")
    if jti and revoked_tokens.is_revoked(jti):
        return None
    user_id = int(payload.get("sub", "0"))
    state = request.app.state.app_state
    with state.database.session() as session:
        row = session.get(UserRow, user_id)
        if row is None:
            return None
        return CurrentUser(id=row.id, username=row.username, role=row.role, display_name=row.display_name)


async def current_token_payload(
    token: Optional[str] = Depends(oauth2_scheme),
) -> dict:
    """Return the raw claims of the caller's token. Used by the logout
    endpoint to read the jti so we can revoke it. Raises 401 if no token."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return payload


# =============================================================================
# Bootstrap
# =============================================================================
def ensure_default_admin(database) -> None:
    """Seed an `admin/admin` user on first startup so the demo isn't locked
    out. Operators should change the password (or delete the row) before any
    real deployment."""
    with database.session() as session:
        if session.execute(select(UserRow).limit(1)).scalar() is not None:
            return
        session.add(UserRow(
            username="admin",
            password_hash=hash_password("admin"),
            role="admin",
            display_name="Default Admin",
        ))
        session.commit()
        log.warning(
            "Seeded default admin user (admin / admin) — change this password "
            "via /api/auth/change-password before any real use."
        )
