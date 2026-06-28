"""
JWT-based authentication helpers and FastAPI dependency.
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt

from database import get_conn

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY must be set in .env before starting the server.")

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain[:72].encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain[:72].encode(), hashed.encode())


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "username": username, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def get_current_user(token: str = Depends(_oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, email FROM users WHERE id=?", (user_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User not found.")
    return dict(row)
