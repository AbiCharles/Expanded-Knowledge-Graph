"""Auth endpoints: register, login, logout, me, change-password.

Rate-limiting policy (enforced via slowapi at the route level):
- ``/login`` and ``/register``: 10 attempts per minute per source IP.
  Tighter than the global default to make password-spray attacks
  expensive; legitimate operators won't notice.
- Set ``HITL_DISABLE_RATE_LIMIT=1`` to bypass for tests / local dev.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..auth import (
    CurrentUser,
    create_access_token,
    current_user,
    current_token_payload,
    hash_password,
    revoked_tokens,
    verify_password,
)
from ..persistence.db import UserRow

router = APIRouter(tags=["auth"], prefix="/auth")

# Per-IP limiter for login/register. Other endpoints use the app-wide
# limiter (set up in main.py). Keeping a separate instance lets us tune the
# ratio without touching the global one. ``HITL_DISABLE_RATE_LIMIT=1`` makes
# the limiter a no-op (used by the pytest suite).
_DISABLED = os.environ.get("HITL_DISABLE_RATE_LIMIT") == "1"
limiter = Limiter(key_func=get_remote_address, enabled=not _DISABLED)


class RegisterIn(BaseModel):
    """Body for POST /api/auth/register — self-service signup."""

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    display_name: str | None = None


class TokenOut(BaseModel):
    """Response for register + login — JWT plus a small user summary the
    frontend caches in localStorage."""

    access_token: str
    token_type: str = "bearer"
    user: dict


class MeOut(BaseModel):
    """Response for GET /api/auth/me — used by the frontend to validate
    a cached token at app load."""

    id: int
    username: str
    role: str
    display_name: str | None


class ChangePasswordIn(BaseModel):
    """Body for POST /api/auth/change-password — requires the current
    password as a defence against session hijack."""

    current_password: str
    new_password: str = Field(min_length=4, max_length=128)


@router.post("/register", response_model=TokenOut)
@limiter.limit("10/minute")
def register(payload: RegisterIn, request: Request) -> TokenOut:
    state = request.app.state.app_state
    with state.database.session() as session:
        existing = session.execute(
            select(UserRow).where(UserRow.username == payload.username)
        ).scalar()
        if existing is not None:
            raise HTTPException(status_code=409, detail="username already taken")
        user = UserRow(
            username=payload.username,
            password_hash=hash_password(payload.password),
            role="user",
            display_name=payload.display_name or payload.username,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_access_token(user)
        return TokenOut(
            access_token=token,
            user={"id": user.id, "username": user.username, "role": user.role, "display_name": user.display_name},
        )


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()) -> TokenOut:
    state = request.app.state.app_state
    with state.database.session() as session:
        user = session.execute(
            select(UserRow).where(UserRow.username == form.username)
        ).scalar()
        if user is None or not verify_password(form.password, user.password_hash or ""):
            raise HTTPException(status_code=401, detail="invalid username or password")
        token = create_access_token(user)
        return TokenOut(
            access_token=token,
            user={"id": user.id, "username": user.username, "role": user.role, "display_name": user.display_name},
        )


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser = Depends(current_user)) -> MeOut:
    return MeOut(id=user.id, username=user.username, role=user.role, display_name=user.display_name)


@router.post("/logout")
def logout(payload: dict = Depends(current_token_payload)) -> dict:
    """Revoke the caller's token by adding its ``jti`` to the in-process
    blocklist. Subsequent requests with this token fail at ``current_user``.

    Client-side, the frontend also clears localStorage; this server-side
    revocation is the belt-and-braces against a stolen token still being
    valid until expiry.
    """
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        # `exp` is a unix timestamp; convert to aware datetime.
        revoked_tokens.add(jti, datetime.fromtimestamp(exp, tz=timezone.utc))
    return {"ok": True}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
) -> dict:
    state = request.app.state.app_state
    with state.database.session() as session:
        row = session.get(UserRow, user.id)
        if row is None or not verify_password(payload.current_password, row.password_hash or ""):
            raise HTTPException(status_code=403, detail="current password incorrect")
        row.password_hash = hash_password(payload.new_password)
        session.commit()
    return {"ok": True}
