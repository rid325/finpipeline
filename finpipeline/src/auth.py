# src/auth.py
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.config import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AUTH_USERNAME,
    AUTH_PASSWORD,
)

security = HTTPBearer()

USERS = {}


def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict) -> str:
    """Create a signed JWT token with expiry."""
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises 401 if invalid."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> str:
    """Dependency — extracts and validates user from Bearer token."""
    payload = decode_token(credentials.credentials)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return username


# A single demo user is intentionally configured through deployment secrets.
# If either value is absent, login stays disabled instead of falling back to a
# credential published in the repository.
if AUTH_USERNAME and AUTH_PASSWORD:
    USERS[AUTH_USERNAME] = {
        "username": AUTH_USERNAME,
        "hashed_password": hash_password(AUTH_PASSWORD),
    }
