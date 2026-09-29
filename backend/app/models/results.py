"""Results intelligence (FairScore): reproducible normalization + ranking.

A NormalizationRun is immutable once written: recomputing creates a new run,
never edits an old one, so any historical ranking can be re-derived exactly.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class NormalizationRun(Base):
    __tablename__ = "normalization_runs"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    method = Column(String(64), nullable=False, default="zscore_per_judge")
    params = Column(Text, nullable=False, default="{}")  # JSON: formula, sd type, tie-breakers
    status = Column(String(32), nullable=False, default="completed")
    project_count = Column(Integer, nullable=False, default=0)
    evaluation_count = Column(Integer, nullable=False, default=0)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class NormalizedScore(Base):
    """Per-evaluation intermediates: raw weighted composite, judge stats, z.

    Storing judge_mean/judge_sd beside z makes every number re-derivable from
    the row itself (normalization-proof style), not just from the inputs.
    """
    __tablename__ = "normalized_scores"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("normalization_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluation_id = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_weighted = Column(Float, nullable=False)  # Σ (score/max) × weight
    judge_mean = Column(Float, nullable=False)    # that judge's mean raw composite
    judge_sd = Column(Float, nullable=False)      # population sd of that judge's composites
    z_score = Column(Float, nullable=False)       # (raw - mean) / sd, 0 when sd == 0


class RankingResult(Base):
    __tablename__ = "ranking_results"
    __table_args__ = (UniqueConstraint("run_id", "project_id", name="uq_ranking"),)

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("normalization_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    final_score = Column(Float, nullable=False)   # mean z across the project's evaluations
    raw_weighted = Column(Float, nullable=False)  # mean raw composite, pre-normalization
    judge_count = Column(Integer, nullable=False, default=0)
    coverage_ok = Column(Boolean, nullable=False, default=False)
    explanation = Column(Text, nullable=False, default="{}")  # JSON blob for /why

    project = relationship("Project")
