import re

from fastapi import Header, HTTPException

from .config import get_settings


def current_user(x_dev_user_id: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if settings.auth_mode != "development" or settings.app_env == "production":
        # Never fall back to a development identity when deployment authentication is selected.
        raise HTTPException(401, {"code": "AUTHENTICATION_REQUIRED", "message": "Deployment authentication is not configured"})
    identity = x_dev_user_id or "dev-user"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identity):
        raise HTTPException(400, {"code": "INVALID_DEV_IDENTITY", "message": "Invalid development user ID"})
    return identity
