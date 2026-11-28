from datetime import timedelta
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import config
from ..database import get_db
from ..files import remove_files, store_upload
from ..models import Job, Notification, User, utcnow
from ..pricing import estimate, get_pricing
from ..schemas import ConfirmIn, EstimateIn
from ..security import require_roles
from ..services import (ACTIVE, LABELS, change_status, job_out, new_tracking_code, queue_position)

router = APIRouter(prefix="/api", tags=["customer"])
customer = require_roles("customer")


# ---------- public ----------
@router.get("/config")
def public_config(db: Session = Depends(get_db)):
    return {"shop_name": config.SHOP_NAME, "pricing": get_pricing(db), "max_upload_mb": config.MAX_UPLOAD_MB,
            "max_pages": config.MAX_PAGES, "min_pickup_minutes": config.MIN_PICKUP_MINUTES,
            "allowed_types": ["PDF", "DOCX"]}


@router.post("/estimate")
def cost_estimate(data: EstimateIn, db: Session = Depends(get_db)):
    try:
        return estimate(data.pages, data.model_dump(), get_pricing(db))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/track/{code}")
def track(code: str, db: Session = Depends(get_db)):
    """Order status tracker by tracking code. Exposes no personal data or file names."""
    job = db.scalar(select(Job).where(Job.tracking_code == code.strip().upper(), Job.status != "draft"))
    if not job:
        raise HTTPException(404, "No order found with that tracking code.")
    return {"tracking_code": job.tracking_code, "status": job.status, "status_label": LABELS[job.status],
            "queue_position": queue_position(db, job), "pickup_at": job.pickup_at.isoformat() if job.pickup_at else None,
            "total_cost": float(job.total_cost) if job.total_cost is not None else None,
            "updated": (job.ready_at or job.started_at or job.confirmed_at).isoformat()}


@router.get("/board")
def live_board(db: Session = Depends(get_db)):
    """Live print-queue board: codes are masked so customers cannot look up each other's orders."""
    jobs = db.scalars(select(Job).where(Job.status.in_(("pending", "processing", "ready")))
                      .order_by(Job.confirmed_at, Job.id).limit(100)).all()
    rows = [{"code": j.tracking_code[:5] + "\u2022" * 3 + j.tracking_code[-1], "status": j.status,
             "status_label": LABELS[j.status], "position": queue_position(db, j), "pages": j.page_count * j.copies}
            for j in jobs]
    return {"jobs": rows, "waiting": sum(r["status"] == "pending" for r in rows),
            "printing": sum(r["status"] == "processing" for r in rows),
            "ready": sum(r["status"] == "ready" for r in rows)}


# ---------- customer ----------
def _own_job(db, user, job_id) -> Job:
    job = db.get(Job, job_id)
    if not job or job.customer_id != user.id:
        raise HTTPException(404, "Order not found.")
    return job


@router.post("/jobs", status_code=201)
def upload_document(file: UploadFile = File(...), user: User = Depends(customer), db: Session = Depends(get_db)):
    """FR3-6: validated upload, stored on the server as a draft until the customer confirms."""
    info = store_upload(file)
    job = Job(tracking_code=new_tracking_code(db), customer_id=user.id, status="draft", **info)
    db.add(job); db.commit()
    return job_out(db, job)


@router.get("/jobs")
def my_jobs(user: User = Depends(customer), db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).where(Job.customer_id == user.id, Job.status != "draft")
                      .order_by(Job.created_at.desc()).limit(100)).all()
    return [job_out(db, j) for j in jobs]


@router.get("/jobs/{job_id}")
def my_job(job_id: int, user: User = Depends(customer), db: Session = Depends(get_db)):
    return job_out(db, _own_job(db, user, job_id))


@router.post("/jobs/{job_id}/confirm")
def confirm_job(job_id: int, data: ConfirmIn, user: User = Depends(customer), db: Session = Depends(get_db)):
    """FR8-10: preferences + pickup reservation, then the confirmed request enters the FIFO queue."""
    job = _own_job(db, user, job_id)
    if job.status != "draft":
        raise HTTPException(409, "This order was already submitted.")
    earliest = utcnow() + timedelta(minutes=config.MIN_PICKUP_MINUTES - 1)
    pickup = data.pickup_at if data.pickup_at.tzinfo else data.pickup_at.replace(tzinfo=utcnow().tzinfo)
    if pickup < earliest:
        raise HTTPException(422, f"Choose a pickup time at least {config.MIN_PICKUP_MINUTES} minutes from now.")
    try:
        est = estimate(job.page_count, data.model_dump(), get_pricing(db))
    except ValueError as e:
        raise HTTPException(422, str(e))
    for f in ("paper_size", "color_mode", "sides", "copies", "binding"):
        setattr(job, f, getattr(data, f))
    job.notes = (data.notes or "").strip() or None
    job.pickup_at, job.total_cost, job.confirmed_at = pickup, est["total"], utcnow()
    change_status(db, job, "pending")
    return job_out(db, job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, user: User = Depends(customer), db: Session = Depends(get_db)):
    job = _own_job(db, user, job_id)
    if job.status == "draft":
        remove_files(job.stored_name, job.print_name)
        db.delete(job); db.commit()
        return {"deleted": True}
    if job.status != "pending":
        raise HTTPException(409, "Only orders that have not started printing can be cancelled.")
    change_status(db, job, "cancelled")
    return job_out(db, job)


@router.get("/notifications")
def notifications(user: User = Depends(require_roles("customer", "staff", "admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id)
                      .order_by(Notification.id.desc()).limit(30)).all()
    return [{"id": n.id, "message": n.message, "is_read": n.is_read, "created_at": n.created_at.isoformat()} for n in rows]


@router.post("/notifications/read")
def mark_read(user: User = Depends(require_roles("customer", "staff", "admin")), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))):
        n.is_read = True
    db.commit()
    return {"ok": True}
