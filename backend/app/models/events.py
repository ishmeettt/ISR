"""Event / Track aggregates."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base, utcnow


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    external_id = Column(String(64), unique=True, nullable=False)  # e.g. evt_01 from fixtures
    code = Column(String(12), unique=True, nullable=True, index=True)  # share code, e.g. SAMPLE26
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    judge_count = Column(Integer, nullable=False, default=3)  # target evaluators per project
    registration_open = Column(DateTime(timezone=True), nullable=True)
    registration_close = Column(DateTime(timezone=True), nullable=True)
    submissions_open = Column(DateTime(timezone=True), nullable=True)
    submissions_close = Column(DateTime(timezone=True), nullable=False)
    judging_close = Column(DateTime(timezone=True), nullable=True)
    # Optional per-event AI key (e.g. Groq). Empty = AI review stays fully
    # offline (static analysis only). Stored server-side, never sent back to
    # any client — the API only exposes a boolean "configured" flag.
    ai_api_key = Column(String(255), nullable=True, default=None)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    tracks = relationship(
        "Track", back_populates="event", cascade="all, delete-orphan",
        foreign_keys="Track.event_id",
    )

    @property
    def is_open_for_submissions(self) -> bool:
        from .base import ensure_aware, utcnow

        close = ensure_aware(self.submissions_close)
        if close is None or utcnow() > close:
            return False
        open_at = ensure_aware(self.submissions_open)
        return open_at is None or utcnow() >= open_at


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (UniqueConstraint("external_id", "event_id", name="uq_track_per_event"),)

    id = Column(Integer, primary_key=True)
    external_id = Column(String(64), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)

    event = relationship("Event", back_populates="tracks")
