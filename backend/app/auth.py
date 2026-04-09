"""
Google OAuth login + logout + optional dev bypass.

Flow:
  GET  /login          → renders login.html (button linking to /auth/google)
  GET  /auth/google    → redirects to Google consent
  GET  /auth/callback  → handles Google's redirect, upserts a User row,
                          sets request.session["user_id"], redirects to /
  POST /auth/logout    → clears session, redirects to /login
  POST /auth/dev-login → (only when DEV_AUTH_BYPASS=true) creates or reuses
                          a local dev user with a fake email

The session cookie is signed with SESSION_SECRET via SessionMiddleware
(configured in main.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User


router = APIRouter()


# --- Google OAuth client ---------------------------------------------------

oauth = OAuth()

if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def _upsert_user(db: Session, *, email: str, name: str, picture: str) -> User:
    user = db.query(User).filter(User.email == email).one_or_none()
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(email=email, name=name, picture_url=picture, last_login_at=now)
        db.add(user)
    else:
        user.name = name or user.name
        user.picture_url = picture or user.picture_url
        user.last_login_at = now
    db.commit()
    db.refresh(user)
    return user


def _email_allowed(email: str) -> bool:
    domain = settings.ALLOWED_EMAIL_DOMAIN.strip().lower()
    if not domain:
        return True
    return email.lower().endswith("@" + domain)


# --- routes ----------------------------------------------------------------


@router.get("/auth/google")
async def auth_google(request: Request):
    if "google" not in oauth._clients:
        raise HTTPException(
            status_code=500,
            detail=(
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET in .env, or enable DEV_AUTH_BYPASS for local dev."
            ),
        )
    redirect_uri = f"{settings.APP_BASE_URL.rstrip('/')}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"OAuth error: {e.error}") from e

    userinfo = token.get("userinfo") or {}
    email = userinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google did not return an email address")

    if not _email_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Email domain not allowed. This instance is restricted to "
                f"@{settings.ALLOWED_EMAIL_DOMAIN} accounts."
            ),
        )

    user = _upsert_user(
        db,
        email=email,
        name=userinfo.get("name") or "",
        picture=userinfo.get("picture") or "",
    )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/auth/dev-login")
async def auth_dev_login(request: Request, db: Session = Depends(get_db)):
    """Dev-only shortcut. Creates a fake user so you can test without Google OAuth."""
    if not settings.DEV_AUTH_BYPASS:
        raise HTTPException(status_code=404)
    user = _upsert_user(
        db,
        email="dev@localhost",
        name="Dev User",
        picture="",
    )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
