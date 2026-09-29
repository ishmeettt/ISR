"""Model registry: import all modules so Base.metadata sees every table."""
from .audit import AuditEvent
from .base import Base, ensure_aware, utcnow
from .events import Event, Track
from .judging import (
    AiReview,
    Assignment,
    Evaluation,
    JudgeTrack,
    Rubric,
    RubricCriterion,
    RubricScore,
    RubricVersion,
)
from .projects import Project
from .results import NormalizationRun, NormalizedScore, RankingResult
from .teams import Team, TeamMember
from .trust import TrustFlag
from .users import Session, User

__all__ = [
    "AiReview",
    "Assignment",
    "AuditEvent",
    "Base",
    "Evaluation",
    "Event",
    "ensure_aware",
    "JudgeTrack",
    "NormalizationRun",
    "NormalizedScore",
    "Project",
    "Rubric",
    "RubricCriterion",
    "RubricScore",
    "RubricVersion",
    "RankingResult",
    "Session",
    "Team",
    "TeamMember",
    "Track",
    "TrustFlag",
    "User",
    "utcnow",
]
