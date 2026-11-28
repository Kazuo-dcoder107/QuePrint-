from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..schemas import LoginIn, RegisterIn
from ..security import (create_token, current_user, hash_password, throttle_check, throttle_clear,
                        throttle_fail, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User):
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role}


@router.post("/register", status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Customers create their own account (role is always 'customer')."""
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, full_name=data.full_name.strip(), password_hash=hash_password(data.password), role="customer")
    db.add(user); db.commit()
    return {"token": create_token(user), "user": user_out(user)}


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    """FR1: sign in with registered credentials (customers, staff and admins)."""
    email = data.email.lower()
    key = f"{email}|{request.client.host if request.client else ''}"
    throttle_check(key)
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        throttle_fail(key)
        raise HTTPException(401, "Incorrect email or password.")
    throttle_clear(key)
    return {"token": create_token(user), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
