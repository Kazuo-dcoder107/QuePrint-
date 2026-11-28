import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .. import config
from ..database import get_db
from ..models import Job, Setting, User
from ..pricing import get_pricing, validate_pricing
from ..schemas import StaffCreateIn, StatusIn
from ..security import hash_password, require_roles
from ..services import ACTIVE, TRANSITIONS, change_status, get_setting, job_out, print_job, set_setting

router = APIRouter(prefix="/api", tags=["staff"])
staff_only = require_roles("staff", "admin")
admin_only = require_roles("admin")


def _job(db, job_id) -> Job:
    job = db.get(Job, job_id)
    if not job or job.status == "draft":
        raise HTTPException(404, "Order not found.")
    return job


@router.get("/staff/jobs")
def list_jobs(status: str = Query("active"), user=Depends(staff_only), db: Session = Depends(get_db)):
    """Operator print dashboard: FIFO list of job tickets."""
    q = select(Job).where(Job.status != "draft")
    if status == "active":
        q = q.where(Job.status.in_(ACTIVE))
    elif status != "all":
        q = q.where(Job.status == status)
    jobs = db.scalars(q.order_by(Job.confirmed_at, Job.id).limit(300)).all()
    return [job_out(db, j, staff=True) for j in jobs]


@router.get("/staff/stats")
def stats(user=Depends(staff_only), db: Session = Depends(get_db)):
    rows = dict(db.execute(select(Job.status, func.count()).where(Job.status != "draft").group_by(Job.status)).all())
    return {"counts": rows, "auto_dispatch": get_setting(db, "auto_dispatch", "true") == "true",
            "printer_mode": config.PRINTER_MODE}


@router.get("/staff/jobs/{job_id}")
def ticket(job_id: int, user=Depends(staff_only), db: Session = Depends(get_db)):
    return job_out(db, _job(db, job_id), staff=True)


@router.patch("/staff/jobs/{job_id}/status")
def set_status(job_id: int, data: StatusIn, user=Depends(staff_only), db: Session = Depends(get_db)):
    job = _job(db, job_id)
    if data.status not in TRANSITIONS[job.status]:
        raise HTTPException(409, f"An order that is '{job.status}' cannot move to '{data.status}'.")
    change_status(db, job, data.status)
    return job_out(db, job, staff=True)


@router.post("/staff/jobs/{job_id}/print")
def print_now(job_id: int, user=Depends(staff_only), db: Session = Depends(get_db)):
    """Send (or re-send) a job to the printer manually."""
    job = _job(db, job_id)
    if job.status not in ("pending", "processing", "failed"):
        raise HTTPException(409, "Only waiting, printing, or failed orders can be sent to the printer.")
    ok, msg = print_job(db, job)
    return {"ok": ok, "message": msg, "job": job_out(db, job, staff=True)}


@router.get("/staff/jobs/{job_id}/file")
def download(job_id: int, which: str = "print", user=Depends(staff_only), db: Session = Depends(get_db)):
    job = _job(db, job_id)
    name = job.stored_name if which == "original" else job.print_name
    path = config.UPLOAD_DIR / name
    if not path.exists():
        raise HTTPException(404, "The file is missing from the server.")
    if which == "original":
        return FileResponse(path, filename=job.original_name)
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})


# ---------- admin ----------
@router.put("/admin/pricing")
def update_pricing(body: dict, user=Depends(admin_only), db: Session = Depends(get_db)):
    try:
        clean = validate_pricing(body)
    except ValueError as e:
        raise HTTPException(422, str(e))
    set_setting(db, "pricing", json.dumps(clean))
    return clean


@router.put("/admin/auto-dispatch")
def set_auto_dispatch(body: dict, user=Depends(admin_only), db: Session = Depends(get_db)):
    set_setting(db, "auto_dispatch", "true" if body.get("enabled") else "false")
    return {"auto_dispatch": bool(body.get("enabled"))}


@router.get("/admin/users")
def list_staff(user=Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.role.in_(("staff", "admin"))).order_by(User.id)).all()
    return [{"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active} for u in rows]


@router.post("/admin/users", status_code=201)
def create_staff(data: StaffCreateIn, user=Depends(admin_only), db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists.")
    db.add(User(email=email, full_name=data.full_name.strip(), password_hash=hash_password(data.password), role=data.role))
    db.commit()
    return {"ok": True}


@router.patch("/admin/users/{user_id}")
def toggle_user(user_id: int, body: dict, user=Depends(admin_only), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target or target.role == "customer":
        raise HTTPException(404, "Staff account not found.")
    if target.id == user.id:
        raise HTTPException(409, "You cannot deactivate your own account.")
    target.is_active = bool(body.get("is_active"))
    db.commit()
    return {"ok": True}
