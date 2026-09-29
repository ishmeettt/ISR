"""Projects (T1)."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    external_id = Column(String(64), unique=True, nullable=False)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False, default="")
    repo_url = Column(String(512), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)  # null => draft
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    track = relationship("Track")
    team = relationship("Team")
