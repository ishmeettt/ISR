"""Audit service: the single way audit events are written.

The audit_events table is append-only by convention: application code must never
UPDATE or DELETE rows here (no update paths are exposed anywhere in the API).
"""
import json
from typing import Any

from sqlalchemy.orm import Session

from ..models.audit import AuditEvent


def record(
    db: Session,
    *,
    actor_id: int | None,
    actor_role: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    session_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_state=json.dumps(before_state, default=str) if before_state is not None else None,
            after_state=json.dumps(after_state, default=str) if after_state is not None else None,
            session_id=session_id,
            meta=json.dumps(metadata, default=str) if metadata is not None else None,
        )
    )
