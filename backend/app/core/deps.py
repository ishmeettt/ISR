"""FastAPI dependencies: db session, current user, role guards.

Backend is the security boundary: every guard here runs on the server, and
judge isolation is enforced by query ownership (WHERE judge_id = me), never by
hiding UI.
"""
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..models import Session as DbSession, User, ensure_aware, utcnow
from .db import get_db

DbDep = Annotated[OrmSession, Depends(get_db)]


def _load_session(db: OrmSession, token: str | None) -> DbSession | None:
    if not token:
        return None
    token_hash = hashlib_sha256(token)
    sess = db.scalar(select(DbSession).where(DbSession.token_hash == token_hash))
    if sess is None or ensure_aware(sess.expires_at) < utcnow():
        return None
    return sess


def hashlib_sha256(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def get_current_user(
    db: DbDep,
    session: Annotated[str | None, Cookie(alias="session")] = None,
) -> User:
    sess = _load_session(db, session)
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def get_current_user_optional(
    db: DbDep,
    session: Annotated[str | None, Cookie(alias="session")] = None,
) -> User | None:
    sess = _load_session(db, session)
    if sess is None:
        return None
    return db.get(User, sess.user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    """Dependency factory: allow only the given roles."""

    def guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return user

    return guard


RoleOrganizer = Annotated[User, Depends(require_role("organizer", "admin"))]
RoleJudge = Annotated[User, Depends(require_role("judge"))]
RoleParticipant = Annotated[User, Depends(require_role("participant", "admin"))]
