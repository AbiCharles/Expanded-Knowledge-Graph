"""Auth: bcrypt password hashing + JWT tokens + FastAPI dependencies.

Demo-grade. One shared secret, HS256, 24h expiry, no refresh tokens, no
email verification. Sufficient for per-user case isolation.
"""
from __future__ import annotations

import logging
import os
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

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# tokenUrl points at our login endpoint; FastAPI uses it for the docs UI.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


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
    expires = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "exp": expires,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
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
    """Required-auth dependency. 401 if no/invalid token."""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
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
    """Optional-auth dependency. Returns None if no/invalid token (used by
    SSE streams and read-only endpoints that pre-existed auth)."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user_id = int(payload.get("sub", "0"))
    state = request.app.state.app_state
    with state.database.session() as session:
        row = session.get(UserRow, user_id)
        if row is None:
            return None
        return CurrentUser(id=row.id, username=row.username, role=row.role, display_name=row.display_name)


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
