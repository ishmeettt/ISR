"""Trust Center endpoints (organizer-only). Detection is automatic; disposition is human."""
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from ..core.audit import record
from ..core.deps import DbDep, RoleOrganizer
from ..models import TrustFlag, utcnow
from ..services import trust

router = APIRouter(prefix="/api/trust", tags=["trust"])


def _flag_out(flag: TrustFlag) -> dict:
    return {
        "id": flag.id,
        "detector": flag.detector,
        "severity": flag.severity,
        "subject_type": flag.subject_type,
        "subject_id": flag.subject_id,
        "title": flag.title,
        "detail": flag.detail,
        "status": flag.status,
        "created_at": flag.created_at.isoformat(),
        "resolved_at": flag.resolved_at.isoformat() if flag.resolved_at else None,
    }


@router.post("/scan", status_code=status.HTTP_201_CREATED)
def run_scan(db: DbDep, organizer: RoleOrganizer) -> dict:
    """Run all detectors; upsert findings (existing dispositions are preserved)."""
    result = trust.scan(db)
    record(db, actor_id=organizer.id, actor_role=organizer.role,
           action="TRUST_SCAN", resource_type="trust_flag",
           metadata={"created": result["created"], "updated": result["updated"],
                     "open": result["open"]})
    db.commit()
    return result


@router.get("/flags")
def list_flags(db: DbDep, organizer: RoleOrganizer,
               flag_status: str | None = Query(default=None, pattern="^(open|resolved|dismissed)$"),
               detector: str | None = Query(default=None, max_length=64)) -> dict:
    stmt = select(TrustFlag).order_by(TrustFlag.id.asc())
    if flag_status:
        stmt = stmt.where(TrustFlag.status == flag_status)
    if detector:
        stmt = stmt.where(TrustFlag.detector == detector)
    flags = db.scalars(stmt).all()
    by_status = {"open": 0, "resolved": 0, "dismissed": 0}
    for f in flags:
        by_status[f.status] += 1
    return {"counts": by_status, "flags": [_flag_out(f) for f in flags]}


@router.post("/flags/{flag_id}/{disposition}", status_code=status.HTTP_200_OK)
def dispose(db: DbDep, organizer: RoleOrganizer,
            flag_id: int, disposition: str) -> dict:
    """Resolve or dismiss a flag. Audited; never affects scores or rankings."""
    if disposition not in ("resolved", "dismissed"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "disposition must be resolved|dismissed")
    flag = db.get(TrustFlag, flag_id)
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flag not found")
    before = {"status": flag.status}
    flag.status = disposition
    flag.resolved_by = organizer.id
    flag.resolved_at = utcnow()
    record(db, actor_id=organizer.id, actor_role=organizer.role,
           action="TRUST_FLAG_DISPOSITION", resource_type="trust_flag",
           resource_id=str(flag.id), before_state=before,
           after_state={"status": disposition, "detector": flag.detector})
    db.commit()
    return _flag_out(flag)
