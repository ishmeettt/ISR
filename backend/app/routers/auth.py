"""Auth: /api/auth/login, /api/auth/logout, /api/auth/me. Session cookie is HttpOnly.

Judges may supply an event code at login: it links them to that event (with
eligibility for its tracks) so the evaluator workspace can scope to the event.
"""
import datetime as dt
import hashlib

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from ..core.audit import record
from ..core.deps import CurrentUser, DbDep
from ..core.security import hash_password, new_session_token, verify_password
from ..models import Event, Session as DbSession, User, utcnow
from ..schemas import LoginIn, MeOut, SignupIn
from ..services.events import link_judge_to_event

router = APIRouter(prefix="/api/auth", tags=["auth"])
SESSION_TTL = dt.timedelta(days=7)


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, db: DbDep, response: Response) -> MeOut:
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    event_payload = None
    if body.event_code:
        code = body.event_code.strip().upper()
        event = db.scalar(select(Event).where(Event.code == code))
        if event is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No event with that code")
        if user.role == "judge":
            already_linked = link_judge_to_event(db, user, event)
            record(db, actor_id=user.id, actor_role=user.role,
                   action="JUDGE_EVENT_KNOWN" if already_linked else "JUDGE_EVENT_LINKED",
                   resource_type="event", resource_id=str(event.id))
        event_payload = {"name": event.name, "code": event.code}

    token = new_session_token()
    db.add(DbSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                     user_id=user.id, expires_at=utcnow() + SESSION_TTL))
    record(db, actor_id=user.id, actor_role=user.role, action="USER_LOGIN",
           resource_type="user", resource_id=str(user.id))
    db.commit()
    response.set_cookie(
        "session", token, httponly=True, samesite="lax", max_age=int(SESSION_TTL.total_seconds()),
    )
    return MeOut(email=user.email, name=user.name, role=user.role, event=event_payload)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, db: DbDep) -> dict:
    """Self-service signup: create the account, do NOT sign the user in.

    The UI returns to the login form so the person signs in with the
    credentials they just chose. New accounts are participants; judges and
    organizers are provisioned by the event organizer, not by signup.
    """
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")

    user = User(email=email, name=body.name.strip(), role="participant",
                password_hash=hash_password(body.password))
    db.add(user)
    db.flush()  # assign the PK before the audit row references it
    record(db, actor_id=None, actor_role="anon", action="USER_SIGNED_UP",
           resource_type="user", resource_id=email)
    db.commit()
    # Deliberately no session cookie: signup creates the account only.
    return {"email": user.email, "name": user.name, "role": user.role, "created": True}


@router.post("/logout")
def logout(db: DbDep, user: CurrentUser, response: Response) -> dict:
    db.query(DbSession).filter(DbSession.user_id == user.id).delete()
    db.commit()
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser) -> MeOut:
    return MeOut(email=user.email, name=user.name, role=user.role)
