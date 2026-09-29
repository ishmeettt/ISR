"""Signup (self-service participant accounts) and gallery access control.

The gallery used to be public; it is now behind login, so anonymous callers
get 401 and every signed-in role can read it. Signup always creates a
participant account and refuses duplicate emails with 409. It deliberately
does NOT sign the user in: the UI returns to the login form and the person
signs in with the credentials they just chose.
"""
from sqlalchemy import select

from app.models import User


def test_gallery_requires_login(client):
    r = client.get("/api/gallery")
    assert r.status_code == 401
    payload = r.json()
    assert "authenticated" in payload["detail"].lower()


def test_gallery_open_to_every_signed_in_role(client, organizer_cookie, judge_a_cookie,
                                              participant_cookie):
    for cookie in (organizer_cookie, judge_a_cookie, participant_cookie):
        r = client.get("/api/gallery", headers=cookie)
        assert r.status_code == 200
        projects = r.json()
        assert isinstance(projects, list) and projects, "seeded gallery must not be empty"


def test_signup_creates_account_without_signing_in(client, db_session):
    r = client.post("/api/auth/signup", json={
        "email": "newperson@example.org",
        "name": "New Person",
        "password": "sup3r-secret-pw",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "newperson@example.org"
    assert body["role"] == "participant"
    assert body["created"] is True
    # No session is issued at signup: the caller is still anonymous.
    assert "set-cookie" not in r.headers
    r_anon = client.get("/api/auth/me")
    assert r_anon.status_code == 401

    # The account exists with a proper PBKDF2 hash (never plaintext).
    user = db_session.scalar(select(User).where(User.email == "newperson@example.org"))
    assert user is not None
    assert user.password_hash.startswith("pbkdf2$")

    # The intended flow: sign in afterwards with the chosen credentials.
    r_login = client.post("/api/auth/login", json={
        "email": "newperson@example.org", "password": "sup3r-secret-pw",
    })
    assert r_login.status_code == 200
    r_me = client.get("/api/auth/me")
    assert r_me.status_code == 200
    assert r_me.json()["email"] == "newperson@example.org"

    # ...and that fresh account can read the gallery.
    r3 = client.get("/api/gallery")
    assert r3.status_code == 200


def test_signup_rejects_duplicate_email(client):
    r = client.post("/api/auth/signup", json={
        "email": "newperson@example.org",
        "name": "Impostor",
        "password": "another-secret-pw",
    })
    assert r.status_code == 409


def test_signup_rejects_short_password(client):
    r = client.post("/api/auth/signup", json={
        "email": "shortpw@example.org",
        "name": "Short PW",
        "password": "short",
    })
    assert r.status_code == 422
