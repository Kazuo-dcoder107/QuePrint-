"""FR15: background worker that sends the next eligible (oldest confirmed) job to the printer."""
import logging, threading, time
from datetime import timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import lazyload
from . import config
from .database import SessionLocal
from .files import remove_files
from .models import Job, utcnow
from .services import get_setting, print_job

log = logging.getLogger("queprint.dispatcher")
_stop = threading.Event()


def dispatch_once():
    with SessionLocal() as db:
        if get_setting(db, "auto_dispatch", "true") != "true":
            return
        active = db.scalar(select(func.count()).select_from(Job).where(Job.status == "processing"))
        if active >= config.MAX_ACTIVE_PRINTING:
            return
        job = db.scalars(select(Job).where(Job.status == "pending").order_by(Job.confirmed_at, Job.id)
                         .options(lazyload(Job.customer)).limit(1)
                         .with_for_update(skip_locked=True, of=Job)).first()
        if job:
            ok, msg = print_job(db, job)
            log.info("Dispatched %s -> %s (%s)", job.tracking_code, "ok" if ok else "failed", msg)


def cleanup_drafts():
    """Remove uploads that were never confirmed within 24 hours."""
    with SessionLocal() as db:
        old = db.scalars(select(Job).where(Job.status == "draft", Job.created_at < utcnow() - timedelta(hours=24))).all()
        for j in old:
            remove_files(j.stored_name, j.print_name)
            db.delete(j)
        db.commit()


def _loop():
    last_cleanup = 0.0
    while not _stop.wait(config.DISPATCH_INTERVAL):
        try:
            dispatch_once()
            if time.time() - last_cleanup > 3600:
                cleanup_drafts()
                last_cleanup = time.time()
        except Exception:
            log.exception("Dispatcher error")


def start():
    threading.Thread(target=_loop, name="queprint-dispatcher", daemon=True).start()


def stop():
    _stop.set()
