import secrets
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import Job, Notification, Setting, utcnow
from .printing import send_to_printer

LABELS = {"draft": "Draft", "pending": "Pending", "processing": "Processing", "ready": "Ready for pickup",
          "completed": "Completed", "cancelled": "Cancelled", "failed": "Needs attention"}
ACTIVE = ("pending", "processing", "failed", "ready")
TRANSITIONS = {
    "pending": {"processing", "cancelled"},
    "processing": {"ready", "failed", "pending", "cancelled"},
    "failed": {"pending", "processing", "cancelled"},
    "ready": {"completed", "cancelled"},
    "completed": set(), "cancelled": set(), "draft": set(),
}
MESSAGES = {
    "pending": "Order {c} is confirmed and waiting in the queue.",
    "processing": "Order {c} is now being printed.",
    "ready": "Order {c} is ready for pickup.",
    "completed": "Order {c} was collected. Thank you!",
    "cancelled": "Order {c} was cancelled.",
    "failed": "Order {c} hit a problem. The shop is looking into it.",
}
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_tracking_code(db: Session) -> str:
    while True:
        code = "QP-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not db.scalar(select(Job.id).where(Job.tracking_code == code)):
            return code


def queue_position(db: Session, job: Job) -> int | None:
    """FIFO position among confirmed, waiting jobs (1 = next). 0 = being printed. None = not queued."""
    if job.status == "processing":
        return 0
    if job.status != "pending":
        return None
    ahead = db.scalar(select(func.count()).select_from(Job).where(
        Job.status == "pending",
        (Job.confirmed_at < job.confirmed_at) | ((Job.confirmed_at == job.confirmed_at) & (Job.id < job.id))))
    return ahead + 1


def iso(d: datetime | None):
    return d.isoformat() if d else None


def job_out(db: Session, job: Job, staff: bool = False) -> dict:
    out = {
        "id": job.id, "tracking_code": job.tracking_code, "document_name": job.original_name,
        "page_count": job.page_count, "paper_size": job.paper_size, "color_mode": job.color_mode,
        "sides": job.sides, "copies": job.copies, "binding": job.binding, "notes": job.notes,
        "pickup_at": iso(job.pickup_at), "total_cost": float(job.total_cost) if job.total_cost is not None else None,
        "status": job.status, "status_label": LABELS[job.status], "queue_position": queue_position(db, job),
        "created_at": iso(job.created_at), "confirmed_at": iso(job.confirmed_at), "ready_at": iso(job.ready_at),
    }
    if staff:
        out.update(customer_name=job.customer.full_name, customer_email=job.customer.email,
                   error_message=job.error_message, file_size=job.file_size)
    return out


def notify(db: Session, job: Job, message: str):
    db.add(Notification(user_id=job.customer_id, job_id=job.id, message=message))


def change_status(db: Session, job: Job, new: str, error: str | None = None):
    now = utcnow()
    job.status = new
    job.error_message = error if new == "failed" else None
    if new == "processing":
        job.started_at = now
    elif new == "ready":
        job.ready_at = now
    elif new == "completed":
        job.completed_at = now
    if new in MESSAGES:
        notify(db, job, MESSAGES[new].format(c=job.tracking_code))
    db.commit()


def print_job(db: Session, job: Job):
    """FR14-16: send to the wireless printer; on any error mark the job 'failed' for staff to see."""
    change_status(db, job, "processing")
    ok, msg = send_to_printer(job)
    if not ok:
        change_status(db, job, "failed", error=msg)
    return ok, msg


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str):
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()
