"""Authentication & RBAC (PRD §10.1).

- JWT access tokens (short-lived, <= 1h) + refresh tokens.
- bcrypt password hashing.
- Four-tier RBAC (Listener < Co-DJ < Host < Admin) enforced SERVER-SIDE via FastAPI
  dependencies, and reusable by the WebSocket handshake (`decode_token`).
"""
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import (
    ROLE_ADMIN,
    ROLE_CO_DJ,
    ROLE_HOST,
    ROLE_LISTENER,
    User,
)

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Role hierarchy — higher number implies all lower privileges.
ROLE_RANK = {ROLE_LISTENER: 0, ROLE_CO_DJ: 1, ROLE_HOST: 2, ROLE_ADMIN: 3}


def _encode(plain: str) -> bytes:
    # bcrypt hashes at most 72 bytes; truncate deterministically (standard practice).
    return plain.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_encode(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _create_token(subject: str, role: str, minutes: int, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user: User) -> str:
    return _create_token(str(user.id), user.role, settings.access_token_expire_minutes, "access")


def create_refresh_token(user: User) -> str:
    return _create_token(str(user.id), user.role, settings.refresh_token_expire_minutes, "refresh")


def decode_token(token: str) -> dict:
    """Decode & validate a JWT. Raises JWTError on failure. Used by HTTP deps AND the WS handshake."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise cred_exc
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise cred_exc
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise cred_exc
    user = db.get(User, user_id)
    if user is None:
        raise cred_exc
    return user


def require_role(minimum_role: str):
    """Dependency factory enforcing a minimum GLOBAL role (e.g. Admin-only endpoints).

    Lounge-scoped checks (Host/Co-DJ of a specific room) are done in the lounge router
    against LoungeMember, because a user may be Host of one room and Listener in another.
    """
    required_rank = ROLE_RANK[minimum_role]

    def _dep(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < required_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{minimum_role}' or higher",
            )
        return user

    return _dep


def has_lounge_privilege(member_role: str, minimum_role: str) -> bool:
    return ROLE_RANK.get(member_role, -1) >= ROLE_RANK[minimum_role]
