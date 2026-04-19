import time

import jwt
from jwt.exceptions import InvalidTokenError

from app.config import settings


def generate_access_token(username: str) -> str:
    now = time.time()
    payload = {
        "sub": username,
        "type": "access",
        "iat": now,
        "exp": now + settings.jwt_expiration,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def generate_refresh_token(username: str) -> str:
    now = time.time()
    payload = {
        "sub": username,
        "type": "refresh",
        "iat": now,
        "exp": now + settings.jwt_refresh_expiration,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def validate_token(token: str) -> bool:
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return True
    except InvalidTokenError:
        return False


def is_refresh_token(token: str) -> bool:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("type") == "refresh"
    except InvalidTokenError:
        return False


def get_username_from_token(token: str) -> str:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    return payload["sub"]


def get_expiration() -> int:
    return settings.jwt_expiration