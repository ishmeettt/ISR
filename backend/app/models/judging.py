"""Judging domain (T2): judge eligibility, assignments, rubric, evaluations, AI reviews."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class JudgeTrack(Base):
    """Track a judge is eligible to review."""
    __tablename__ = "judge_tracks"
    __table_args__ = (UniqueConstraint("judge_id", "track_id", name="uq_judge_track"),)

    id = Column(Integer, primary_key=True)
    judge_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True)


class Assignment(Base):
    """A judge is assigned to review a project."""
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("judge_id", "project_id", name="uq_assignment"),)

    id = Column(Integer, primary_key=True)
    judge_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    project = relationship("Project")


class Rubric(Base):
    __tablename__ = "rubrics"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, default="Default rubric")


class RubricVersion(Base):
    __tablename__ = "rubric_versions"

    id = Column(Integer, primary_key=True)
    rubric_id = Column(Integer, ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    criteria = relationship("RubricCriterion", cascade="all, delete-orphan")


class RubricCriterion(Base):
    __tablename__ = "rubric_criteria"

    id = Column(Integer, primary_key=True)
    rubric_version_id = Column(Integer, ForeignKey("rubric_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    weight = Column(Numeric(5, 4), nullable=False)  # 0.30 = 30%
    max_score = Column(Integer, nullable=False, default=5)


class Evaluation(Base):
    """One judge's evaluation of one project, versioned by rubric."""
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("judge_id", "project_id", "rubric_version_id", name="uq_evaluation"),)

    id = Column(Integer, primary_key=True)
    judge_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    rubric_version_id = Column(Integer, ForeignKey("rubric_versions.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="submitted")  # in_progress|submitted|locked
    comment = Column(Text, nullable=False, default="")
    started_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    rubric = relationship("RubricVersion")
    scores = relationship("RubricScore", back_populates="evaluation", cascade="all, delete-orphan")


class RubricScore(Base):
    __tablename__ = "rubric_scores"

    id = Column(Integer, primary_key=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    criterion_id = Column(Integer, ForeignKey("rubric_criteria.id", ondelete="CASCADE"), nullable=False)
    score = Column(Integer, nullable=False)

    evaluation = relationship("Evaluation", back_populates="scores")
    criterion = relationship("RubricCriterion")


class AiReview(Base):
    """Advisory AI/static analysis of a repo, visible ONLY to the judge who ran it.

    The machine never assigns marks: this stores findings (errors, security
    loopholes, improvements) as context for the judge's manual evaluation.
    """
    __tablename__ = "ai_reviews"
    __table_args__ = (UniqueConstraint("judge_id", "project_id", name="uq_ai_review"),)

    id = Column(Integer, primary_key=True)
    judge_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    repo_url = Column(String(512), nullable=True)
    result = Column(Text, nullable=False, default="{}")  # JSON findings
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
