from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('customer','staff','admin')", name="ck_users_role"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="customer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "print_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('draft','pending','processing','ready','completed','cancelled','failed')",
                        name="ck_jobs_status"),
        CheckConstraint("copies BETWEEN 1 AND 500", name="ck_jobs_copies"),
        Index("ix_jobs_queue", "status", "confirmed_at", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    customer: Mapped["User"] = relationship(lazy="joined")

    # stored document (FR3-FR6)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80))       # uploaded file on disk
    print_name: Mapped[str] = mapped_column(String(80))        # PDF actually sent to printer
    file_size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)

    # printing preferences (FR7)
    paper_size: Mapped[str] = mapped_column(String(20), default="A4")
    color_mode: Mapped[str] = mapped_column(String(10), default="bw")
    sides: Mapped[str] = mapped_column(String(10), default="single")
    copies: Mapped[int] = mapped_column(Integer, default=1)
    binding: Mapped[str] = mapped_column(String(30), default="none")
    notes: Mapped[str | None] = mapped_column(String(500))
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # FR8
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    status: Mapped[str] = mapped_column(String(20), default="draft")
    error_message: Mapped[str | None] = mapped_column(Text)                      # FR16
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # FIFO key (FR12/13)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("print_jobs.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(String(300))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
