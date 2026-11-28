import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from . import config, dispatcher
from .database import Base, SessionLocal, engine
from .models import Setting, User
from .pricing import DEFAULT_PRICING
from .routers import auth, customer, staff
from .security import hash_password

logging.basicConfig(level=logging.INFO)


def seed():
    with SessionLocal() as db:
        if not db.scalar(select(User.id).where(User.role == "admin")):
            db.add(User(email=config.ADMIN_EMAIL.lower(), full_name=config.ADMIN_NAME,
                        password_hash=hash_password(config.ADMIN_PASSWORD), role="admin"))
        if not db.get(Setting, "pricing"):
            db.add(Setting(key="pricing", value=json.dumps(DEFAULT_PRICING)))
        if not db.get(Setting, "auto_dispatch"):
            db.add(Setting(key="auto_dispatch", value="true"))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    seed()
    dispatcher.start()
    yield
    dispatcher.stop()


app = FastAPI(title="QuePrint API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(customer.router)
app.include_router(staff.router)
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
