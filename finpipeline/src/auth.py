# src/auth.py
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

security = HTTPBearer()

# in production these come from a database
# hardcoded user is sufficient to demonstrate the auth pattern
USERS = {
    "admin": {
        "username": "admin",
        "hashed_password": None  # set below on module load
    }
}


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
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> str:
    """Dependency — extracts and validates user from Bearer token."""
    payload = decode_token(credentials.credentials)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return username


# set hashed password on module load
USERS["admin"]["hashed_password"] = hash_password("adminpassword123")
