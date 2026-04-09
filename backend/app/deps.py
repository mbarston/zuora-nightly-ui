"""
FastAPI dependencies for auth — pull the current user out of the session
cookie.

The React SPA is the only consumer; there's no HTML redirect path left
(Phase 5c removed the Jinja routes). `current_user` raises a 401 when the
session is missing and the React app's fetch wrapper handles the bounce to
/login on the client side.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User


def _user_id_from_session(request: Request) -> int | None:
    return request.session.get("user_id")


def current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    uid = _user_id_from_session(request)
    if uid is None:
        return None
    return db.get(User, uid)


def current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Raise a 401 if not logged in. Used by every JSON endpoint."""
    user = current_user_optional(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user
