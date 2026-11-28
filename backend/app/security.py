import hashlib, hmac, os, time
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from . import config
from .database import get_db
from .models import User

_ITER = 390_000
bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


def create_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=config.TOKEN_HOURS)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, config.SECRET_KEY, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Please sign in.")
    try:
        data = jwt.decode(cred.credentials, config.SECRET_KEY, algorithms=["HS256"])
        user = db.get(User, int(data["sub"]))
    except Exception:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    if not user or not user.is_active:
        raise HTTPException(401, "This account is not active.")
    return user


def require_roles(*roles):
    """FR2: only the listed roles may call the endpoint."""
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission to do this.")
        return user
    return dep


# very small in-memory login throttle (per email): 5 failures / 10 minutes
_fails: dict[str, list[float]] = {}


def throttle_check(key: str):
    now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < 600]
    if len(_fails[key]) >= 5:
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")


def throttle_fail(key: str):
    _fails.setdefault(key, []).append(time.time())


def throttle_clear(key: str):
    _fails.pop(key, None)
