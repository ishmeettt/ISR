"""Pydantic response schemas."""
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectOut(BaseModel):
    external_id: str
    title: str
    summary: str
    repo_url: str | None
    track: str
    team: str
    submitted_at: datetime | None

    model_config = {"from_attributes": True}


class LoginIn(BaseModel):
    email: str
    password: str
    event_code: str | None = Field(default=None, max_length=12)


class SignupIn(BaseModel):
    """Self-service account creation. Signup always yields a participant;
    judges and organizers are provisioned by the event organizer."""

    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class MeOut(BaseModel):
    email: str
    name: str
    role: str
    event: dict | None = None  # {name, code} when the login supplied an event_code

    model_config = {"from_attributes": True}


class SubmitIn(BaseModel):
    title: str
    summary: str = ""
    track: str | None = None
    repo_url: str | None = None


class ScoreOut(BaseModel):
    criterion: str
    weight: float
    max_score: int
    score: int


class EvaluationOut(BaseModel):
    project: str
    project_title: str
    comment: str
    submitted_at: datetime
    scores: list[ScoreOut]


class AssignmentOut(BaseModel):
    project: str
    project_title: str
    track: str
    completed: bool
