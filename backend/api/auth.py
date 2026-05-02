"""Auth endpoints: register, login, me, change-password."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..auth import (
    CurrentUser,
    create_access_token,
    current_user,
    hash_password,
    verify_password,
)
from ..persistence.db import UserRow

router = APIRouter(tags=["auth"], prefix="/auth")


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    display_name: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class MeOut(BaseModel):
    id: int
    username: str
    role: str
    display_name: str | None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4, max_length=128)


@router.post("/register", response_model=TokenOut)
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
def login(form: OAuth2PasswordRequestForm = Depends(), request: Request = None) -> TokenOut:
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
