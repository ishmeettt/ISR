"""Trust engine: anomaly findings.

Flags detect anomalies; they never convict. Final results are computed from
scores only — a flag's disposition (resolve/dismiss) is an organizer decision
and is audited, but it does not silently alter any ranking.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .base import Base, utcnow


class TrustFlag(Base):
    __tablename__ = "trust_flags"
    __table_args__ = (UniqueConstraint("flag_key", name="uq_trust_flag_key"),)

    id = Column(Integer, primary_key=True)
    flag_key = Column(String(255), nullable=False, index=True)  # stable identity: detector + subject
    detector = Column(String(64), nullable=False)               # uniform_judge|low_coverage|out_of_track|duplicate_submission
    severity = Column(String(16), nullable=False, default="medium")  # info|medium|high
    subject_type = Column(String(64), nullable=False)           # user|project
    subject_id = Column(Integer, nullable=True)                 # FK to users.id / projects.id where applicable
    title = Column(String(255), nullable=False)
    detail = Column(Text, nullable=False, default="{}")         # JSON evidence
    status = Column(String(16), nullable=False, default="open")  # open|resolved|dismissed
    resolved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
