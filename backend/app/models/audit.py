"""Audit trail: append-only by convention, no update/delete paths exist."""
from sqlalchemy import Column, DateTime, Integer, String, Text

from .base import Base, utcnow


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, nullable=True, index=True)
    actor_role = Column(String(32), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(64), nullable=True)
    before_state = Column(Text, nullable=True)
    after_state = Column(Text, nullable=True)
    session_id = Column(Integer, nullable=True)
    meta = Column("metadata", Text, nullable=True)  # DB column named "metadata"
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
