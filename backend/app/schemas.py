from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class StaffCreateIn(RegisterIn):
    role: str = Field(default="staff", pattern="^(staff|admin)$")


class OptionsIn(BaseModel):
    paper_size: str = "A4"
    color_mode: str = "bw"
    sides: str = "single"
    copies: int = Field(default=1, ge=1, le=500)
    binding: str = "none"
    notes: str | None = Field(default=None, max_length=500)


class EstimateIn(OptionsIn):
    pages: int = Field(ge=1, le=2000)


class ConfirmIn(OptionsIn):
    pickup_at: datetime


class StatusIn(BaseModel):
    status: str
